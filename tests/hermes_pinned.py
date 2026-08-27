"""What Hermes actually looks like at the pinned revision.

GENERATED -- do not edit by hand. Run scripts/refresh_hermes_pin.py.

Committed rather than fetched at test time: the revision is pinned by SHA, so
this is a constant, and re-deriving it on every run made a required check
depend on GitHub answering. The scheduled hermes-pin workflow re-derives it and
fails if this file is not faithful.

Bump deliberately. The documented install and
``hermes plugins doctor usdctofiat --ci`` must both be verified green against a
new revision in an isolated HERMES_HOME before it is pinned here; v0.20.5
(2026.8.19) was verified that way on 2026-08-26.
"""

from __future__ import annotations

HERMES_REPO = "NousResearch/hermes-agent"
HERMES_REV = "057dcdf236f8a6a26721c10fcc6ccb72726e272a"

INSTALLER_PATH = "hermes_cli/plugins_cmd.py"
PLUGINS_PATH = "hermes_cli/plugins.py"
REGISTRY_PATH = "tools/registry.py"

# `_SUPPORTED_MANIFEST_VERSION` in the installer: the ceiling it enforces
# *before* copying anything into place, so a manifest above it makes
# `hermes plugins install` exit 1 without installing.
INSTALLER_MANIFEST_VERSION_CEILING = 1

# `PluginContext.register_tool` parameters. Names, kinds and whether-defaulted
# only -- those decide whether a call binds; annotations and default values do
# not.
REGISTER_TOOL_PARAMETERS = [
    {"name": "name", "kind": "POSITIONAL_OR_KEYWORD", "has_default": False},
    {"name": "toolset", "kind": "POSITIONAL_OR_KEYWORD", "has_default": False},
    {"name": "schema", "kind": "POSITIONAL_OR_KEYWORD", "has_default": False},
    {"name": "handler", "kind": "POSITIONAL_OR_KEYWORD", "has_default": False},
    {"name": "check_fn", "kind": "POSITIONAL_OR_KEYWORD", "has_default": True},
    {"name": "requires_env", "kind": "POSITIONAL_OR_KEYWORD", "has_default": True},
    {"name": "is_async", "kind": "POSITIONAL_OR_KEYWORD", "has_default": True},
    {"name": "description", "kind": "POSITIONAL_OR_KEYWORD", "has_default": True},
    {"name": "emoji", "kind": "POSITIONAL_OR_KEYWORD", "has_default": True},
    {"name": "override", "kind": "POSITIONAL_OR_KEYWORD", "has_default": True},
]

# How `ToolRegistry.dispatch` invokes a handler: `handler(args, **kwargs)`.
DISPATCH_HANDLER_CALL = {
    "positional": 1,
    "forwards_kwargs": True,
    "keywords": [],
}
