"""Tool handlers — wrap usdctofiat.cashout. No keys. mode required."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

# Matched after _normalise_name, which folds case and drops separators, so one
# entry here covers private_key, privateKey, PRIVATE_KEY and private-key alike.
# An exact-string list could not: it refused "private_key" and let "PRIVATE_KEY"
# -- the spelling the env var everyone copies from actually uses -- through.
_BANNED_KEY_NAMES = frozenset(
    {
        "privatekey",
        "evmprivatekey",
        "signingkey",
        "walletkey",
        "keystore",
        "key",
        "secret",
        "secretkey",
        "mnemonic",
        "seed",
        "seedphrase",
    }
)

# Substrings, for the qualified names a model invents around the same material:
# wallet_private_key, userMnemonic, backup_seed_phrase. Only markers that cannot
# mean anything else belong here -- a bare "key" would refuse ordinary words.
_BANNED_KEY_MARKERS = (
    "privatekey",
    "secretkey",
    "signingkey",
    "mnemonic",
    "seedphrase",
    "keystore",
)


# The indexer keys a deposit by ``<escrow address>_<EscrowV2 id>``, and that
# composite is the only id a caller ever sees: it is what usdctofiat_deposits
# hands back and what usdctofiat_watch resolves. The vendor withdraws on the
# EscrowV2 id alone -- ``withdraw_tx(int(deposit_id))`` -- so the listed id
# pasted straight back is a bare ``invalid literal for int() with base 10``.
_COMPOSITE_DEPOSIT_ID = re.compile(r"^(0[xX][0-9a-fA-F]{40})_([0-9]+)$")
_ESCROW_DEPOSIT_ID = re.compile(r"^[0-9]+$")

# The fiat currencies EscrowV2 deposits are actually denominated in on Base,
# read off the live indexer (`DepositCurrencyLiquidity.currencyCode`, distinct)
# and resolved back through keccak256 of the ISO code.
#
# The vendor validates `platform` against its catalog and refuses an unknown one
# by name, but `calldata.currency_hash` falls through to `keccak(text=key)` for
# anything it does not recognise. So "euros", "EURO" or "dollars" -- the codes a
# model writes when the user says "cash out to euros" -- each hash to a
# well-formed 32 bytes and ride into a real createDeposit tx. The reply is an
# ordinary unsigned prepare with nothing in it that says the currency is
# meaningless, so signing it moves USDC into a deposit no taker can fill and
# only usdctofiat_withdraw can undo.
#
# Refusing is deliberately strict, and asymmetric on purpose: a currency the
# protocol adds later costs a caller a named error they can act on, while a
# currency it never had costs them a locked deposit. scripts/live_indexer_check.py
# re-derives this set weekly and fails when it drifts.
SUPPORTED_CURRENCIES = frozenset(
    {
        "AED", "ARS", "AUD", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP",
        "HKD", "HUF", "IDR", "ILS", "INR", "JPY", "KES", "MXN", "MYR", "NOK",
        "NZD", "PHP", "PLN", "RON", "SAR", "SEK", "SGD", "THB", "TRY", "UGX",
        "USD", "VND", "ZAR",
    }
)


class InvalidDepositId(Exception):
    """The deposit id is neither id ``usdctofiat_withdraw`` advertises.

    Carries the ``VALIDATION`` code its sibling checks already use, so a
    mistyped id reads as bad input rather than as a vendor or network failure.
    """

    code = "VALIDATION"


class UnsupportedCurrency(Exception):
    """The fiat code is not one the protocol holds deposits in.

    Carries ``VALIDATION`` for the same reason ``InvalidDepositId`` does: this is
    bad input, not a vendor or network failure, and the model has to be able to
    tell the difference to know that retrying will not help.
    """

    code = "VALIDATION"


class AmbiguousAmount(Exception):
    """The amount is a bare integer, which the vendor reads as base units.

    ``calldata.parse_usdc_amount`` splits on type, not on value: an ``int`` is
    exact six-decimal units, while a ``str``, ``float`` or ``Decimal`` is human
    USDC. The two readings of the same number differ by a factor of a million,
    and nothing downstream says which one was taken.

    Carries ``VALIDATION`` like its siblings, because a named error the model can
    retry against is the whole point.
    """

    code = "VALIDATION"


class ClientNotInstalled(Exception):
    """The vendor client is absent, so say which command installs it.

    ``python_dependencies`` is a declaration seam: Hermes prints the requirement
    at install time and logs a warning at load, then registers all five tools
    anyway. An environment that ran the documented install without the manual
    ``pip install`` therefore reaches a handler, and a bare
    ``ModuleNotFoundError: No module named 'usdctofiat'`` is all the model gets
    back -- from a chat turn that never saw either host message.
    """

    code = "CLIENT_NOT_INSTALLED"

    def __init__(self) -> None:
        super().__init__(
            "The usdctofiat client is not installed in the Python environment "
            "Hermes runs in. Hermes surfaces a plugin's python_dependencies but "
            "never installs them. Run: pip install 'usdctofiat>=0.1.0'"
        )


def _import_client() -> Any:
    """Import ``usdctofiat``, or name the install command instead."""
    try:
        import usdctofiat
    except ModuleNotFoundError as exc:
        # Only an absent client. A missing module *inside* usdctofiat, or a
        # missing dependency of it, is a broken install with a different fix and
        # must keep its own error.
        if exc.name == "usdctofiat":
            raise ClientNotInstalled() from exc
        raise
    return usdctofiat


def _live_indexer(client: Any) -> Any:
    """The plugin's own reader for the deposit indexer. See live_indexer.py."""
    try:
        from . import live_indexer
    except ImportError:  # loose directory / unit tests
        import live_indexer
    return live_indexer.LiveIndexer(client)


def _create_offramp(**kwargs: Any) -> Any:
    client = _import_client()
    # usdctofiat 0.1.0 queries a Ponder-shaped indexer that the live endpoint is
    # not, so its own reader answers usdctofiat_deposits and usdctofiat_watch
    # with a GraphQL validation error. Injecting ours is the client's own seam.
    kwargs.setdefault("indexer", _live_indexer(client))
    return client.create_offramp(**kwargs)


def _cashout(**kwargs: Any) -> Any:
    return _import_client().cashout(**kwargs)


def _normalise_name(name: Any) -> str:
    """Fold an argument name to letters and digits, lowercased."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _reject_keys(payload: dict[str, Any]) -> None:
    """Refuse key material by argument name, however the caller spelled it.

    Refusing is the only signal the conversation gets. An unmatched name is not
    forwarded -- no handler reads one -- but it is dropped in silence, so the
    turn that pasted a key reads as an ordinary success and nobody learns to
    rotate it.
    """
    for name in payload:
        normalised = _normalise_name(name)
        if normalised in _BANNED_KEY_NAMES or any(
            marker in normalised for marker in _BANNED_KEY_MARKERS
        ):
            raise TypeError(
                "usdctofiat-hermes-plugin does not accept a private key. "
                "Inject a host signer callback or call cashout without a signer "
                "to receive unsigned txs."
            )


def _escrow_deposit_id(client: Any, deposit_id: Any) -> int:
    """Resolve either advertised id to the EscrowV2 id the vendor withdraws on.

    A composite for some other escrow is refused rather than stripped:
    ``withdraw_tx`` always encodes against ``ESCROW_V2``, so dropping a foreign
    prefix would silently prepare a withdrawal of whichever EscrowV2 deposit
    happens to share that number.
    """
    text = str(deposit_id).strip()
    if _ESCROW_DEPOSIT_ID.match(text):
        return int(text)
    composite = _COMPOSITE_DEPOSIT_ID.match(text)
    if composite is None:
        raise InvalidDepositId(
            f"deposit_id {deposit_id!r} is not a deposit id. Pass the id "
            "usdctofiat_deposits returned (<escrow>_<EscrowV2 id>), or the "
            "EscrowV2 id on its own."
        )
    escrow, escrow_id = composite.groups()
    if escrow.lower() != str(client.ESCROW_V2).lower():
        raise InvalidDepositId(
            f"deposit {deposit_id} is held by escrow {escrow}, not the EscrowV2 "
            f"this plugin withdraws from ({client.ESCROW_V2}). Refusing rather "
            "than withdrawing the deposit that shares its id."
        )
    return int(escrow_id)


def _as_dict(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return value


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def _error(exc: Exception) -> str:
    payload: dict[str, Any] = {
        "error": str(exc),
        "code": getattr(exc, "code", type(exc).__name__),
    }
    details = getattr(exc, "details", None)
    if details is not None:
        payload["details"] = details
    return _dumps(payload)


def _require_mode(args: dict[str, Any]) -> str:
    mode = args.get("mode")
    if mode is None or str(mode).strip() == "":
        raise TypeError(
            'mode is required. Pass mode="fast" (0% / TOFIAT) or mode="best" (Delegate, 10 bps).'
        )
    key = str(mode).strip().lower()
    if key not in {"fast", "best"}:
        raise TypeError(
            'mode is required. Pass mode="fast" (0% / TOFIAT) or mode="best" (Delegate, 10 bps).'
        )
    return key


def _require_currency(args: dict[str, Any]) -> str:
    """Refuse a fiat code the protocol has no deposits in, and name the ones it has.

    Runs before the client is touched, so an unsupported code costs neither the
    curator round-trip ``prepare`` opens with nor a createDeposit tx encoded
    against a currency hash that means nothing.
    """
    currency = args.get("currency")
    code = str(currency or "").strip().upper()
    if not code:
        raise UnsupportedCurrency(
            "currency is required. Pass a fiat ISO code such as EUR, USD or GBP."
        )
    if code not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrency(
            f"currency {currency!r} is not a fiat currency USDCtoFiat deposits are "
            "denominated in, so a deposit created in it could not be filled. "
            f"Supported: {', '.join(sorted(SUPPORTED_CURRENCIES))}."
        )
    return code


def _require_amount(args: dict[str, Any]) -> Any:
    """Refuse a bare integer amount, which means something else than it reads.

    ``calldata.parse_usdc_amount`` dispatches on the Python type: an ``int`` is
    exact six-decimal base units, everything else is human USDC. A model asked
    to cash out 500 USDC writes ``500`` -- JSON has one number type and Hermes
    dispatches ``handler(args, **kwargs)`` without validating an argument
    against the schema, so the int arrives as an int. Both readings of it are
    wrong, in opposite ways:

    * under 1_000_000 the vendor refuses with ``minimum 1 USDC`` -- a floor the
      caller is a thousand times above -- so the turn dead-ends on an error that
      describes neither the fault nor the fix, and the retry looks identical;
    * at or above it the number is accepted as units, so ``2000000`` prepares a
      2 USDC deposit for a two-million-USDC request and comes back as an
      ordinary ``signed: false`` prepare with nothing in it that says so.

    Naming the ambiguity costs one retry. Silently reading the int as human USDC
    would cost the opposite mistake -- a deposit a million times too large for
    anyone who did mean units -- and this plugin refuses rather than guesses
    whenever a wrong guess is a transaction. ``"500"`` and ``500.0`` are both
    unambiguous and pass through untouched.
    """
    amount = args.get("amount")
    if isinstance(amount, int):  # bool is an int, and is no more an amount
        raise AmbiguousAmount(
            f"amount {amount!r} is an integer, which usdctofiat reads as exact "
            "six-decimal base units rather than USDC. Pass the human USDC "
            f'amount as a string instead: amount="{amount}".'
        )
    return amount


# The indexer stores remainingDeposits / outstandingIntentAmount as uint256
# six-decimal USDC, the same unit ``parse_usdc_amount`` produces. The two read
# tools used to hand those fields back unlabeled, so a live row of ``3863197``
# remainingDeposits reads as 3.8 million USDC rather than 3.863197. The vendor
# prepare envelope already names the unit (``amount_units``); the indexer
# fields do not. Labelling rather than rewriting: the raw fields stay, and
# ``remaining_usdc`` is the human amount a model can report.
_USDC_BASE_UNITS = 1_000_000
_DEPOSIT_AMOUNT_NOTE = (
    "remainingDeposits and outstandingIntentAmount are six-decimal USDC base "
    "units, not USDC. remaining_usdc and outstanding_intent_usdc are the human "
    "amounts. 3863197 remainingDeposits is 3.863197 USDC, not 3.8 million."
)


def _human_usdc(raw: Any) -> str:
    """Turn six-decimal USDC base units into a human USDC string."""
    units = int(str(raw).strip())
    sign = ""
    if units < 0:
        sign = "-"
        units = -units
    whole, frac = divmod(units, _USDC_BASE_UNITS)
    if frac == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{frac:06d}".rstrip("0")


def _label_deposit_row(row: Any) -> Any:
    """Flag indexer amount fields that are base units, and name the USDC figure.

    A row without those fields is left alone -- the mocked suite still uses a
    bare ``{id, status}`` fixture, and inventing a unit on it would be a lie.
    A value that is not an integer is also left alone rather than dropping the
    deposit: a conversion failure must not hide the row the caller asked for.
    """
    if not isinstance(row, dict):
        return row
    remaining = row.get("remainingDeposits")
    outstanding = row.get("outstandingIntentAmount")
    if remaining is None and outstanding is None:
        return row
    labelled = dict(row)
    try:
        if remaining is not None:
            labelled["remaining_usdc"] = _human_usdc(remaining)
        if outstanding is not None:
            labelled["outstanding_intent_usdc"] = _human_usdc(outstanding)
    except (TypeError, ValueError):
        return row
    labelled["amount_unit"] = "usdc_base_units"
    return labelled


def _label_deposit_payload(payload: dict[str, Any], rows_key: str) -> dict[str, Any]:
    """Apply the unit label to every deposit row the read tools return."""
    rows = payload.get(rows_key)
    if not isinstance(rows, list):
        return payload
    labelled_rows = [_label_deposit_row(row) for row in rows]
    payload[rows_key] = labelled_rows
    if any(
        isinstance(row, dict) and row.get("amount_unit") == "usdc_base_units"
        for row in labelled_rows
    ):
        payload["amount_unit"] = "usdc_base_units"
        payload["amount_unit_note"] = _DEPOSIT_AMOUNT_NOTE
    return payload


# ``prepare(mode="best")`` hands back the same two transactions as fast. The
# approve and createDeposit calldata are byte-identical -- ``encode_create_deposit``
# takes ``mode`` and never reads it, and ``prepare`` passes no ``delegate`` -- so
# everything that makes Best Best lives in a third step, ``setRateManager``, that
# it cannot encode: EscrowV2 keys the call on the deposit id, and the deposit does
# not exist until createDeposit has landed. ``steps`` therefore names three
# entries against two txs.
#
# This plugin has no tool that closes that gap and cannot honestly grow one. The
# vendor's ``encode_delegate_hook`` wants the Delegate ``rateManagerId``, and
# nothing in the client, the curator or the indexer hands one back; letting a
# model supply it would put an invented value through ``_bytes32``, which keccaks
# any unrecognised text into a well-formed 32 bytes -- the same silent-wrong-value
# shape ``_require_currency`` exists to refuse.
#
# So the reply says so, beside the ``signed`` flag it already carries. Signing
# both txs and reporting the cash-out done is otherwise a Fast deposit called a
# Best one, at a rate the caller chose to pay 10 bps to have managed.
_RATE_MANAGER_NOT_ATTACHED = (
    "mode=best is not in effect yet. The transactions in this reply create a "
    "deposit identical to mode=fast. Best is EscrowV2.setRateManager on "
    "RateManagerV1 (10 bps), sent against the new deposit id afterwards, and "
    "this plugin does not encode that step: it needs a Delegate rateManagerId "
    "no tool here can obtain. Until it is sent this is a Fast deposit. The "
    "delegate_hook in this reply carries the addresses that step uses; pass "
    "mode=fast instead if a Fast deposit is what you wanted."
)

_BEST_ESTIMATE_FEE_NOT_EFFECTIVE = (
    "manager_fee_bps=10 describes the intended Delegate rate manager, but that "
    "fee is not effective in a cash-out this plugin can prepare. The plugin's "
    "mode=best deposit is identical to mode=fast until EscrowV2.setRateManager "
    "is sent afterwards, and no tool here can encode that step because it "
    "cannot obtain the required Delegate rateManagerId. Treat this as an "
    "unmanaged Fast estimate, or pass mode=fast."
)


def _label_rate_manager(mode: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Flag a best-mode reply that has not attached the rate manager.

    Only on ``best``: fast has no rate manager to attach, and a
    ``rate_manager_attached: false`` on it would read as a fault rather than as
    the mode working as documented.

    Both cashout branches get it. An injected host signer submits those same two
    txs and nothing more, so it wins the deposit id the third step needs and
    still leaves the rate manager unattached.
    """
    if mode != "best":
        return payload
    payload["rate_manager_attached"] = False
    payload["rate_manager_note"] = _RATE_MANAGER_NOT_ATTACHED
    return payload


def _label_estimate_manager_fee(mode: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Say when the vendor's nominal Best fee cannot become effective.

    ``estimate`` reports ``manager_fee_bps=10`` for Best without inspecting the
    transaction path. The path this plugin can prepare never attaches that rate
    manager, so leaving the nominal fee unqualified makes the quote promise a
    managed cash-out the sibling cash-out handler explicitly says it cannot
    produce.

    Fast remains the ordinary vendor payload: its zero fee is effective and no
    missing rate manager is a fault.
    """
    if mode != "best":
        return payload
    payload["manager_fee_effective"] = False
    payload["rate_manager_note"] = _BEST_ESTIMATE_FEE_NOT_EFFECTIVE
    return payload


def _host_signer(kwargs: dict[str, Any]) -> Callable[..., Any] | None:
    """A host may pass a signer callback. Never a key string."""
    signer = kwargs.get("signer")
    if signer is None:
        return None
    if callable(signer):
        return signer
    raise TypeError(
        "usdctofiat-hermes-plugin does not accept a private key. "
        "signer must be a host callback, not a string."
    )


def usdctofiat_cashout(args: dict, **kwargs) -> str:
    """Wrap usdctofiat.cashout. mode required. No keys.

    Without a host signer, returns unsigned prepare txs.
    With an injected signer callback, submits via usdctofiat.cashout.
    """
    try:
        _reject_keys(args)
        _reject_keys(kwargs)
        mode = _require_mode(args)
        platform = args.get("platform")
        payee = args.get("payee")
        if args.get("amount") in (None, "") or not args.get("currency") or not platform or not payee:
            return _dumps({"error": "Need amount, currency, platform, and payee", "code": "VALIDATION"})
        amount = _require_amount(args)
        currency = _require_currency(args)
        signer = _host_signer(kwargs)
        if signer is None:
            prepared = _create_offramp().prepare(
                mode=mode,
                amount=amount,
                currency=currency,
                platform=platform,
                payee=payee,
            )
            return _dumps(
                _label_rate_manager(mode, {"prepared": _as_dict(prepared), "signed": False})
            )
        result = _cashout(
            mode=mode,
            amount=amount,
            currency=currency,
            platform=platform,
            payee=payee,
            signer=signer,
        )
        return _dumps(_label_rate_manager(mode, {"result": _as_dict(result), "signed": True}))
    except Exception as exc:
        return _error(exc)


def usdctofiat_estimate(args: dict, **kwargs) -> str:
    """Estimate a cash-out. mode required. Not a locked quote."""
    try:
        _reject_keys(args)
        _reject_keys(kwargs)
        mode = _require_mode(args)
        if args.get("amount") in (None, "") or not args.get("currency"):
            return _dumps({"error": "Need amount and currency", "code": "VALIDATION"})
        amount = _require_amount(args)
        currency = _require_currency(args)
        estimate = _create_offramp().estimate(mode=mode, amount=amount, currency=currency)
        return _dumps(_label_estimate_manager_fee(mode, _as_dict(estimate)))
    except Exception as exc:
        return _error(exc)


def usdctofiat_watch(args: dict, **kwargs) -> str:
    """Watch a deposit by id (indexer snapshot)."""
    try:
        _reject_keys(args)
        _reject_keys(kwargs)
        deposit_id = args.get("deposit_id")
        if not deposit_id:
            return _dumps({"error": "Need deposit_id", "code": "VALIDATION"})
        rows = list(_create_offramp().watch(deposit_id))
        return _dumps(
            _label_deposit_payload(
                {"deposit_id": deposit_id, "snapshots": rows}, "snapshots"
            )
        )
    except Exception as exc:
        return _error(exc)


def usdctofiat_withdraw(args: dict, **kwargs) -> str:
    """Withdraw / close a deposit. Unsigned unless a host signer is injected.

    Takes either id the read tools speak: the composite ``<escrow>_<EscrowV2
    id>`` that ``usdctofiat_deposits`` hands back, or the EscrowV2 id alone.

    Both branches carry the ``signed`` flag ``usdctofiat_cashout`` already uses.
    Unwrapped, the branch this plugin takes by default answered with a bare
    ``{to, data, value, chainId}``: a transaction nobody has broadcast, with
    nothing in it that says so. That reads as a completed withdrawal, so the
    model reports the deposit closed while the tx is still sitting unsigned.
    """
    try:
        _reject_keys(args)
        _reject_keys(kwargs)
        deposit_id = args.get("deposit_id")
        if not deposit_id:
            return _dumps({"error": "Need deposit_id", "code": "VALIDATION"})
        # Before the id is resolved: a key passed as the signer has to be
        # refused on its own terms, not shadowed by a typo in deposit_id.
        signer = _host_signer(kwargs)
        escrow_id = _escrow_deposit_id(_import_client(), deposit_id)
        result = _create_offramp().withdraw(escrow_id, signer=signer)
        # The signer this handler passed is what decides the shape coming back:
        # an UnsignedTx without one, a CashoutResult with one. Reading our own
        # argument beats sniffing the result's keys.
        if signer is None:
            return _dumps({"prepared": _as_dict(result), "signed": False})
        return _dumps({"result": _as_dict(result), "signed": True})
    except Exception as exc:
        return _error(exc)


def usdctofiat_deposits(args: dict, **kwargs) -> str:
    """List deposits for a 0x owner on Base."""
    try:
        _reject_keys(args)
        _reject_keys(kwargs)
        owner = args.get("owner")
        if not owner:
            return _dumps({"error": "Need owner", "code": "VALIDATION"})
        return _dumps(
            _label_deposit_payload(
                {"owner": owner, "deposits": _create_offramp().deposits(owner)},
                "deposits",
            )
        )
    except Exception as exc:
        return _error(exc)
