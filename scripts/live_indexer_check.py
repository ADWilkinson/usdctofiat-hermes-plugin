#!/usr/bin/env python3
"""Call the two indexer-backed tools against the real indexer and read the answer.

``usdctofiat_deposits`` and ``usdctofiat_watch`` shipped broken -- the client's
queries were written for a Ponder-shaped endpoint and the live one is Hasura --
and every offline test stayed green through it, because the mocked suite patches
the client and ``tests/test_client_contract.py`` binds call shapes rather than
answers. Nothing in this repository had ever asked the indexer a question.

So this does. It seeds itself from the newest deposit the indexer holds rather
than pinning an address, then drives the tool handlers exactly as Hermes would
and fails if either comes back without a deposit. It then hands that same id to
``usdctofiat_withdraw``, because the composite key the indexer hands back is the
only deposit id a caller ever sees, and the vendor withdraws on the EscrowV2 id
alone. No key, and nothing is signed or broadcast: the withdraw branch exercised
here is local calldata encoding with no signer. Only shapes and counts are
printed -- the addresses are public on-chain data, but a CI log is not where
they belong.

It also re-derives ``tools.SUPPORTED_CURRENCIES``. That set is a copy of live
state -- the fiat codes EscrowV2 deposits are actually denominated in -- and
``usdctofiat_cashout`` refuses anything outside it, because the vendor hashes an
unrecognised code into a deposit no taker can fill. A stale copy is the same
defect facing the other way, so the copy is checked against the indexer here
rather than trusted.

Listed rows must be EscrowV2. The indexer tracks every Base escrow, so an
owner-only filter mixed in deposits ``usdctofiat_withdraw`` cannot close.

Weekly and out of the merge path, for the same reason ``hermes-pin.yml`` is:
this reads a service nobody here operates, and an unrelated outage should not
turn a required check red.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools  # noqa: E402

from usdctofiat.calldata import currency_hash  # noqa: E402
from usdctofiat.constants import ESCROW_V2, INDEXER_URL  # noqa: E402

CURRENCIES_QUERY = """
query LiveCurrencies {
  DepositCurrencyLiquidity(distinct_on: currencyCode) {
    currencyCode
  }
}
"""

SEED_QUERY = """
query NewestDeposit($escrowAddress: String!) {
  Deposit(
    where: {escrowAddress: {_eq: $escrowAddress}}
    limit: 1
    order_by: {blockNumber: desc}
  ) {
    id
    depositId
    depositor
  }
}
"""

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    """``detail`` explains a failure; a passing check is one line."""
    print(f"ok   {label}" if ok else f"FAIL {label}{f' -- {detail}' if detail else ''}")
    if not ok:
        failures.append(label)


def seed() -> dict[str, str]:
    """Newest EscrowV2 deposit on the indexer, fetched without the code under test.

    The indexer holds every Base escrow it has tracked. Seeding from the global
    newest row would pick a foreign-escrow deposit this plugin cannot watch or
    withdraw, and the rest of the check would fail for the wrong reason.
    """
    response = httpx.post(
        INDEXER_URL,
        json={
            "query": SEED_QUERY,
            "variables": {"escrowAddress": ESCROW_V2.lower()},
        },
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise SystemExit(f"seed query failed: {json.dumps(body['errors'])[:300]}")
    rows = body["data"]["Deposit"]
    if not rows:
        raise SystemExit("indexer holds no EscrowV2 deposits: cannot seed the check")
    return rows[0]


def live_currencies() -> set[str]:
    """The currency hashes EscrowV2 deposits are actually denominated in.

    Hashed rather than named on the indexer, so it is read back through the
    vendor's own ``currency_hash`` -- the same function that encodes the code
    into a createDeposit tx. A code that round-trips here is a code the plugin
    would build a fillable deposit for.
    """
    response = httpx.post(INDEXER_URL, json={"query": CURRENCIES_QUERY}, timeout=30)
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise SystemExit(f"currency query failed: {json.dumps(body['errors'])[:300]}")
    return {row["currencyCode"] for row in body["data"]["DepositCurrencyLiquidity"]}


def check_supported_currencies() -> None:
    """``tools.SUPPORTED_CURRENCIES`` is a copy of live state, so re-derive it.

    ``usdctofiat_cashout`` refuses any code outside that set, because the vendor
    silently keccaks an unknown one into a deposit no taker can fill. A copy that
    drifts is the same defect wearing the other face: a currency the protocol
    added, refused by name to a caller who could have used it.
    """
    live = live_currencies()
    named = {currency_hash(code): code for code in tools.SUPPORTED_CURRENCIES}
    unlisted = sorted(named[h] for h in named.keys() - live)
    unknown = sorted(live - named.keys())
    check(
        "SUPPORTED_CURRENCIES still matches the indexer",
        not unlisted and not unknown,
        f"listed but no longer on any deposit: {unlisted or 'none'}; "
        f"on {len(unknown)} deposit currenc(ies) the plugin would refuse -- "
        "re-derive the set in tools.py",
    )


def main() -> int:
    row = seed()
    owner, composite, numeric = row["depositor"], row["id"], str(row["depositId"])
    print(f"seeded from the newest deposit (id ends _{numeric})")

    listed = json.loads(tools.usdctofiat_deposits({"owner": owner}))
    check("usdctofiat_deposits returns deposits", bool(listed.get("deposits")), listed.get("error", ""))
    listed_ids = [str(row.get("id") or "") for row in listed.get("deposits") or []]
    check(
        "usdctofiat_deposits lists only EscrowV2 deposits",
        bool(listed_ids) and all(deposit_id.lower().startswith(f"{ESCROW_V2.lower()}_") for deposit_id in listed_ids),
        "an owner-only filter lists deposits this plugin cannot withdraw",
    )

    lowered = json.loads(tools.usdctofiat_deposits({"owner": owner.lower()}))
    check(
        "usdctofiat_deposits ignores owner casing",
        bool(lowered.get("deposits")) and lowered["deposits"] == listed.get("deposits"),
        "a lower-cased address must not read as having no deposits",
    )

    for label, deposit_id in (("composite id", composite), ("bare EscrowV2 id", numeric)):
        watched = json.loads(tools.usdctofiat_watch({"deposit_id": deposit_id}))
        check(f"usdctofiat_watch resolves a {label}", bool(watched.get("snapshots")), watched.get("error", ""))

    # The read -> withdraw handoff, on a real id rather than a fixture one.
    # Unsigned: no signer is passed, so this only encodes calldata.
    prepared = json.loads(tools.usdctofiat_withdraw({"deposit_id": composite}))
    check(
        "usdctofiat_withdraw accepts the id usdctofiat_deposits returned",
        prepared.get("signed") is False and bool(prepared.get("prepared", {}).get("data")),
        prepared.get("error", ""),
    )

    check_supported_currencies()

    missing = json.loads(tools.usdctofiat_watch({"deposit_id": "0" * 40 + "_0"}))
    check(
        "usdctofiat_watch says not found rather than erroring",
        missing.get("code") == "INDEXER" and "not found" in missing.get("error", ""),
        json.dumps(missing)[:200],
    )

    if failures:
        print(f"\n{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("\nlive indexer: every read tool answered with a deposit, and withdraw took its id")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
