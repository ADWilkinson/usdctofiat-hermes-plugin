"""The two read tools, against the shape the live indexer actually answers with.

No network: ``Indexer._graphql`` is the vendor's transport and is patched here,
so what is under test is the query this plugin sends and the payload key it
reads back. The real client is imported, so the error types and the escrow
address are the ones a Hermes call would raise and build ids from, not stand-ins.

``.github/workflows/live-indexer.yml`` is the other half. This file proves the
plugin reads a Hasura answer correctly; that workflow proves the endpoint is
still Hasura.
"""

from __future__ import annotations

import json

import pytest
import usdctofiat

import live_indexer
import tools

OWNER = "0xdC341b2284c4C419C3131E4d63dB603C6df17EBD"

ROW = {
    "id": "0x777777779d229cdf3110e9de47943791c26300ef_4408",
    "depositor": OWNER,
    "remainingDeposits": "3863197",
    "outstandingIntentAmount": "0",
    "status": "ACTIVE",
    "acceptingIntents": True,
}


class FakeTransport(list):
    """Every query the plugin sent, and the rows Hasura is pretending to hold."""

    rows = [ROW]

    def __call__(self, query, variables):
        self.append((query, variables))
        return {"Deposit": list(self.rows)}


@pytest.fixture
def calls(monkeypatch):
    """Capture what the plugin asks the indexer, and answer as Hasura does."""
    transport = FakeTransport()
    transport.rows = [ROW]
    monkeypatch.setattr(usdctofiat.indexer.Indexer, "_graphql", transport)
    return transport


@pytest.fixture
def indexer():
    return live_indexer.LiveIndexer(usdctofiat)


def test_deposits_queries_the_root_field_hasura_exposes(calls, indexer):
    """The whole defect in one assertion.

    The vendor asks for ``deposits``; ``query_root`` has ``Deposit``. Selecting
    the wrong one is not an empty result, it is a validation error that reaches
    the conversation instead of a deposit.
    """
    assert indexer.deposits(OWNER) == [ROW]
    query, variables = calls[0]
    assert "Deposit(" in query
    assert "deposits(" not in query
    assert variables == {"depositor": OWNER}


def test_deposits_matches_the_owner_whatever_case_it_arrived_in(calls, indexer):
    """The indexer stores ``depositor`` checksummed.

    An exact-match filter turns the lower-cased address most wallet tooling
    hands over into an empty list, and an empty list is indistinguishable from
    having no deposits.
    """
    assert indexer.deposits(OWNER.lower()) == [ROW]
    query, variables = calls[0]
    assert "_ilike" in query
    assert variables == {"depositor": OWNER.lower()}


@pytest.mark.parametrize(
    "owner",
    ["", "   ", "alice.eth", "0x1234", "0x" + "zz" * 20, "%", "0x%", "0x" + "1" * 39 + "_"],
    ids=["empty", "blank", "ens", "short", "non-hex", "wildcard", "short-wildcard", "underscore"],
)
def test_deposits_refuses_anything_that_is_not_an_address(calls, indexer, owner):
    """``_ilike`` reads ``%`` and ``_`` as wildcards, so the filter has to be checked.

    Unchecked, the last two are a filter the caller got to write: ``0x%`` would
    return somebody else's deposits under the owner they asked about.
    """
    with pytest.raises(usdctofiat.ValidationError):
        indexer.deposits(owner)
    assert list(calls) == []


def test_deposits_strips_an_address_the_model_padded(calls, indexer):
    assert indexer.deposits(f"  {OWNER}\n") == [ROW]
    _query, variables = calls[0]
    assert variables == {"depositor": OWNER}


def test_watch_resolves_a_composite_id(calls, indexer):
    assert list(indexer.watch(ROW["id"])) == [ROW]
    _query, variables = calls[0]
    assert variables == {"id": ROW["id"]}


def test_watch_resolves_a_bare_escrowv2_id(calls, indexer):
    """``usdctofiat_withdraw`` takes the numeric id; the indexer keys the composite.

    A caller who closed a deposit and then asked to watch it has the number, not
    ``<escrow>_<number>``, and both are advertised on the watch schema.
    """
    assert list(indexer.watch("4408")) == [ROW]
    _query, variables = calls[0]
    assert variables == {"id": f"{usdctofiat.ESCROW_V2.lower()}_4408"}


def test_watch_lower_cases_a_checksummed_composite_id(calls, indexer):
    """The indexer keys deposits in lower case; ``ESCROW_V2`` is checksummed."""
    assert list(indexer.watch(f"{usdctofiat.ESCROW_V2}_4408")) == [ROW]
    _query, variables = calls[0]
    assert variables == {"id": f"{usdctofiat.ESCROW_V2.lower()}_4408"}


def test_a_missing_deposit_is_not_found_rather_than_empty(calls, indexer):
    calls.rows.clear()
    assert indexer.deposit("4408") is None
    with pytest.raises(usdctofiat.errors.IndexerError):
        list(indexer.watch("4408"))


def test_no_deposits_is_an_empty_list_not_an_error(calls, indexer):
    calls.rows.clear()
    assert indexer.deposits(OWNER) == []


def test_the_handlers_go_through_this_indexer(calls, monkeypatch):
    """End to end from the tool the model calls, with only the transport faked.

    ``_create_offramp`` injects the reader on the client's own ``indexer=``
    seam, so a regression that stops injecting it lands back on the vendor's
    broken queries and this fails. The handlers also label the amount unit
    the indexer does not name, so the raw row is a subset of the reply.
    """
    payload = json.loads(tools.usdctofiat_deposits({"owner": OWNER}))
    row = payload["deposits"][0]
    assert {key: row[key] for key in ROW} == ROW
    assert row["remaining_usdc"] == "3.863197"
    assert row["outstanding_intent_usdc"] == "0"
    assert payload["amount_unit"] == "usdc_base_units"

    watched = json.loads(tools.usdctofiat_watch({"deposit_id": "4408"}))
    snapshot = watched["snapshots"][0]
    assert {key: snapshot[key] for key in ROW} == ROW
    assert snapshot["remaining_usdc"] == "3.863197"


def test_a_bad_owner_reaches_the_tool_as_a_validation_error(calls):
    payload = json.loads(tools.usdctofiat_deposits({"owner": "alice.eth"}))
    assert payload["code"] == "VALIDATION"
    assert "0x address" in payload["error"]
    assert list(calls) == []
