"""Tool schemas — what the Hermes LLM sees."""

try:
    from .tools import PAYMENT_METHOD_CURRENCIES, SUPPORTED_CURRENCIES
except ImportError:  # loose directory / unit tests
    from tools import PAYMENT_METHOD_CURRENCIES, SUPPORTED_CURRENCIES

# The enum keeps the model from inventing "euros" in the first place; the handler
# guard that owns this set refuses it anyway, because a schema is advice.
_CURRENCIES = sorted(SUPPORTED_CURRENCIES)
_PLATFORMS = sorted(PAYMENT_METHOD_CURRENCIES)

CASHOUT = {
    "name": "usdctofiat_cashout",
    "description": (
        "Cash out Base USDC to fiat via USDCtoFiat by Galleon Labs. "
        "Wraps usdctofiat.cashout. mode is required: fast (0% spread / 0 bps, earns TOFIAT) "
        "or best (Delegate rate manager, 10 bps). There is no default mode. "
        "This tool never accepts a wallet private key. It returns unsigned "
        "{to, data, value, chainId} transactions for a host signer, or a signed "
        "result only when the host has already injected a signer callback. "
        "A best reply also carries rate_manager_attached: false -- best prepares "
        "the same deposit as fast and the rate manager is attached by a later "
        "step this tool does not encode, so do not report a best cash-out as "
        "managed. A platform/currency pair EscrowV2 does not settle (venmo/EUR, "
        "monzo/USD) is refused rather than encoded. "
        "Not a Peer Cash product. Not Peerlytics. Docs: https://usdctofiat.xyz/developers"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["fast", "best"],
                "description": (
                    "Required. No default. fast = 0% spread, earns TOFIAT. "
                    "best = Delegate rate manager, 10 bps -- but this tool only "
                    "prepares the deposit, which is identical to fast; the "
                    "setRateManager step that makes it best is not encoded here, "
                    "and the reply says so."
                ),
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
                "enum": _PLATFORMS,
                "description": (
                    "Payment rail. Must settle the chosen currency onchain: "
                    "venmo, cashapp, chime and zelle are USD; monzo is GBP. "
                    "A pair EscrowV2 does not settle is refused rather than encoded."
                ),
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
        "mode is required: fast (0 bps seller spread) or best (nominal 10 bps "
        "manager fee). A best reply carries manager_fee_effective: false because "
        "this plugin cannot attach the rate manager; treat it as an unmanaged "
        "Fast estimate. "
        "No API key. No private key."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["fast", "best"],
                "description": (
                    "Required. fast or best. No default. Best's nominal 10 bps "
                    "manager fee is not effective in a cash-out this plugin can "
                    "prepare, and the reply says so."
                ),
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
    "description": (
        "Watch a USDCtoFiat deposit by id (public indexer snapshot). "
        "remainingDeposits and outstandingIntentAmount are six-decimal USDC "
        "base units, not USDC; remaining_usdc is the human amount. No keys."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "deposit_id": {
                "type": "string",
                "description": (
                    "The id usdctofiat_deposits returned (<escrow>_<EscrowV2 id>), "
                    "or the EscrowV2 id on its own. Other escrows are not found."
                ),
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
    "description": (
        "List this plugin's EscrowV2 deposits for a 0x owner on Base. "
        "Public indexer. Other escrows the indexer tracks are omitted because "
        "usdctofiat_withdraw cannot close them. remainingDeposits and "
        "outstandingIntentAmount are six-decimal USDC base units, not USDC; "
        "remaining_usdc is the human amount. No keys."
    ),
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
