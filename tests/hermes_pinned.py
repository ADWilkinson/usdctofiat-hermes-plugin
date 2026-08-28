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

# `tools/plugin_guard.py` -- the security scan `_install_plugin_core` runs on the
# fresh clone *before* it copies anything into place. Its verdict decides whether
# the documented one-line install proceeds, needs a confirmation the docs never
# mention, or is refused outright.
PLUGIN_SCANNER_VERSION = "plugin-guard-v1"

# The only verdict `should_allow_plugin_install` lets through unprompted.
UNATTENDED_INSTALL_VERDICT = "safe"

# `_determine_verdict`: a finding at one of these severities forces the verdict
# beside it. Severities absent here (medium, low) are informational.
SCAN_VERDICT_BY_SEVERITY = {
    "critical": "dangerous",
    "high": "caution",
}

# `plugin_guard.SEVERITY_REMAP`: severities the plugin scanner overrides on the
# structural findings it raises, relaxing the skills-guard defaults.
SCAN_SEVERITY_REMAP = {
    "binary_file": "high",
    "curl_pipe_shell": "high",
    "hermes_env_access": "medium",
}

# `skills_guard.SUSPICIOUS_BINARY_EXTENSIONS`: shipping one of these raises
# `binary_file`, which SCAN_SEVERITY_REMAP puts at `high` for plugins.
SCAN_BINARY_EXTENSIONS = [".app", ".bin", ".com", ".dat", ".deb", ".dll", ".dmg", ".dylib", ".exe", ".msi", ".rpm", ".so"]

# `plugin_guard.EXCLUDED_DIRS`: never walked, so nothing under them can trip a
# finding.
SCAN_EXCLUDED_DIRS = [".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".venv", "__pycache__", "node_modules", "venv"]

# `plugin_guard` structural limits. Exceeding one raises a medium finding, which
# does not block on its own but is the tree growing past what the host expects.
SCAN_MAX_FILE_COUNT = 400
SCAN_MAX_SINGLE_FILE_KB = 1024
SCAN_MAX_TOTAL_SIZE_KB = 10240
