"""Mocked unit tests for the USDCtoFiat Hermes plugin.

No network. No keys. usdctofiat.cashout / create_offramp are patched.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tools import (
    usdctofiat_cashout,
    usdctofiat_deposits,
    usdctofiat_estimate,
    usdctofiat_watch,
    usdctofiat_withdraw,
)


_DELEGATE_HOOK = {
    "step": "setRateManager",
    "to": "0x777777779d229cdF3110e9de47943791c26300Ef",
    "rate_manager": "0xeED7dB23e724aC4590d6BB6f78FDa6dB203535f3",
    "fee_bps": 10,
    "requires": "deposit_id",
    "note": "Best is the same createDeposit as Fast, then EscrowV2.setRateManager ...",
}


def _prepared(mode: str = "fast") -> SimpleNamespace:
    return SimpleNamespace(
        mode=mode,
        as_dict=lambda: {
            "mode": mode,
            "txs": [
                {"to": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "data": "0x095ea7b3", "value": "0x0", "chainId": 8453},
                {"to": "0x777777779d229cdF3110e9de47943791c26300Ef", "data": "0xcreate", "value": "0x0", "chainId": 8453},
            ],
            "steps": ["approve", "createDeposit"] if mode == "fast" else ["approve", "createDeposit", "setRateManager"],
            "payee_details_hash": "0x11" + "ab" * 31,
            "amount_units": "100000000",
            "platform": "revolut",
            "currency": "EUR",
            "attribution": {"referral_code": "TOFIAT", "referrers": ["galleonlabs"]},
            "delegate_hook": None if mode == "fast" else _DELEGATE_HOOK,
        },
    )


def _result(mode: str = "fast") -> SimpleNamespace:
    return SimpleNamespace(
        deposit_id="42",
        tx_hash="0x" + "ab" * 32,
        mode=mode,
        as_dict=lambda: {
            "deposit_id": "42",
            "tx_hash": "0x" + "ab" * 32,
            "mode": mode,
            "tx_hashes": ["0x" + "ab" * 32],
            "delegate_hook": None if mode == "fast" else _DELEGATE_HOOK,
        },
    )


def _estimate(mode: str = "fast") -> SimpleNamespace:
    return SimpleNamespace(
        as_dict=lambda: {
            "mode": mode,
            "amount_units": "100000000",
            "currency": "EUR",
            "rate": "1",
            "receive_amount": "100",
            "spread_bps": 0,
            "manager_fee_bps": 0 if mode == "fast" else 10,
            "kind": "oracle-estimate",
        }
    )


@pytest.fixture
def mock_offramp():
    client = MagicMock()
    client.prepare.return_value = _prepared("fast")
    client.estimate.return_value = _estimate("fast")
    client.deposits.return_value = [{"id": "42", "status": "ACTIVE"}]
    client.watch.return_value = iter([{"id": "42", "status": "ACTIVE"}])
    client.withdraw.return_value = SimpleNamespace(
        as_dict=lambda: {
            "to": "0x777777779d229cdF3110e9de47943791c26300Ef",
            "data": "0xwithdraw",
            "value": "0x0",
            "chainId": 8453,
        }
    )
    return client


@pytest.fixture
def patched(mock_offramp):
    with patch("tools._create_offramp", return_value=mock_offramp) as create, patch(
        "tools._cashout", return_value=_result("fast")
    ) as cashout:
        yield create, cashout, mock_offramp


def test_manifest_keeps_v2_metadata_and_python_dep():
    """Hermes parses the v2 metadata fields regardless of the declared version.

    The declared version itself is owned by tests/test_install_compat.py, which
    checks it against the real installer ceiling.
    """
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "plugin.yaml").read_text()
    assert "name: usdctofiat" in text
    assert "api_version: 1" in text
    assert "python_dependencies:" in text
    assert "usdctofiat>=0.1.0" in text
    assert "requires_env" not in text
    assert "usdctofiat_cashout" in text


def test_readme_has_install_command():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "hermes plugins install ADWilkinson/usdctofiat-hermes-plugin" in text
    assert "mode" in text.lower()
    assert "galleon" in text.lower()
    assert "not a peer cash product" in text.lower()
    assert "NousResearch/hermes-agent" in text


def test_register_wires_cashout_handler():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("usdctofiat_plugin", root / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    register = mod.register

    ctx = MagicMock()
    register(ctx)
    names = [c.kwargs["name"] for c in ctx.register_tool.call_args_list]
    assert names == [
        "usdctofiat_cashout",
        "usdctofiat_estimate",
        "usdctofiat_watch",
        "usdctofiat_withdraw",
        "usdctofiat_deposits",
    ]
    cashout_call = ctx.register_tool.call_args_list[0]
    assert cashout_call.kwargs["handler"] is usdctofiat_cashout
    assert cashout_call.kwargs["toolset"] == "usdctofiat"


def test_cashout_without_signer_returns_unsigned_prepare(patched):
    _create, cashout, offramp = patched
    payload = json.loads(
        usdctofiat_cashout(
            {
                "mode": "fast",
                "amount": "100",
                "currency": "EUR",
                "platform": "revolut",
                "payee": "alice",
            }
        )
    )
    assert payload["signed"] is False
    assert payload["prepared"]["mode"] == "fast"
    assert payload["prepared"]["steps"] == ["approve", "createDeposit"]
    assert payload["prepared"]["attribution"]["referral_code"] == "TOFIAT"
    offramp.prepare.assert_called_once()
    cashout.assert_not_called()


def test_cashout_with_injected_signer_calls_usdctofiat_cashout(patched):
    _create, cashout, offramp = patched
    seen = []

    def signer(tx):
        seen.append(tx)
        return {"hash": "0x" + "cd" * 32, "deposit_id": "42"}

    payload = json.loads(
        usdctofiat_cashout(
            {
                "mode": "fast",
                "amount": "10",
                "currency": "GBP",
                "platform": "monzo",
                "payee": "alice",
            },
            signer=signer,
        )
    )
    assert payload["signed"] is True
    assert payload["result"]["deposit_id"] == "42"
    assert payload["result"]["mode"] == "fast"
    cashout.assert_called_once()
    kwargs = cashout.call_args.kwargs
    assert kwargs["mode"] == "fast"
    assert kwargs["signer"] is signer
    offramp.prepare.assert_not_called()


def test_best_says_the_rate_manager_is_not_attached_yet(patched):
    """A best prepare is a fast deposit until a step this plugin cannot encode.

    ``prepare(mode="best")`` returns the same two txs as fast -- identical
    approve and createDeposit calldata -- and names a third, ``setRateManager``,
    that it cannot build until the deposit id exists. Nothing in this plugin's
    toolset can build it either. Signing the two and reporting the cash-out done
    therefore leaves a Fast deposit described as a Best one.
    """
    _create, _cashout_fn, offramp = patched
    offramp.prepare.return_value = _prepared("best")

    payload = json.loads(
        usdctofiat_cashout(
            {
                "mode": "best",
                "amount": "100",
                "currency": "EUR",
                "platform": "revolut",
                "payee": "alice",
            }
        )
    )

    assert payload["signed"] is False
    assert payload["rate_manager_attached"] is False
    assert "not in effect yet" in payload["rate_manager_note"]
    assert "setRateManager" in payload["rate_manager_note"]
    # The gap the flag is about: three steps named, two txs handed over.
    assert payload["prepared"]["steps"] == ["approve", "createDeposit", "setRateManager"]
    assert len(payload["prepared"]["txs"]) == 2


def test_best_is_flagged_on_the_signed_branch_too(patched):
    """A host signer submits those same two txs and stops there.

    An injected signer wins the deposit id the third step needs, and still never
    sends it, so the reply that reads most like a completed cash-out is exactly
    the one that must carry the flag.
    """
    _create, cashout, offramp = patched
    cashout.return_value = _result("best")

    payload = json.loads(
        usdctofiat_cashout(
            {
                "mode": "best",
                "amount": "100",
                "currency": "EUR",
                "platform": "revolut",
                "payee": "alice",
            },
            signer=lambda tx: {"hash": "0x" + "cd" * 32, "deposit_id": "42"},
        )
    )

    assert payload["signed"] is True
    assert payload["result"]["mode"] == "best"
    assert payload["rate_manager_attached"] is False
    assert payload["result"]["delegate_hook"]["step"] == "setRateManager"


def test_fast_carries_no_rate_manager_flag(patched):
    """Fast has no rate manager to attach, so the flag would read as a fault."""
    payload = json.loads(
        usdctofiat_cashout(
            {
                "mode": "fast",
                "amount": "100",
                "currency": "EUR",
                "platform": "revolut",
                "payee": "alice",
            }
        )
    )
    assert payload["signed"] is False
    assert "rate_manager_attached" not in payload
    assert "rate_manager_note" not in payload


def test_the_cashout_schema_warns_the_model_about_best():
    """The reply flag is the guard; the schema is what stops the wrong report.

    A model that has already called the tool reads ``rate_manager_attached``, but
    the description is what it reads while deciding how to summarise the turn.
    """
    import schemas

    blob = json.dumps(schemas.CASHOUT)
    assert "rate_manager_attached" in blob
    assert "setRateManager" in blob


def test_best_estimate_says_its_manager_fee_is_not_effective(patched):
    """The nominal 10 bps must not read as a fee this plugin can apply."""
    _create, _cashout, offramp = patched
    offramp.estimate.return_value = _estimate("best")

    payload = json.loads(
        usdctofiat_estimate({"mode": "best", "amount": "100", "currency": "EUR"})
    )

    assert payload["manager_fee_bps"] == 10
    assert payload["manager_fee_effective"] is False
    assert "unmanaged Fast estimate" in payload["rate_manager_note"]
    assert "rateManagerId" in payload["rate_manager_note"]


def test_fast_estimate_keeps_the_vendor_shape(patched):
    """Fast has no missing manager, so the Best caveat would read as a fault."""
    payload = json.loads(
        usdctofiat_estimate({"mode": "fast", "amount": "100", "currency": "EUR"})
    )

    assert payload["manager_fee_bps"] == 0
    assert "manager_fee_effective" not in payload
    assert "rate_manager_note" not in payload


def test_the_estimate_schema_warns_the_model_about_the_nominal_best_fee():
    """The schema is what the model reads before it presents the quote."""
    import schemas

    blob = json.dumps(schemas.ESTIMATE)
    assert "manager_fee_effective" in blob
    assert "unmanaged" in blob


def test_cashout_mode_required():
    payload = json.loads(
        usdctofiat_cashout(
            {
                "mode": "",
                "amount": "100",
                "currency": "EUR",
                "platform": "revolut",
                "payee": "alice",
            }
        )
    )
    assert "mode is required" in payload["error"]


def test_cashout_rejects_invalid_mode():
    payload = json.loads(
        usdctofiat_cashout(
            {
                "mode": "slow",
                "amount": "100",
                "currency": "EUR",
                "platform": "revolut",
                "payee": "alice",
            }
        )
    )
    assert "mode is required" in payload["error"]


def test_cashout_rejects_private_key(patched):
    payload = json.loads(
        usdctofiat_cashout(
            {
                "mode": "fast",
                "amount": "100",
                "currency": "EUR",
                "platform": "revolut",
                "payee": "alice",
                "private_key": "0xabc",
            }
        )
    )
    assert "does not accept a private key" in payload["error"]
    _create, cashout, offramp = patched
    cashout.assert_not_called()
    offramp.prepare.assert_not_called()


def test_cashout_rejects_string_signer(patched):
    payload = json.loads(
        usdctofiat_cashout(
            {
                "mode": "fast",
                "amount": "100",
                "currency": "EUR",
                "platform": "revolut",
                "payee": "alice",
            },
            signer="0xabc",
        )
    )
    assert "does not accept a private key" in payload["error"]


class TestKeyNameVariants:
    """One pasted key, spelled the way the caller happened to spell it.

    The refusal is the only place this plugin's no-keys promise is visible from
    a chat turn. An unmatched name never reaches the vendor -- no handler reads
    anything outside the schema -- but it is dropped in silence, so the call
    comes back as an ordinary prepare and the pasted key looks accepted and
    safe. Matching exact strings made that the default for ``PRIVATE_KEY``,
    which is how the env var everyone copies from is actually spelled, and which
    the old list already anticipated one line down as ``EVM_PRIVATE_KEY``.
    """

    SPELLINGS = (
        "private_key",
        "privateKey",
        "PRIVATE_KEY",
        "Private-Key",
        "privatekey",
        "EVM_PRIVATE_KEY",
        "wallet_private_key",
        "mnemonic",
        "MNEMONIC",
        "userMnemonic",
        "seed_phrase",
        "secretKey",
        "keystore",
        "signing_key",
    )

    @staticmethod
    def _args(**extra):
        return {
            "mode": "fast",
            "amount": "100",
            "currency": "EUR",
            "platform": "revolut",
            "payee": "alice",
            **extra,
        }

    @pytest.mark.parametrize("name", SPELLINGS)
    def test_every_spelling_is_refused_before_the_vendor_is_called(self, name, patched):
        _create, cashout, offramp = patched
        payload = json.loads(usdctofiat_cashout(self._args(**{name: "0x" + "ab" * 32})))
        assert "does not accept a private key" in payload["error"]
        cashout.assert_not_called()
        offramp.prepare.assert_not_called()

    @pytest.mark.parametrize("name", SPELLINGS)
    def test_a_host_kwarg_is_refused_too(self, name, patched):
        """``_reject_keys`` guards both sides; kwargs is where a host would pass one."""
        _create, cashout, offramp = patched
        payload = json.loads(
            usdctofiat_cashout(self._args(), **{name: "0x" + "ab" * 32})
        )
        assert "does not accept a private key" in payload["error"]
        cashout.assert_not_called()
        offramp.prepare.assert_not_called()

    @pytest.mark.parametrize(
        "handler,args",
        (
            (usdctofiat_estimate, {"mode": "fast", "amount": "100", "currency": "EUR"}),
            (usdctofiat_watch, {"deposit_id": "42"}),
            (usdctofiat_withdraw, {"deposit_id": "42"}),
            (usdctofiat_deposits, {"owner": "0x1111111111111111111111111111111111111111"}),
        ),
        ids=["estimate", "watch", "withdraw", "deposits"],
    )
    def test_the_other_tools_refuse_it_as_well(self, handler, args, patched):
        payload = json.loads(handler({**args, "PRIVATE_KEY": "0x" + "ab" * 32}))
        assert "does not accept a private key" in payload["error"]

    def test_the_schema_arguments_are_not_caught(self, patched):
        """Substring matching must not refuse the fields the tools are for.

        Every name in schemas.py, plus the host ``signer`` callback, which is the
        supported way to sign and must survive the guard that refuses key strings.
        """
        _create, _cashout, offramp = patched
        payload = json.loads(usdctofiat_cashout(self._args()))
        assert payload["signed"] is False
        offramp.prepare.assert_called_once()

        for handler, args in (
            (usdctofiat_estimate, {"mode": "fast", "amount": "100", "currency": "EUR"}),
            (usdctofiat_watch, {"deposit_id": "42"}),
            (usdctofiat_withdraw, {"deposit_id": "42"}),
            (usdctofiat_deposits, {"owner": "0x1111111111111111111111111111111111111111"}),
        ):
            assert "does not accept a private key" not in handler(args)

        signed = json.loads(
            usdctofiat_cashout(self._args(), signer=lambda tx: {"hash": "0x" + "cd" * 32})
        )
        assert signed["signed"] is True


def test_estimate_watch_withdraw_deposits(patched):
    _create, _cashout, offramp = patched
    estimate = json.loads(usdctofiat_estimate({"mode": "fast", "amount": "100", "currency": "EUR"}))
    assert estimate["spread_bps"] == 0
    assert estimate["mode"] == "fast"

    watched = json.loads(usdctofiat_watch({"deposit_id": "42"}))
    assert watched["snapshots"][0]["status"] == "ACTIVE"

    rows = json.loads(usdctofiat_deposits({"owner": "0x1111111111111111111111111111111111111111"}))
    assert rows["deposits"][0]["id"] == "42"

    withdrawn = json.loads(usdctofiat_withdraw({"deposit_id": "42"}))
    assert withdrawn["prepared"]["to"].lower().endswith("ef")
    assert withdrawn["prepared"]["data"] == "0xwithdraw"


class TestWithdrawSaysWhetherItWasSent:
    """An unsigned withdraw must not read like a completed one.

    Without a host signer -- the default, since the plugin never takes a key --
    the vendor hands back an ``UnsignedTx``, whose ``as_dict`` is a bare
    ``{to, data, value, chainId}``. Returned unwrapped, that is a confident
    success with nothing in it to say the transaction was never broadcast: the
    model reports the deposit closed, the user stops watching it, and the tx is
    still unsigned. ``usdctofiat_cashout`` already answers this with a ``signed``
    flag, so the fix is one envelope across both tools rather than a new idiom.
    """

    def test_the_default_withdraw_is_labelled_unsigned(self, patched):
        _create, _cashout, offramp = patched
        payload = json.loads(usdctofiat_withdraw({"deposit_id": "42"}))

        assert payload["signed"] is False
        assert payload["prepared"]["data"] == "0xwithdraw"
        # The bare tx must not also be the top-level object: that is the shape
        # that reads as a finished withdrawal.
        assert "to" not in payload
        offramp.withdraw.assert_called_once_with(42, signer=None)

    def test_an_injected_signer_is_labelled_signed(self, patched):
        """The signed branch, which nothing exercised before."""
        _create, _cashout, offramp = patched
        offramp.withdraw.return_value = _result("fast")

        def signer(tx):
            return {"hash": "0x" + "cd" * 32}

        payload = json.loads(usdctofiat_withdraw({"deposit_id": "42"}, signer=signer))

        assert payload["signed"] is True
        assert payload["result"]["tx_hash"] == "0x" + "ab" * 32
        assert offramp.withdraw.call_args.kwargs["signer"] is signer

    def test_a_string_signer_is_refused_before_the_vendor_is_called(self, patched):
        """``withdraw`` takes a signer too, so it needs the same refusal."""
        _create, _cashout, offramp = patched
        payload = json.loads(usdctofiat_withdraw({"deposit_id": "42"}, signer="0x" + "ab" * 32))

        assert "does not accept a private key" in payload["error"]
        offramp.withdraw.assert_not_called()

    def test_a_string_signer_outranks_an_unusable_deposit_id(self, patched):
        """A key must be refused on its own terms, not shadowed by a typo.

        Refusing is the only signal the conversation gets that a key was pasted,
        so a bad ``deposit_id`` in the same call must not answer instead.
        """
        _create, _cashout, offramp = patched
        payload = json.loads(usdctofiat_withdraw({"deposit_id": "not an id"}, signer="0x" + "ab" * 32))

        assert "does not accept a private key" in payload["error"]
        offramp.withdraw.assert_not_called()


class TestWithdrawTakesTheIdTheListToolHandedBack:
    """The composite id is the only deposit id a caller ever sees.

    ``usdctofiat_deposits`` returns the indexer's ``<escrow>_<EscrowV2 id>`` key
    and ``usdctofiat_watch`` resolves it, but the vendor withdraws on the
    EscrowV2 id alone -- ``withdraw_tx(int(deposit_id))``. Pasting the listed id
    back therefore answered ``invalid literal for int() with base 10``: a raw
    Python error, naming no id the tool would have taken, on the one tool here
    that moves a deposit.

    ``ESCROW_V2`` is stubbed to an address that is deliberately not the real
    one, so a resolution that passes here is reading the client's constant
    rather than a copy of it.
    """

    ESCROW = "0x" + "ab" * 20
    OTHER_ESCROW = "0x" + "cd" * 20

    @pytest.fixture
    def withdrawable(self, patched):
        """``patched`` stubs the offramp; the id resolver reads the client too."""
        _create, _cashout, offramp = patched
        with patch("tools._import_client", return_value=SimpleNamespace(ESCROW_V2=self.ESCROW)):
            yield offramp

    def test_the_composite_id_resolves_to_the_escrow_id(self, withdrawable):
        payload = json.loads(usdctofiat_withdraw({"deposit_id": f"{self.ESCROW}_4388"}))

        assert payload["signed"] is False
        assert payload["prepared"]["data"] == "0xwithdraw"
        withdrawable.withdraw.assert_called_once_with(4388, signer=None)

    def test_the_composite_id_resolves_whatever_its_casing(self, withdrawable):
        """The indexer keys the composite lower case; a caller may checksum it.

        The escrow is matched on its value, not on the spelling it arrived in.
        """
        json.loads(usdctofiat_withdraw({"deposit_id": f"{self.ESCROW.upper()}_4388"}))

        withdrawable.withdraw.assert_called_once_with(4388, signer=None)

    def test_the_bare_escrow_id_still_works(self, withdrawable):
        json.loads(usdctofiat_withdraw({"deposit_id": " 4388 "}))

        withdrawable.withdraw.assert_called_once_with(4388, signer=None)

    def test_another_escrow_is_refused_rather_than_stripped(self, withdrawable):
        """``withdraw_tx`` always encodes against ``ESCROW_V2``.

        Dropping a foreign prefix would prepare a withdrawal of whichever
        EscrowV2 deposit happens to share that number -- someone else's.
        """
        payload = json.loads(usdctofiat_withdraw({"deposit_id": f"{self.OTHER_ESCROW}_4388"}))

        assert payload["code"] == "VALIDATION"
        assert self.OTHER_ESCROW in payload["error"]
        withdrawable.withdraw.assert_not_called()

    def test_an_unusable_id_names_both_accepted_forms(self, withdrawable):
        payload = json.loads(usdctofiat_withdraw({"deposit_id": "deposit #4388"}))

        assert payload["code"] == "VALIDATION"
        assert "usdctofiat_deposits" in payload["error"]
        assert "EscrowV2 id on its own" in payload["error"]
        # Not the bare int() failure this replaced.
        assert "invalid literal" not in payload["error"]
        withdrawable.withdraw.assert_not_called()


def test_estimate_mode_required():
    payload = json.loads(usdctofiat_estimate({"mode": "slow", "amount": "100", "currency": "EUR"}))
    assert "mode is required" in payload["error"]


def test_handlers_accept_kwargs_and_return_json_string():
    payload = usdctofiat_cashout(
        {"mode": "", "amount": "1", "currency": "USD", "platform": "venmo", "payee": "x"},
        extra_future_field=True,
    )
    assert isinstance(payload, str)
    json.loads(payload)


class TestClientNotInstalled:
    """The first-run state the documented install actually leaves behind.

    Hermes never installs a plugin's ``python_dependencies``: the CLI prints
    them once at install time and ``PluginManager`` logs a warning at load, then
    loads the plugin and registers all five tools regardless. So the likeliest
    first call after `hermes plugins install` is one made without the client
    present, and whatever it returns is the only thing the model -- and through
    it the user -- ever sees about the problem.
    """

    ALL_TOOLS = (
        (usdctofiat_cashout, {"mode": "fast", "amount": "100", "currency": "EUR", "platform": "revolut", "payee": "alice"}),
        (usdctofiat_estimate, {"mode": "fast", "amount": "100", "currency": "EUR"}),
        (usdctofiat_watch, {"deposit_id": "42"}),
        (usdctofiat_withdraw, {"deposit_id": "42"}),
        (usdctofiat_deposits, {"owner": "0x1111111111111111111111111111111111111111"}),
    )

    @staticmethod
    def _absent(monkeypatch):
        """Make ``import usdctofiat`` fail the way an uninstalled client does.

        ``None`` in ``sys.modules`` raises ``ModuleNotFoundError`` with ``name``
        set to the blocked module, so this reproduces the real failure even in
        CI, where the client is installed.
        """
        import sys

        monkeypatch.setitem(sys.modules, "usdctofiat", None)

    @pytest.mark.parametrize(
        "handler,args", ALL_TOOLS, ids=[handler.__name__ for handler, _ in ALL_TOOLS]
    )
    def test_every_tool_names_the_install_command(self, handler, args, monkeypatch):
        self._absent(monkeypatch)
        payload = json.loads(handler(args))
        assert payload["code"] == "CLIENT_NOT_INSTALLED"
        assert "pip install 'usdctofiat>=0.1.0'" in payload["error"]

    def test_the_bare_error_it_replaces_is_not_what_ships(self, monkeypatch):
        """Regression fixture: the reply this repo used to return.

        ``{"error": "No module named 'usdctofiat'", "code": "ModuleNotFoundError"}``
        is a true statement with no remediation in it, and the host messages
        that carry the remediation are a console line and a log entry the chat
        turn never sees.
        """
        self._absent(monkeypatch)
        payload = json.loads(usdctofiat_cashout(dict(self.ALL_TOOLS[0][1])))
        assert payload["code"] != "ModuleNotFoundError"
        assert "No module named" not in payload["error"]

    def test_a_broken_client_keeps_its_own_error(self, monkeypatch):
        """Only an *absent* client is relabelled.

        A dependency missing from inside ``usdctofiat`` is a different fault
        with a different fix; claiming the client is uninstalled would send the
        user to a pip command that is already satisfied.
        """
        import sys

        class BrokenClientFinder:
            """Fail ``import usdctofiat`` the way a missing transitive dep does."""

            def find_spec(self, name, path=None, target=None):
                if name == "usdctofiat":
                    raise ModuleNotFoundError("No module named 'httpx'", name="httpx")
                return None

        monkeypatch.delitem(sys.modules, "usdctofiat", raising=False)
        monkeypatch.setattr(sys, "meta_path", [BrokenClientFinder(), *sys.meta_path])
        payload = json.loads(usdctofiat_estimate({"mode": "fast", "amount": "1", "currency": "EUR"}))
        assert payload["code"] == "ModuleNotFoundError"
        assert "httpx" in payload["error"]


class TestCurrencyMustBeOneTheProtocolHolds:
    """``platform`` is refused by name; ``currency`` was not refused at all.

    The vendor validates a platform against its catalog and raises naming the
    supported set, but ``calldata.currency_hash`` falls through to
    ``keccak(text=key)`` for anything it does not recognise. "euros", "EURO" and
    "dollars" -- what a model writes when the user says "cash out to euros" --
    therefore each produced a well-formed currency hash and a real createDeposit
    tx, returned as an ordinary ``signed: false`` prepare with nothing in it
    saying the currency was meaningless. Signing that moves USDC into a deposit
    no taker can fill.

    The refusal has to land before the client is reached: ``prepare`` opens with
    a live curator POST, so a bad code must not get that far.
    """

    ARGS = {"mode": "fast", "amount": "100", "platform": "revolut", "payee": "alice"}

    @pytest.mark.parametrize("code", ["EUR", "USD", "GBP", "AUD", "JPY", "ZAR"])
    def test_a_currency_the_protocol_holds_is_accepted(self, code, patched):
        _create, _cashout, offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "currency": code}))

        assert payload["signed"] is False
        assert offramp.prepare.call_args.kwargs["currency"] == code

    @pytest.mark.parametrize("code", ["euros", "EURO", "dollars", "XYZ", "   "])
    def test_a_currency_it_does_not_hold_is_refused_by_name(self, code, patched):
        _create, _cashout, offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "currency": code}))

        assert payload["code"] == "VALIDATION"
        assert "EUR" in payload["error"]
        # Never reached the vendor, so never reached the curator POST prepare opens with.
        offramp.prepare.assert_not_called()

    def test_the_unsigned_prepare_it_replaces_is_not_what_ships(self, patched):
        """The failure mode: a signable tx handed back for a meaningless currency."""
        _create, _cashout, _offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "currency": "euros"}))

        assert "prepared" not in payload
        assert payload.get("signed") is not False

    @pytest.mark.parametrize("code", ["eur", " gbp ", "Usd"])
    def test_casing_and_padding_are_normalised_rather_than_refused(self, code, patched):
        _create, _cashout, offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "currency": code}))

        assert payload["signed"] is False
        assert offramp.prepare.call_args.kwargs["currency"] == code.strip().upper()

    def test_estimate_refuses_it_too(self, patched):
        """An estimate in a currency nothing can fill is a quote for nothing."""
        _create, _cashout, offramp = patched

        payload = json.loads(usdctofiat_estimate({"mode": "fast", "amount": "100", "currency": "euros"}))

        assert payload["code"] == "VALIDATION"
        offramp.estimate.assert_not_called()

    def test_an_absent_currency_still_reads_as_the_missing_argument(self, patched):
        """Not the unsupported-currency error: nothing was passed to support."""
        _create, _cashout, _offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "currency": ""}))

        assert payload["error"] == "Need amount, currency, platform, and payee"

    def test_the_schema_offers_only_currencies_the_guard_accepts(self):
        """A model that obeys the enum can never be refused by the handler."""
        import schemas
        from tools import SUPPORTED_CURRENCIES

        for schema in (schemas.CASHOUT, schemas.ESTIMATE):
            offered = schema["parameters"]["properties"]["currency"]["enum"]
            assert offered == sorted(SUPPORTED_CURRENCIES)


class TestPairMustBeOneEscrowSettles:
    """The vendor refuses a platform by name; a known platform plus the wrong
    currency encoded cleanly.

    ``usdctofiat`` 0.1.0 checks the platform catalog and the currency feed
    separately. ``venmo``/``EUR``, ``monzo``/``USD`` and ``zelle``/``MXN``
    therefore each produced a well-formed createDeposit, returned as an ordinary
    ``signed: false`` prepare. EscrowV2 then reverts
    ``CurrencyNotSupported(paymentMethod, currency)`` after the approve is
    signed. The refusal has to land before the client is reached: ``prepare``
    opens with a live curator POST.

    ``tests/test_client_contract.py`` holds the vendor half of this claim.
    """

    ARGS = {"mode": "fast", "amount": "100", "payee": "alice"}

    @pytest.mark.parametrize(
        "platform,currency",
        [
            ("venmo", "USD"),
            ("revolut", "EUR"),
            ("monzo", "GBP"),
            ("paypal", "SGD"),
            ("cashapp", "USD"),
            ("zelle", "USD"),
            ("chime", "USD"),
            ("wise", "USD"),
        ],
    )
    def test_a_pair_escrow_settles_is_accepted(self, platform, currency, patched):
        _create, _cashout, offramp = patched

        payload = json.loads(
            usdctofiat_cashout({**self.ARGS, "platform": platform, "currency": currency})
        )

        assert payload["signed"] is False
        assert offramp.prepare.call_args.kwargs["platform"] == platform
        assert offramp.prepare.call_args.kwargs["currency"] == currency

    @pytest.mark.parametrize(
        "platform,currency",
        [
            ("venmo", "EUR"),
            ("cashapp", "GBP"),
            ("revolut", "PHP"),
            ("wise", "SAR"),
            ("monzo", "EUR"),
            ("paypal", "TRY"),
            ("zelle", "MXN"),
            ("chime", "CAD"),
        ],
    )
    def test_a_pair_escrow_does_not_settle_is_refused_before_the_vendor(
        self, platform, currency, patched
    ):
        _create, _cashout, offramp = patched

        payload = json.loads(
            usdctofiat_cashout({**self.ARGS, "platform": platform, "currency": currency})
        )

        assert payload["code"] == "VALIDATION"
        assert currency in payload["error"]
        assert platform in payload["error"]
        offramp.prepare.assert_not_called()

    def test_the_signable_prepare_it_replaces_is_not_what_ships(self, patched):
        """The failure mode: a signable tx for a deposit EscrowV2 will revert."""
        _create, _cashout, _offramp = patched

        payload = json.loads(
            usdctofiat_cashout({**self.ARGS, "platform": "venmo", "currency": "EUR"})
        )

        assert "prepared" not in payload
        assert payload.get("signed") is not False

    def test_the_refusal_names_the_currencies_that_platform_takes(self, patched):
        _create, _cashout, _offramp = patched

        payload = json.loads(
            usdctofiat_cashout({**self.ARGS, "platform": "venmo", "currency": "EUR"})
        )

        assert "USD" in payload["error"]

    @pytest.mark.parametrize("platform", ["Venmo", " VENMO ", "venmo"])
    def test_platform_casing_and_padding_are_normalised(self, platform, patched):
        _create, _cashout, offramp = patched

        payload = json.loads(
            usdctofiat_cashout({**self.ARGS, "platform": platform, "currency": "USD"})
        )

        assert payload["signed"] is False
        assert offramp.prepare.call_args.kwargs["platform"] == "venmo"

    def test_an_unknown_platform_is_left_to_the_vendor(self, patched):
        """The vendor already names the catalog. Duplicating that set here would
        be another copy to drift; the hole is a known platform with the wrong
        currency."""
        _create, _cashout, offramp = patched

        payload = json.loads(
            usdctofiat_cashout({**self.ARGS, "platform": "skrill", "currency": "USD"})
        )

        assert payload["signed"] is False
        offramp.prepare.assert_called_once()

    def test_the_signed_branch_is_guarded_as_well(self, patched):
        _create, cashout, _offramp = patched

        payload = json.loads(
            usdctofiat_cashout(
                {**self.ARGS, "platform": "venmo", "currency": "EUR"},
                signer=lambda tx: tx,
            )
        )

        assert payload["code"] == "VALIDATION"
        cashout.assert_not_called()

    def test_the_schema_offers_only_platforms_the_pair_map_knows(self):
        """A model that obeys the enum still has to pick a currency that rail
        settles; the handler refuses the combination the schema cannot express."""
        import schemas
        from tools import PAYMENT_METHOD_CURRENCIES

        offered = schemas.CASHOUT["parameters"]["properties"]["platform"]["enum"]
        assert offered == sorted(PAYMENT_METHOD_CURRENCIES)


class TestAmountMustNotBeABareInteger:
    """``currency`` was hashed through; ``amount`` is read as the wrong unit.

    ``calldata.parse_usdc_amount`` dispatches on the Python type rather than the
    value: an ``int`` is exact six-decimal base units, a ``str`` or ``float`` is
    human USDC. JSON has one number type, and Hermes' registry dispatches
    ``handler(args, **kwargs)`` without validating an argument against the
    schema, so a model that writes ``500`` for "cash out 500 USDC" reaches the
    vendor with an int and gets one of two wrong answers: ``minimum 1 USDC``
    below 1_000_000 -- a floor the caller is far above, so the turn dead-ends on
    an error naming neither the fault nor the fix -- or, at or above it, an
    ordinary ``signed: false`` prepare for a deposit a million times too small.

    ``tests/test_client_contract.py`` holds the vendor half of this claim.
    """

    ARGS = {"mode": "fast", "currency": "EUR", "platform": "revolut", "payee": "alice"}

    @pytest.mark.parametrize("amount", [1, 500, 1_000_000, 2_000_000, 0, True])
    def test_an_integer_amount_is_refused_before_the_vendor(self, amount, patched):
        _create, _cashout, offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "amount": amount}))

        assert payload["code"] == "VALIDATION"
        assert "base units" in payload["error"]
        # prepare opens with a live curator POST, and would encode a createDeposit
        # tx for the wrong size. Neither happens.
        offramp.prepare.assert_not_called()

    def test_the_refusal_names_the_string_to_retry_with(self, patched):
        """One retry away: the error carries the amount the caller meant."""
        _create, _cashout, _offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "amount": 500}))

        assert 'amount="500"' in payload["error"]

    def test_the_undersized_prepare_it_replaces_is_not_what_ships(self, patched):
        """The failure mode above the floor: a signable tx for 2 USDC, not 2m."""
        _create, _cashout, _offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "amount": 2_000_000}))

        assert "prepared" not in payload
        assert payload.get("signed") is not False

    @pytest.mark.parametrize("amount", ["500", "1.5", 500.0, "2000000"])
    def test_an_unambiguous_amount_passes_through_untouched(self, amount, patched):
        """Strings and floats already mean human USDC. Nothing is coerced."""
        _create, _cashout, offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "amount": amount}))

        assert payload["signed"] is False
        assert offramp.prepare.call_args.kwargs["amount"] == amount

    def test_estimate_refuses_it_too(self, patched):
        """An estimate off by a million is what the cash-out is decided on."""
        _create, _cashout, offramp = patched

        payload = json.loads(usdctofiat_estimate({"mode": "fast", "amount": 500, "currency": "EUR"}))

        assert payload["code"] == "VALIDATION"
        offramp.estimate.assert_not_called()

    def test_an_absent_amount_still_reads_as_the_missing_argument(self, patched):
        """Not the ambiguity error: nothing was passed to be ambiguous."""
        _create, _cashout, _offramp = patched

        payload = json.loads(usdctofiat_cashout({**self.ARGS, "amount": None}))

        assert payload["error"] == "Need amount, currency, platform, and payee"

    def test_the_signed_branch_is_guarded_as_well(self, patched):
        """With a host signer the vendor submits, so the size is final."""
        _create, cashout, _offramp = patched

        payload = json.loads(
            usdctofiat_cashout({**self.ARGS, "amount": 2_000_000}, signer=lambda tx: tx)
        )

        assert payload["code"] == "VALIDATION"
        cashout.assert_not_called()


class TestDepositAmountsAreLabelledBaseUnits:
    """The indexer stores remainingDeposits in six-decimal USDC, unlabeled.

    A live row of ``3863197`` is 3.863197 USDC. Returned as-is, that number
    reads as 3.8 million -- the same million-times silent-wrong-value shape
    ``TestAmountMustNotBeABareInteger`` already guards on the way in. The
    vendor prepare envelope names the unit (``amount_units``); the two read
    tools did not. Labelling rather than rewriting: the raw fields stay so a
    caller who already divided is not broken the other way, and
    ``remaining_usdc`` is the figure a model can report.

    ``tests/test_client_contract.py`` holds the vendor half of this claim.
    """

    ROW = {
        "id": "0x777777779d229cdf3110e9de47943791c26300ef_4408",
        "remainingDeposits": "3863197",
        "outstandingIntentAmount": "500000",
        "status": "ACTIVE",
    }

    @pytest.fixture
    def listed(self, patched):
        _create, _cashout, offramp = patched
        offramp.deposits.return_value = [dict(self.ROW)]
        offramp.watch.return_value = iter([dict(self.ROW)])
        return offramp

    def test_deposits_keeps_the_indexer_fields_and_names_the_usdc(self, listed):
        payload = json.loads(
            usdctofiat_deposits({"owner": "0x1111111111111111111111111111111111111111"})
        )
        row = payload["deposits"][0]

        assert row["remainingDeposits"] == "3863197"
        assert row["remaining_usdc"] == "3.863197"
        assert row["outstandingIntentAmount"] == "500000"
        assert row["outstanding_intent_usdc"] == "0.5"
        assert row["amount_unit"] == "usdc_base_units"
        assert payload["amount_unit"] == "usdc_base_units"
        assert "3.863197 USDC" in payload["amount_unit_note"]
        assert "3.8 million" in payload["amount_unit_note"]

    def test_the_unlabeled_millions_it_replaces_are_not_what_ships(self, listed):
        """The failure mode: a remainingDeposits figure with nothing saying the unit."""
        payload = json.loads(
            usdctofiat_deposits({"owner": "0x1111111111111111111111111111111111111111"})
        )
        row = payload["deposits"][0]

        assert "remaining_usdc" in row
        assert row["remaining_usdc"] != row["remainingDeposits"]

    def test_watch_labels_the_same_fields(self, listed):
        payload = json.loads(usdctofiat_watch({"deposit_id": "4408"}))
        row = payload["snapshots"][0]

        assert row["remaining_usdc"] == "3.863197"
        assert row["amount_unit"] == "usdc_base_units"
        assert payload["amount_unit"] == "usdc_base_units"

    def test_a_whole_usdc_amount_has_no_trailing_zeros(self, listed):
        listed.deposits.return_value = [
            {**self.ROW, "remainingDeposits": "100000000", "outstandingIntentAmount": "0"}
        ]

        row = json.loads(
            usdctofiat_deposits({"owner": "0x1111111111111111111111111111111111111111"})
        )["deposits"][0]

        assert row["remaining_usdc"] == "100"
        assert row["outstanding_intent_usdc"] == "0"

    def test_a_row_without_amount_fields_is_left_alone(self, patched):
        """The mocked suite's ``{id, status}`` fixture is not an amount."""
        payload = json.loads(
            usdctofiat_deposits({"owner": "0x1111111111111111111111111111111111111111"})
        )
        row = payload["deposits"][0]

        assert row == {"id": "42", "status": "ACTIVE"}
        assert "amount_unit" not in payload
        assert "amount_unit_note" not in payload

    def test_a_non_numeric_amount_does_not_drop_the_row(self, listed):
        listed.deposits.return_value = [
            {**self.ROW, "remainingDeposits": "not-units"}
        ]

        payload = json.loads(
            usdctofiat_deposits({"owner": "0x1111111111111111111111111111111111111111"})
        )
        row = payload["deposits"][0]

        assert row["remainingDeposits"] == "not-units"
        assert "remaining_usdc" not in row
        assert payload["deposits"][0]["id"] == self.ROW["id"]

    def test_the_schemas_warn_the_model_about_the_unit(self):
        """The reply label is the guard; the schema is what is read first."""
        import schemas

        for schema in (schemas.DEPOSITS, schemas.WATCH):
            blob = json.dumps(schema)
            assert "remaining_usdc" in blob
            assert "base units" in blob
        assert "EscrowV2" in schemas.DEPOSITS["description"]
        assert "usdctofiat_deposits returned" in schemas.WATCH["parameters"]["properties"]["deposit_id"]["description"]
