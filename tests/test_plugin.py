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
            "delegate_hook": None,
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
    assert withdrawn["to"].lower().endswith("ef")
    assert withdrawn["data"] == "0xwithdraw"


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
