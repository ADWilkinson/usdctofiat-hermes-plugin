# USDCtoFiat Hermes plugin

Cash out Base USDC to fiat from [Hermes Agent](https://hermes-agent.nousresearch.com/docs/guides/build-a-hermes-plugin) via **USDCtoFiat by Galleon Labs**.

Built on the public Peer/ZKP2P protocol. **Not a Peer Cash product. Not Peerlytics.**

This is a standalone plugin repo. It is not part of `NousResearch/hermes-agent`.

`mode` is required on every priced or mutating call. There is no default.

- **fast**: 0% spread / 0 bps. Earns `TOFIAT`.
- **best**: Delegate rate manager, 10 bps.

The plugin never accepts a wallet private key. It wraps [`usdctofiat.cashout`](https://pypi.org/project/usdctofiat/) (`usdctofiat>=0.1.0`). Without a host signer callback it returns unsigned `{to, data, value, chainId}` transactions for you to sign outside Hermes.

Developer docs: https://usdctofiat.xyz/developers

## Install

```bash
hermes plugins install ADWilkinson/usdctofiat-hermes-plugin
hermes plugins enable usdctofiat
```

Hermes surfaces `python_dependencies` (`usdctofiat>=0.1.0`) but does not auto-install them. Install the client into the same environment Hermes uses:

```bash
pip install "usdctofiat>=0.1.0"
```

No API key. No `requires_env`. No private-key prompt.

## Tools

| Tool | What it does |
| --- | --- |
| `usdctofiat_cashout` | Wrap `usdctofiat.cashout`. `mode` required. Unsigned prepare unless a host signer is injected. |
| `usdctofiat_estimate` | Estimate a cash-out. Not a locked quote. `mode` required. |
| `usdctofiat_watch` | Watch a deposit by id (public indexer snapshot). |
| `usdctofiat_withdraw` | Prepare an unsigned withdraw / close. |
| `usdctofiat_deposits` | List deposits for a `0x` owner on Base. |

## Usage

Ask Hermes to cash out, or call the tool with:

- `mode`: `fast` or `best` (required, no default)
- `amount`: human USDC amount (an int is six-decimal units)
- `currency`: fiat ISO code such as `EUR`, `USD`, or `GBP`
- `platform`: payment rail such as `revolut`, `venmo`, or `monzo`
- `payee`: handle on that platform

`usdctofiat_cashout` returns JSON with `prepared` and `signed: false`. Sign `prepared.txs` in the host wallet. Never paste a private key into Hermes or this plugin.

## Product lock

- Product name is **USDCtoFiat by Galleon Labs**.
- Vendor package is `usdctofiat>=0.1.0`.
- Attribution is locked to `peer-ref-TOFIAT` then `galleonlabs` inside the client. Callers cannot replace it.
- Fast earns TOFIAT at 0% spread. Best uses the Delegate rate manager at 10 bps.

## Layout

Native Hermes directory plugin (`plugin.yaml` + `register(ctx)`):

```text
.
├── plugin.yaml      # manifest (installer-compatible v1 + v2 metadata)
├── __init__.py      # register()
├── schemas.py       # what the LLM sees
├── tools.py         # wraps usdctofiat.cashout
└── tests/           # mocked tool tests + installer/vendor/host contract guards
```

## Tests

```bash
pip install "usdctofiat>=0.1.0" pytest
pytest
```

Tool behaviour is tested against a mocked client. Three guards check the real contracts instead: the installed `usdctofiat` call surface, the Hermes installer's manifest ceiling, and the Hermes host runtime (`register(ctx)`, the handler dispatch shape, and `provides_tools`). The last two read pinned upstream Hermes source over the network — they skip when offline, and CI requires them. Nothing sends a transaction or reads a key.

## Source and support

- Plugin: https://github.com/ADWilkinson/usdctofiat-hermes-plugin
- Python client: https://github.com/ADWilkinson/usdctofiat-python
- Docs: https://usdctofiat.xyz/developers
- PyPI: https://pypi.org/project/usdctofiat/
- Contact: gm@galleonlabs.io
- Author: [ADWilkinson](https://github.com/ADWilkinson)

MIT
