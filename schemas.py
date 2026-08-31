"""Tool schemas — what the Hermes LLM sees."""

try:
    from .tools import SUPPORTED_CURRENCIES
except ImportError:  # loose directory / unit tests
    from tools import SUPPORTED_CURRENCIES

# The enum keeps the model from inventing "euros" in the first place; the handler
# guard that owns this set refuses it anyway, because a schema is advice.
_CURRENCIES = sorted(SUPPORTED_CURRENCIES)

CASHOUT = {
    "name": "usdctofiat_cashout",
    "description": (
        "Cash out Base USDC to fiat via USDCtoFiat by Galleon Labs. "
        "Wraps usdctofiat.cashout. mode is required: fast (0% spread / 0 bps, earns TOFIAT) "
        "or best (Delegate rate manager, 10 bps). There is no default mode. "
        "This tool never accepts a wallet private key. It returns unsigned "
        "{to, data, value, chainId} transactions for a host signer, or a signed "
        "result only when the host has already injected a signer callback. "
        "Not a Peer Cash product. Not Peerlytics. Docs: https://usdctofiat.xyz/developers"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["fast", "best"],
                "description": "Required. fast = 0% / TOFIAT. best = Delegate, 10 bps. No default.",
            },
            "amount": {
                "type": "string",
                "description": (
                    'Human USDC amount, as a string: "500" is 500 USDC. A bare '
                    "integer is read as six-decimal base units, not USDC, so it "
                    "is refused rather than guessed at."
                ),
            },
            "currency": {
                "type": "string",
                "enum": _CURRENCIES,
                "description": "Fiat ISO code the deposit is denominated in, e.g. EUR, USD, GBP.",
            },
            "platform": {
                "type": "string",
                "description": "Payment rail, e.g. revolut, venmo, monzo, paypal, wise.",
            },
            "payee": {
                "type": "string",
                "description": "Handle on that platform (not an email for PayPal — use the paypal.me username).",
            },
        },
        "required": ["mode", "amount", "currency", "platform", "payee"],
    },
}

ESTIMATE = {
    "name": "usdctofiat_estimate",
    "description": (
        "Estimate a USDCtoFiat cash-out. Not a locked quote. "
        "mode is required: fast (0 bps seller spread) or best (10 bps manager fee). "
        "No API key. No private key."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["fast", "best"],
                "description": "Required. fast or best. No default.",
            },
            "amount": {
                "type": "string",
                "description": 'Human USDC amount, as a string: "500" is 500 USDC.',
            },
            "currency": {
                "type": "string",
                "enum": _CURRENCIES,
                "description": "Fiat ISO code the deposit is denominated in, e.g. EUR, USD, GBP.",
            },
        },
        "required": ["mode", "amount", "currency"],
    },
}

WATCH = {
    "name": "usdctofiat_watch",
    "description": "Watch a USDCtoFiat deposit by id (public indexer snapshot). No keys.",
    "parameters": {
        "type": "object",
        "properties": {
            "deposit_id": {
                "type": "string",
                "description": "Fast composite resume key or Best numeric EscrowV2 id.",
            },
        },
        "required": ["deposit_id"],
    },
}

WITHDRAW = {
    "name": "usdctofiat_withdraw",
    "description": (
        "Withdraw or close a USDCtoFiat deposit. The reply always carries a "
        "signed flag. Without a host signer -- the default, since this plugin "
        'never takes a key -- it returns {"prepared": {to, data, value, '
        'chainId}, "signed": false}: an unsigned transaction that has NOT been '
        "broadcast and still has to be signed in the host wallet, so the "
        "deposit is not closed yet. Only signed: true means the withdrawal was "
        "submitted. Never pass a private key."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "deposit_id": {
                "type": "string",
                "description": (
                    "The id usdctofiat_deposits returned (<escrow>_<EscrowV2 id>), "
                    "or the EscrowV2 id on its own."
                ),
            },
        },
        "required": ["deposit_id"],
    },
}

DEPOSITS = {
    "name": "usdctofiat_deposits",
    "description": "List USDCtoFiat deposits for a 0x owner on Base. Public indexer. No keys.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {
                "type": "string",
                "description": "0x depositor address on Base.",
            },
        },
        "required": ["owner"],
    },
}
