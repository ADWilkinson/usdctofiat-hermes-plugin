"""Read the deposit indexer this plugin's two read tools actually point at.

``usdctofiat`` 0.1.0 ships indexer queries written for a Ponder-shaped endpoint
-- ``deposits(where: {depositor: $depositor}, limit: 50)`` -- but the public
indexer it targets, ``https://indexer.zkp2p.xyz/v1/graphql``, is Hasura. Its
root field is ``Deposit``, and its filters are comparison objects rather than
bare values. Every read therefore comes back as ``field 'deposits' not found in
type: 'query_root'``, so ``usdctofiat_deposits`` and ``usdctofiat_watch`` -- two
of this plugin's five tools -- answer the chat turn with a GraphQL validation
blob and never a deposit. 0.1.0 is the only release, so there is no client to
upgrade to.

The second hole is which rows that Hasura field holds. The indexer tracks every
Base escrow it has ever seen, and ``withdraw`` only ever encodes against
EscrowV2. An owner-only filter therefore lists deposits this plugin cannot
close, and the 50-row cap hides EscrowV2 rows behind them. Both queries now
pin ``escrowAddress`` and ``chainId``; rows that still arrive from another
escrow are dropped rather than shown.

``Offramp(indexer=...)`` is the client's own injection seam, so the fix is the
two queries and nothing else: the transport, the timeout, the httpx client
lifecycle and ``IndexerError`` all stay the vendor's, reached through
``Indexer._graphql``.

Delete this module and the ``indexer=`` argument in ``tools._create_offramp``
once ``usdctofiat`` ships a release whose own queries answer against the live
endpoint and already scope owner reads to EscrowV2.
``tests/test_client_contract.py`` fails the moment either the seam or the
internals this leans on move.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

# The columns the vendor's own queries selected. Keeping the set identical means
# the rows handed back to the tools keep the shape the plugin already returns.
_FIELDS = """
    id
    depositor
    remainingDeposits
    outstandingIntentAmount
    status
    acceptingIntents
"""

# ``_ilike`` without a wildcard is an exact match that ignores case. The indexer
# stores ``depositor`` checksummed, and a caller who lower-cased the address --
# the normalisation most wallet tooling applies -- would otherwise get an empty
# list, which reads as "you have no deposits" rather than "wrong case".
#
# ``escrowAddress`` / ``chainId`` are the other half of the filter: without them
# the 50 rows are a mix of escrows this plugin cannot withdraw, newest-first
# only after the pin so the cap is 50 EscrowV2 deposits rather than 50 of
# whatever the indexer happens to return.
OWNER_DEPOSITS_QUERY = f"""
query OwnerDeposits($depositor: String!, $escrowAddress: String!, $chainId: Int!) {{
  Deposit(
    where: {{
      depositor: {{_ilike: $depositor}}
      escrowAddress: {{_eq: $escrowAddress}}
      chainId: {{_eq: $chainId}}
    }}
    limit: 50
    order_by: {{timestamp: desc}}
  ) {{{_FIELDS}  }}
}}
"""

DEPOSIT_QUERY = f"""
query Deposit($id: String!, $escrowAddress: String!, $chainId: Int!) {{
  Deposit(
    where: {{
      id: {{_eq: $id}}
      escrowAddress: {{_eq: $escrowAddress}}
      chainId: {{_eq: $chainId}}
    }}
    limit: 1
  ) {{{_FIELDS}  }}
}}
"""

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


class LiveIndexer:
    """The vendor ``Indexer``'s transport, pointed at the fields Hasura has.

    Composed rather than subclassed: this module is imported only after
    ``tools._import_client`` has proved the client is installed, and a subclass
    would have to name the base class at import time.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._transport = client.indexer.Indexer()

    def deposits(self, owner: str) -> list[dict[str, Any]]:
        rows = self._rows(
            OWNER_DEPOSITS_QUERY,
            {"depositor": self._address(owner), **self._escrow_scope()},
        )
        return [row for row in rows if self._held_by_this_escrow(row)]

    def deposit(self, deposit_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            DEPOSIT_QUERY,
            {"id": self._deposit_key(deposit_id), **self._escrow_scope()},
        )
        rows = [row for row in rows if self._held_by_this_escrow(row)]
        return rows[0] if rows else None

    def watch(self, deposit_id: str) -> Iterator[dict[str, Any]]:
        """One read, like the vendor's. Hosts poll; nothing long-polls production."""
        row = self.deposit(deposit_id)
        if row is None:
            raise self._client.errors.IndexerError(f"deposit {deposit_id} not found")
        yield row

    def _rows(self, query: str, variables: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self._transport._graphql(query, variables).get("Deposit") or []
        if not isinstance(rows, list):
            raise self._client.errors.IndexerError("unexpected deposit payload", details=rows)
        return rows

    def _address(self, owner: str) -> str:
        """Refuse anything that is not a plain 0x address.

        ``_ilike`` reads ``%`` and ``_`` as wildcards, so an unchecked argument
        is a filter the caller gets to write. An address never contains either.
        """
        text = str(owner).strip()
        if not _ADDRESS.match(text):
            raise self._client.ValidationError(
                f"owner must be a 0x address on Base, got {owner!r}", field="owner"
            )
        return text

    def _deposit_key(self, deposit_id: Any) -> str:
        """Accept both ids the watch schema advertises.

        The indexer keys a deposit by ``<escrow address>_<EscrowV2 id>``, all
        lower case. That composite is what ``usdctofiat_deposits`` hands back, so
        it is what a caller pastes; a bare EscrowV2 id is what
        ``usdctofiat_withdraw`` takes. Both have to resolve. A composite for
        some other escrow is still looked up -- the escrow pin on the query
        makes it a miss rather than stripping the prefix and returning whoever
        shares that EscrowV2 id.
        """
        text = str(deposit_id).strip().lower()
        if text.isdigit():
            return f"{self._escrow_v2()}_{int(text)}"
        return text

    def _escrow_v2(self) -> str:
        return str(self._client.ESCROW_V2).lower()

    def _chain_id(self) -> int:
        chain_id = getattr(self._client, "CHAIN_ID", None)
        if chain_id is None:
            chain_id = self._client.constants.CHAIN_ID
        return int(chain_id)

    def _escrow_scope(self) -> dict[str, Any]:
        return {"escrowAddress": self._escrow_v2(), "chainId": self._chain_id()}

    def _held_by_this_escrow(self, row: dict[str, Any]) -> bool:
        """Drop a foreign-escrow row even if the query filter was ignored.

        The GraphQL pin is what keeps the 50-row cap on EscrowV2. This is the
        other face: a transport that answered unscoped would otherwise hand
        ``usdctofiat_deposits`` deposits ``usdctofiat_withdraw`` must refuse.
        """
        return str(row.get("id") or "").lower().startswith(f"{self._escrow_v2()}_")
