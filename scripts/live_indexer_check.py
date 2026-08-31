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

from usdctofiat.constants import INDEXER_URL  # noqa: E402

SEED_QUERY = """
query NewestDeposit {
  Deposit(limit: 1, order_by: {blockNumber: desc}) {
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
    """Newest deposit on the indexer, fetched without the code under test."""
    response = httpx.post(INDEXER_URL, json={"query": SEED_QUERY}, timeout=30)
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise SystemExit(f"seed query failed: {json.dumps(body['errors'])[:300]}")
    rows = body["data"]["Deposit"]
    if not rows:
        raise SystemExit("indexer holds no deposits: cannot seed the check")
    return rows[0]


def main() -> int:
    row = seed()
    owner, composite, numeric = row["depositor"], row["id"], str(row["depositId"])
    print(f"seeded from the newest deposit (id ends _{numeric})")

    listed = json.loads(tools.usdctofiat_deposits({"owner": owner}))
    check("usdctofiat_deposits returns deposits", bool(listed.get("deposits")), listed.get("error", ""))

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
