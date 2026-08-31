# USDCtoFiat Hermes plugin

Cash out Base USDC to fiat from [Hermes Agent](https://hermes-agent.nousresearch.com/docs/guides/build-a-hermes-plugin) via **USDCtoFiat by Galleon Labs**.

Built on the public Peer/ZKP2P protocol. **Not a Peer Cash product. Not Peerlytics.**

This is a standalone plugin repo. It is not part of `NousResearch/hermes-agent`.

`mode` is required on every priced or mutating call. There is no default.

- **fast**: 0% spread / 0 bps. Earns `TOFIAT`.
- **best**: Delegate rate manager, 10 bps.

The plugin never accepts a wallet private key. It wraps [`usdctofiat.cashout`](https://pypi.org/project/usdctofiat/) (`usdctofiat>=0.1.0`). Without a host signer callback it returns unsigned `{to, data, value, chainId}` transactions for you to sign outside Hermes.

The deposit reads are the one thing it does not take from the client. `usdctofiat` 0.1.0 queries the indexer as if it were Ponder-shaped, and the public indexer it points at is Hasura, so `usdctofiat_deposits` and `usdctofiat_watch` answered every call with `field 'deposits' not found in type: 'query_root'`. `live_indexer.py` replaces those two queries on the client's own `indexer=` seam and leaves its transport, timeouts and errors alone. It goes when a `usdctofiat` release answers against the live endpoint on its own.

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

Skip that step and the plugin still installs, loads and registers all five tools. The first call then returns `CLIENT_NOT_INSTALLED` and repeats the command above, because Hermes' own install hint and load-time warning go to the console and the log rather than to the conversation.

No API key. No `requires_env`. No private-key prompt.

## Tools

| Tool | What it does |
| --- | --- |
| `usdctofiat_cashout` | Wrap `usdctofiat.cashout`. `mode` required. Unsigned prepare unless a host signer is injected. |
| `usdctofiat_estimate` | Estimate a cash-out. Not a locked quote. `mode` required. |
| `usdctofiat_watch` | Watch a deposit by id (public indexer snapshot). Takes the composite `<escrow>_<id>` or a bare EscrowV2 id. |
| `usdctofiat_withdraw` | Withdraw / close a deposit. Takes the same two ids as `usdctofiat_watch`. Returns `signed: false` with an unsigned tx unless a host signer is injected. |
| `usdctofiat_deposits` | List deposits for a `0x` owner on Base. |

## Usage

Ask Hermes to cash out, or call the tool with:

- `mode`: `fast` or `best` (required, no default)
- `amount`: human USDC amount (an int is six-decimal units)
- `currency`: fiat ISO code such as `EUR`, `USD`, or `GBP`. Only the codes EscrowV2 deposits are actually denominated in are accepted; anything else is refused by name.
- `platform`: payment rail such as `revolut`, `venmo`, or `monzo`
- `payee`: handle on that platform

`currency` is the one argument the client does not refuse for you. It validates `platform` against its catalog and names the supported rails, but hashes an unrecognised currency straight through — so `euros`, `EURO` or `dollars`, the codes a model writes when the user says "cash out to euros", each produced a real `createDeposit` tx denominated in a currency no taker can fill. The plugin refuses a code the protocol holds no deposits in, before the curator call `prepare` opens with. The set is read off the live indexer and re-derived weekly.

`usdctofiat_cashout` returns JSON with `prepared` and `signed: false`. Sign `prepared.txs` in the host wallet. `usdctofiat_withdraw` uses the same envelope: `signed: false` means the withdraw tx in `prepared` is unsigned and unbroadcast, so the deposit stays open until you sign it. Never paste a private key into Hermes or this plugin.

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
├── live_indexer.py  # reads the deposit indexer the client points at
├── tests/           # mocked tool tests + installer/vendor/host contract guards
└── scripts/         # regenerate the pinned snapshot; run the install scan and the indexer check
```

## Tests

```bash
pip install "usdctofiat>=0.1.0" pytest
pytest
```

Tool behaviour is tested against a mocked client. Five guards check the real contracts instead:

- the installed `usdctofiat` call surface, including the `indexer=` seam `live_indexer.py` injects on;
- the Hermes installer's manifest ceiling;
- the security scan the installer runs on the clone before it installs, where a `caution` verdict refuses the documented one-line install rather than merely warning;
- the Hermes host runtime (`register(ctx)`, the handler dispatch shape, and `provides_tools`);
- the deposit reads, against the shape the live indexer answers with.

The Hermes shapes are captured from a pinned revision into `tests/hermes_pinned.py`, so the whole suite runs offline; `scripts/refresh_hermes_pin.py` regenerates that file when the pin moves, and a weekly workflow re-derives it to prove it is still faithful. The scan guard re-implements only the scanner's structural half offline, so the same weekly workflow runs `scripts/hermes_install_scan.py`, which executes the real scanner from the pinned revision over the tracked tree.

The offline suite patches the client, so it can only prove the plugin reads an indexer answer correctly, never that the indexer still answers that way. A second weekly workflow runs `scripts/live_indexer_check.py`, which drives `usdctofiat_deposits` and `usdctofiat_watch` against the real indexer and fails if either stops returning a deposit, and re-derives the accepted currency set so the copy in `tools.py` cannot drift from the protocol in either direction. Neither weekly workflow gates a merge: both read services nobody here operates. Nothing sends a transaction or reads a key.

## Source and support

- Plugin: https://github.com/ADWilkinson/usdctofiat-hermes-plugin
- Python client: https://github.com/ADWilkinson/usdctofiat-python
- Docs: https://usdctofiat.xyz/developers
- PyPI: https://pypi.org/project/usdctofiat/
- Contact: gm@galleonlabs.io
- Author: [ADWilkinson](https://github.com/ADWilkinson)

MIT
