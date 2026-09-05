# Changelog

Caller-visible identity. `plugin.yaml` `version` and `pyproject.toml` `version`
must match the newest entry here. A change to what `tools.py` or `schemas.py`
does to a call moves this number. `manifest_version` is the installer's ceiling,
not a product version.

Hermes prints this string from `plugin.yaml` in `plugins list` and
`plugins info`. It does not surface the installed git revision.

## 2.0.0 — 2026-09-05

These landed while still declared `1.0.0`. This number is the first one that
can tell a current install from that original.

- A pasted private key is refused under any argument name (#15)
- A fiat code the protocol holds no deposits in is refused, instead of hashing
  `euros` through into a `createDeposit` no taker can fill (#19)
- `amount: 500` (a bare integer) is refused by name, instead of preparing a
  0.0005 USDC deposit or dead-ending on `minimum 1 USDC` (#20)
- `best` says `rate_manager_attached: false` rather than reporting a Fast
  deposit as a managed cash-out (#21, #22)
- `remainingDeposits` carries `amount_unit` and `remaining_usdc`, so
  `3863197` does not read as 3.8 million (#23)
- `usdctofiat_deposits` lists EscrowV2 only, so deposits this plugin cannot
  withdraw are not hidden behind the 50-row cap (#24)
- A `platform`/`currency` pair EscrowV2 does not settle is refused, instead of
  encoding calldata that reverts `CurrencyNotSupported` after the approve is
  signed (#25)

## 1.0.0 — 2026-08-14

Initial plugin. Cash-out, estimate, watch, withdraw, deposits. `mode`
required. No keys.
