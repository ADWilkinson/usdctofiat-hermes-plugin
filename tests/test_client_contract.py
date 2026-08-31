"""Guards the vendor call surface the plugin actually depends on.

``tools.py`` reaches ``usdctofiat`` only through the lazy ``_create_offramp``
and ``_cashout`` wrappers, and ``tests/test_plugin.py`` patches both. The real
client is therefore never imported by the mocked suite, and the CI wheel smoke
installs ``--no-deps``. A vendor rename or a changed keyword would break all
five tools at runtime while every other test stayed green -- the same shape as
the two failures this repo already shipped (a package that would not build, and
a documented install that exited 1).

These tests bind the plugin's exact call shapes against the installed client, so
vendor drift is loud rather than silent. ``usdctofiat`` is a hard dependency in
pyproject.toml, so a missing client is a real failure here, not a skip.
"""

from __future__ import annotations

import inspect

import pytest

import usdctofiat

import tools


def bind(func, *args, **kwargs):
    """Prove the vendor accepts a call shape without pinning its full signature.

    Binding rather than comparing signatures keeps added optional vendor
    parameters green; only removing or renaming something the plugin passes
    fails.
    """
    inspect.signature(func).bind(*args, **kwargs)


def test_module_entry_points_exist():
    """The two names the lazy wrappers import."""
    assert callable(usdctofiat.create_offramp)
    assert callable(usdctofiat.cashout)


def test_lazy_wrappers_resolve_the_vendor_functions(monkeypatch):
    """Both wrappers import from ``usdctofiat`` at call time and forward through.

    Substituting the module attributes proves the linkage without a live
    transaction, and without asserting on wrapper source text.
    """
    sentinel = object()
    monkeypatch.setattr(usdctofiat, "create_offramp", lambda **kwargs: sentinel)
    monkeypatch.setattr(usdctofiat, "cashout", lambda **kwargs: sentinel)

    assert tools._create_offramp() is sentinel
    assert tools._cashout() is sentinel


def test_create_offramp_needs_no_arguments_or_credentials():
    """Every handler calls ``_create_offramp()`` bare.

    A client that grew a required RPC URL or API key at construction would break
    all five tools and the plugin's no-keys promise at the same time.
    """
    offramp = tools._create_offramp()
    assert isinstance(offramp, usdctofiat.Offramp)


def test_cashout_accepts_the_signed_call_shape():
    """``usdctofiat_cashout`` with an injected host signer."""
    bind(
        usdctofiat.cashout,
        mode="fast",
        amount="100",
        currency="EUR",
        platform="revolut",
        payee="alice",
        signer=lambda tx: tx,
    )


def test_offramp_accepts_every_handler_call_shape():
    offramp = usdctofiat.Offramp

    # usdctofiat_cashout, unsigned branch
    bind(
        offramp.prepare,
        offramp,
        mode="fast",
        amount="100",
        currency="EUR",
        platform="revolut",
        payee="alice",
    )
    # usdctofiat_estimate
    bind(offramp.estimate, offramp, mode="fast", amount="100", currency="EUR")
    # usdctofiat_watch
    bind(offramp.watch, offramp, "42")
    # usdctofiat_withdraw, on the EscrowV2 id tools._escrow_deposit_id resolved
    bind(offramp.withdraw, offramp, 42, signer=None)
    # usdctofiat_deposits
    bind(offramp.deposits, offramp, "0x1111111111111111111111111111111111111111")


def test_withdraw_returns_unsigned_without_a_signer_and_a_result_with_one():
    """``usdctofiat_withdraw`` labels its reply from the signer it passed in.

    That flag is only honest while the vendor keeps this correspondence, and an
    inverted one would tell the model an unbroadcast transaction was sent. Both
    calls are local calldata encoding against a stub signer -- no network,
    nothing submitted.
    """
    offramp = tools._create_offramp()

    unsigned = offramp.withdraw("42", signer=None)
    assert isinstance(unsigned, usdctofiat.UnsignedTx)

    signed = offramp.withdraw("42", signer=lambda tx: {"hash": "0x" + "cd" * 32})
    assert isinstance(signed, usdctofiat.CashoutResult)


def test_the_vendor_withdraws_on_the_escrow_id_alone():
    """Why ``tools._escrow_deposit_id`` has to exist.

    ``Offramp.withdraw`` is ``withdraw_tx(int(deposit_id))``, so it takes the
    EscrowV2 id and nothing else -- while the composite ``<escrow>_<EscrowV2
    id>`` is the only deposit id this plugin's own read tools ever show a
    caller. Local calldata encoding against no signer: nothing is submitted.

    If a vendor release ever accepts the composite too, this fails, and the
    normalisation in ``tools`` can go with it.
    """
    offramp = tools._create_offramp()

    assert isinstance(offramp.withdraw(4388, signer=None), usdctofiat.UnsignedTx)
    with pytest.raises(ValueError):
        offramp.withdraw(f"{usdctofiat.ESCROW_V2}_4388", signer=None)


def test_result_types_still_expose_as_dict():
    """``tools._as_dict`` degrades silently when ``as_dict`` disappears.

    It returns the object untouched, which ``_dumps`` then renders through
    ``default=str`` as a repr string -- a valid JSON response carrying unusable
    output. Assert the attribute instead of waiting to see that in a tool reply.
    """
    for name in ("PreparedCashout", "Estimate", "CashoutResult", "UnsignedTx"):
        result_type = getattr(usdctofiat, name)
        assert hasattr(result_type, "as_dict"), f"usdctofiat.{name} lost as_dict"


def test_the_indexer_seam_this_plugin_injects_on_still_exists():
    """``live_indexer`` replaces the client's deposit reader on a public argument.

    ``Offramp`` reads deposits only through ``self.indexer``, so a constructor
    that stopped accepting the argument, or methods that stopped going through
    the attribute, would silently put the vendor's broken queries back in front
    of usdctofiat_deposits and usdctofiat_watch.
    """
    sentinel = object()
    offramp = usdctofiat.Offramp(indexer=sentinel)
    assert offramp.indexer is sentinel
    bind(usdctofiat.create_offramp, indexer=sentinel)


def test_the_indexer_internals_live_indexer_borrows_still_exist():
    """It borrows the vendor's transport rather than opening a second one.

    Only the two queries are this plugin's; the httpx client, the timeout and
    the error mapping stay the client's, reached through ``Indexer._graphql``.
    ``ESCROW_V2`` is how a bare EscrowV2 id becomes the composite the indexer
    keys on.
    """
    assert callable(usdctofiat.indexer.Indexer._graphql)
    bind(usdctofiat.indexer.Indexer._graphql, usdctofiat.indexer.Indexer(), "query", {})
    assert issubclass(usdctofiat.errors.IndexerError, usdctofiat.UsdctoFiatError)
    assert usdctofiat.errors.IndexerError("x").code == "INDEXER"
    assert str(usdctofiat.ESCROW_V2).startswith("0x")


def test_vendor_errors_reach_the_json_error_path():
    """Handlers catch ``Exception``; vendor errors must stay inside that."""
    assert issubclass(usdctofiat.UsdctoFiatError, Exception)
    for name in ("ValidationError", "ModeRequired", "SignerRequired"):
        assert issubclass(getattr(usdctofiat, name), usdctofiat.UsdctoFiatError)


def test_the_vendor_reads_an_integer_amount_as_base_units():
    """Why ``tools._require_amount`` has to exist.

    ``parse_usdc_amount`` splits on type, not value, so the same number means two
    things a million apart and nothing downstream records which was taken. Both
    branches are local arithmetic -- no network, nothing submitted.

    If a vendor release ever reads an int as human USDC, or refuses one, this
    fails and the guard in ``tools`` can go with it.
    """
    from usdctofiat.calldata import parse_usdc_amount

    # A string is human USDC.
    assert parse_usdc_amount("500") == 500_000_000

    # The identical number as an int is base units -- 500 millionths of a USDC,
    # which then trips a floor the caller is a thousand times above.
    with pytest.raises(usdctofiat.ValidationError, match="minimum 1 USDC"):
        parse_usdc_amount(500)

    # Above the floor there is no error at all: 2_000_000 USDC becomes 2 USDC.
    assert parse_usdc_amount(2_000_000) == 2_000_000
    assert parse_usdc_amount("2000000") == 2_000_000 * 10**6


def test_the_amount_shapes_the_guard_lets_through_are_still_human_usdc():
    """The guard only refuses ints, so every other shape must mean human USDC."""
    from usdctofiat.calldata import parse_usdc_amount

    assert parse_usdc_amount(500.0) == 500_000_000
    assert parse_usdc_amount("1.5") == 1_500_000
