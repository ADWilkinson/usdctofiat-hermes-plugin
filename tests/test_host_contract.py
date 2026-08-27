"""Guards the Hermes host contract this plugin has to satisfy at runtime.

The installer gate is guarded (``tests/test_install_compat.py``) and the vendor
client call surface is guarded (``tests/test_client_contract.py``). The seam
between them -- what Hermes itself does with ``register(ctx)`` and the handlers
it hands back to the model -- was not. Every existing check drives ``register``
with a ``MagicMock`` context, which accepts any keyword, any arity and any
return type, so the plugin could stop loading in a real session with the whole
suite green. That is the same shape as the two failures this repo already
shipped: a package that would not build, and a documented install that exited 1.

These tests bind the plugin's actual calls against the real
``PluginContext.register_tool`` and ``ToolRegistry.dispatch`` shapes, captured
from the pinned Hermes revision in tests/hermes_pinned.py, so host drift is loud
rather than silent.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import sys
import types
from pathlib import Path

import pytest

from tests.hermes_pinned import (
    DISPATCH_HANDLER_CALL,
    HERMES_REV,
    REGISTER_TOOL_PARAMETERS,
)

ROOT = Path(__file__).resolve().parents[1]

# The namespace Hermes imports directory plugins under
# (``PluginManager._load_directory_module``). Suffixed here so a test import can
# never collide with a real one in the same interpreter.
TEST_NS_PARENT = "hermes_plugins_host_contract"

EXPECTED_TOOLS = [
    "usdctofiat_cashout",
    "usdctofiat_estimate",
    "usdctofiat_watch",
    "usdctofiat_withdraw",
    "usdctofiat_deposits",
]

# One call per tool that fails validation inside the handler, so the response
# contract can be checked without a client, a network hop or a key.
INCOMPLETE_ARGS = {
    "usdctofiat_cashout": {"mode": "fast"},
    "usdctofiat_estimate": {"mode": "fast"},
    "usdctofiat_watch": {},
    "usdctofiat_withdraw": {},
    "usdctofiat_deposits": {},
}


def register_tool_signature():
    """Rebuild ``PluginContext.register_tool``'s signature from the snapshot.

    Names, kinds and whether-defaulted are all that decide whether a call binds.
    Annotations and default *values* are deliberately not captured: pinning them
    would couple this guard to upstream's typing style and fail on a harmless
    annotation edit.
    """
    return inspect.Signature(
        [
            inspect.Parameter(
                parameter["name"],
                getattr(inspect.Parameter, parameter["kind"]),
                default=None if parameter["has_default"] else inspect.Parameter.empty,
            )
            for parameter in REGISTER_TOOL_PARAMETERS
        ]
    )


def load_plugin_as_hermes_does():
    """Import the plugin the way ``PluginManager._load_directory_module`` does.

    Hermes execs ``__init__.py`` under a package name with
    ``submodule_search_locations`` set, so ``from . import schemas, tools``
    resolves relatively. ``tests/test_plugin.py`` loads the file without search
    locations, which can only ever exercise the ``ImportError`` fallback -- the
    branch Hermes never takes. A relative-import break would therefore pass
    every other test and fail on load in a real session.
    """
    if TEST_NS_PARENT not in sys.modules:
        namespace = types.ModuleType(TEST_NS_PARENT)
        namespace.__path__ = []
        namespace.__package__ = TEST_NS_PARENT
        sys.modules[TEST_NS_PARENT] = namespace

    module_name = f"{TEST_NS_PARENT}.usdctofiat"
    stale_prefix = f"{module_name}."
    for cached in [n for n in sys.modules if n == module_name or n.startswith(stale_prefix)]:
        del sys.modules[cached]

    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(ROOT)]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class RecordingContext:
    """A plugin context that binds every call against the real host signature."""

    def __init__(self, signature):
        self._signature = signature
        self.calls = []

    def register_tool(self, *args, **kwargs):
        try:
            bound = self._signature.bind(*args, **kwargs)
        except TypeError as exc:
            tool = kwargs.get("name") or (args[0] if args else "<unnamed>")
            raise AssertionError(
                f"register_tool for {tool!r} does not bind against "
                f"PluginContext.register_tool{self._signature} at "
                f"{HERMES_REV[:7]}: {exc}"
            ) from exc
        self.calls.append(bound.arguments)


@pytest.fixture(scope="module")
def plugin_module():
    return load_plugin_as_hermes_does()


@pytest.fixture
def registered(plugin_module):
    """Drive ``register()`` through the pinned ``PluginContext.register_tool``."""
    ctx = RecordingContext(register_tool_signature())
    plugin_module.register(ctx)
    return ctx.calls


def test_plugin_imports_the_way_hermes_does(plugin_module):
    """The relative-import branch Hermes actually takes."""
    assert callable(plugin_module.register)
    assert plugin_module.PLUGIN_NAME == "usdctofiat"
    assert f"{TEST_NS_PARENT}.usdctofiat.tools" in sys.modules
    assert f"{TEST_NS_PARENT}.usdctofiat.schemas" in sys.modules


def test_register_binds_against_the_real_host_signature(registered):
    """Every keyword ``register()`` passes is one the pinned host accepts.

    Binding rather than comparing signatures keeps added optional host
    parameters green; only removing or renaming something the plugin passes, or
    the host adding a required parameter the plugin omits, fails.
    """
    assert [call["name"] for call in registered] == EXPECTED_TOOLS
    for call in registered:
        assert call["toolset"] == "usdctofiat"
        assert callable(call["handler"])
        assert isinstance(call["schema"], dict)


def test_host_signature_would_reject_an_unknown_keyword():
    """Prove the bind guard bites.

    ``register_tool`` takes no ``**kwargs`` upstream, so an unknown keyword is a
    hard ``TypeError`` in a real session rather than an ignored extra. If that
    ever changes, the bind above stops proving anything and this fails first.
    """
    signature = register_tool_signature()
    assert not any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    with pytest.raises(TypeError):
        signature.bind(
            name="usdctofiat_cashout",
            toolset="usdctofiat",
            schema={},
            handler=lambda args, **kwargs: "",
            not_a_host_parameter=True,
        )


def test_handlers_accept_the_host_dispatch_call_shape(registered):
    """Hermes calls ``entry.handler(args, **kwargs)``.

    ``handler(**args)`` instead of ``handler(args)`` would break all five tools
    at runtime with the mocked suite still green, so the call shape is one
    captured from the real dispatcher rather than assumed.
    """
    assert DISPATCH_HANDLER_CALL["positional"] == 1, "host stopped passing args positionally"
    assert DISPATCH_HANDLER_CALL["forwards_kwargs"], "host stopped forwarding **kwargs"
    assert not DISPATCH_HANDLER_CALL["keywords"], (
        f"host now passes named arguments {DISPATCH_HANDLER_CALL['keywords']} at "
        f"{HERMES_REV[:7]}; the handlers accept them via **kwargs, but check that is intended."
    )

    for entry in registered:
        signature = inspect.signature(entry["handler"])
        signature.bind({})
        signature.bind({}, some_future_host_kwarg=True)


def test_handlers_return_a_string_for_every_tool(registered):
    """Hermes rejects any handler result that is not a string.

    ``ToolRegistry._normalize_handler_result`` replaces a non-string return with
    a ``tool_result_contract`` error, so a handler that returned a dict would
    look fine locally and reach the model as an error.
    """
    for entry in registered:
        result = entry["handler"](INCOMPLETE_ARGS[entry["name"]])
        assert isinstance(result, str), f"{entry['name']} returned {type(result).__name__}"
        assert "error" in json.loads(result)


def test_schema_names_match_the_registered_tool_names(registered):
    """The registry keys on ``name``; the model reads ``schema['name']``.

    A mismatch registers one tool and advertises another, so the model emits a
    call the registry cannot resolve.
    """
    for entry in registered:
        schema = entry["schema"]
        assert schema["name"] == entry["name"]
        assert schema["description"].strip(), f"{entry['name']} has no description"
        assert schema["parameters"]["type"] == "object"


def test_manifest_provides_tools_matches_what_register_registers(registered):
    """``hermes plugins list`` and Doctor name a plugin's tools from the manifest.

    ``provides_tools`` is a promise read by the host, not documentation; a name
    there that ``register()`` never registers is a tool Hermes advertises and
    cannot dispatch.
    """
    manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    block = re.search(r"^provides_tools:\n((?:  - \S+\n)+)", manifest, re.MULTILINE)
    assert block is not None, "plugin.yaml declares no provides_tools"
    declared = re.findall(r"  - (\S+)", block.group(1))
    assert declared == [entry["name"] for entry in registered]
