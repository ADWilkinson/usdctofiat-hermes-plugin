"""Tool handlers — wrap usdctofiat.cashout. No keys. mode required."""

from __future__ import annotations

import json
from typing import Any, Callable

_BANNED_KEY_KWARGS = (
    "private_key",
    "privateKey",
    "key",
    "secret",
    "mnemonic",
    "wallet_key",
    "evm_private_key",
    "EVM_PRIVATE_KEY",
)


def _create_offramp(**kwargs: Any) -> Any:
    from usdctofiat import create_offramp

    return create_offramp(**kwargs)


def _cashout(**kwargs: Any) -> Any:
    from usdctofiat import cashout

    return cashout(**kwargs)


def _reject_keys(payload: dict[str, Any]) -> None:
    for banned in _BANNED_KEY_KWARGS:
        if banned in payload:
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
    """Withdraw / close a deposit. Unsigned unless a host signer is injected."""
    try:
        _reject_keys(args)
        _reject_keys(kwargs)
        deposit_id = args.get("deposit_id")
        if not deposit_id:
            return _dumps({"error": "Need deposit_id", "code": "VALIDATION"})
        signer = _host_signer(kwargs)
        result = _create_offramp().withdraw(deposit_id, signer=signer)
        return _dumps(_as_dict(result))
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
