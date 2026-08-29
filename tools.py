"""Tool handlers — wrap usdctofiat.cashout. No keys. mode required."""

from __future__ import annotations

import json
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


def _create_offramp(**kwargs: Any) -> Any:
    return _import_client().create_offramp(**kwargs)


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
        amount = args.get("amount")
        currency = args.get("currency")
        platform = args.get("platform")
        payee = args.get("payee")
        if amount in (None, "") or not currency or not platform or not payee:
            return _dumps({"error": "Need amount, currency, platform, and payee", "code": "VALIDATION"})
        signer = _host_signer(kwargs)
        if signer is None:
            prepared = _create_offramp().prepare(
                mode=mode,
                amount=amount,
                currency=currency,
                platform=platform,
                payee=payee,
            )
            return _dumps({"prepared": _as_dict(prepared), "signed": False})
        result = _cashout(
            mode=mode,
            amount=amount,
            currency=currency,
            platform=platform,
            payee=payee,
            signer=signer,
        )
        return _dumps({"result": _as_dict(result), "signed": True})
    except Exception as exc:
        return _error(exc)


def usdctofiat_estimate(args: dict, **kwargs) -> str:
    """Estimate a cash-out. mode required. Not a locked quote."""
    try:
        _reject_keys(args)
        _reject_keys(kwargs)
        mode = _require_mode(args)
        amount = args.get("amount")
        currency = args.get("currency")
        if amount in (None, "") or not currency:
            return _dumps({"error": "Need amount and currency", "code": "VALIDATION"})
        estimate = _create_offramp().estimate(mode=mode, amount=amount, currency=currency)
        return _dumps(_as_dict(estimate))
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
        return _dumps({"deposit_id": deposit_id, "snapshots": rows})
    except Exception as exc:
        return _error(exc)


def usdctofiat_withdraw(args: dict, **kwargs) -> str:
    """Withdraw / close a deposit. Unsigned unless a host signer is injected.

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
        signer = _host_signer(kwargs)
        result = _create_offramp().withdraw(deposit_id, signer=signer)
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
        return _dumps({"owner": owner, "deposits": _create_offramp().deposits(owner)})
    except Exception as exc:
        return _error(exc)
