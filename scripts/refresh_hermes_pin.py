#!/usr/bin/env python3
"""Regenerate tests/hermes_pinned.py from real Hermes source.

The guards in tests/ check this plugin against the shapes Hermes actually has:
the installer's manifest-version ceiling, ``PluginContext.register_tool``'s
parameter list, and the way ``ToolRegistry.dispatch`` calls a handler. Reading
those over the network at test time made a required check depend on GitHub
answering, and GitHub's anti-scraping protection answers repeated content reads
of a repo you do not own with 429 -- three of four matrix legs, then the single
job that replaced them.

It was also redundant. The revision is pinned by SHA, so upstream source at that
SHA cannot change; re-reading it every run re-derives a constant. So read it
once, here, and commit the result.

Run this when bumping the pin, and re-verify the isolated
``hermes plugins install`` + ``hermes plugins doctor usdctofiat --ci`` readback
before you do:

    python scripts/refresh_hermes_pin.py --rev <sha>

With no --rev it re-derives the currently pinned revision, which is what the
scheduled hermes-pin workflow does to prove the committed snapshot is faithful.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests" / "hermes_pinned.py"

HERMES_REPO = "NousResearch/hermes-agent"

INSTALLER_PATH = "hermes_cli/plugins_cmd.py"
PLUGINS_PATH = "hermes_cli/plugins.py"
REGISTRY_PATH = "tools/registry.py"

_ATTEMPTS = 5
_BACKOFF_SECONDS = (5, 15, 45, 90)
_MAX_WAIT_SECONDS = 120

def _get(path, rev):
    url = f"https://api.github.com/repos/{HERMES_REPO}/contents/{path}?ref={rev}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github.raw"})
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def fetch(path, rev):
    """Read one file at the pinned revision, retrying GitHub's throttles."""
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            return _get(path, rev)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == _ATTEMPTS:
                raise SystemExit(f"could not read {HERMES_REPO}@{rev[:7]}:{path}: {exc}")
            headers = getattr(exc, "headers", None)
            raw = headers.get("Retry-After") if headers is not None else None
            try:
                wait = int(raw)
            except (TypeError, ValueError):
                wait = _BACKOFF_SECONDS[attempt - 1]
            wait = max(1, min(wait, _MAX_WAIT_SECONDS))
            print(f"  {path}: {exc}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)


def find_function(source, class_name, func_name, path, rev):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == func_name:
                    return child
    raise SystemExit(f"{class_name}.{func_name} not found in {path} at {rev[:7]}")


def parameters_of(func):
    """Name, kind and whether-defaulted for each parameter. Values and
    annotations are dropped: only these decide whether a call binds."""
    spec = func.args
    positional = spec.posonlyargs + spec.args
    first_defaulted = len(positional) - len(spec.defaults)

    out = []
    for index, arg in enumerate(positional):
        if arg.arg == "self":
            continue
        out.append(
            {
                "name": arg.arg,
                "kind": "POSITIONAL_ONLY" if index < len(spec.posonlyargs) else "POSITIONAL_OR_KEYWORD",
                "has_default": index >= first_defaulted,
            }
        )
    if spec.vararg is not None:
        out.append({"name": spec.vararg.arg, "kind": "VAR_POSITIONAL", "has_default": False})
    for arg, default in zip(spec.kwonlyargs, spec.kw_defaults):
        out.append({"name": arg.arg, "kind": "KEYWORD_ONLY", "has_default": default is not None})
    if spec.kwarg is not None:
        out.append({"name": spec.kwarg.arg, "kind": "VAR_KEYWORD", "has_default": False})
    return out


def handler_call_shape(dispatch, rev):
    """How ``ToolRegistry.dispatch`` invokes a registered handler."""
    calls = [
        node
        for node in ast.walk(dispatch)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "handler"
    ]
    if not calls:
        raise SystemExit(f"no handler call in ToolRegistry.dispatch at {rev[:7]}")
    shapes = {
        (len(call.args), tuple(keyword.arg for keyword in call.keywords))
        for call in calls
    }
    if len(shapes) != 1:
        raise SystemExit(f"ToolRegistry.dispatch calls handlers inconsistently at {rev[:7]}: {shapes}")
    positional, keywords = shapes.pop()
    return {
        "positional": positional,
        "forwards_kwargs": keywords == (None,),
        "keywords": [name for name in keywords if name is not None],
    }


def installer_ceiling(source, rev):
    match = re.search(r"^_SUPPORTED_MANIFEST_VERSION\s*=\s*(\d+)", source, re.MULTILINE)
    if match is None:
        raise SystemExit(
            f"_SUPPORTED_MANIFEST_VERSION not found in {INSTALLER_PATH} at {rev[:7]}; "
            "the installer gate moved -- re-verify the isolated install before repinning."
        )
    return int(match.group(1))


def render(rev, ceiling, register_tool, dispatch_shape):
    parameters = "\n".join(
        '    {{"name": "{name}", "kind": "{kind}", "has_default": {has_default}}},'.format(**p)
        for p in register_tool
    )
    keywords = ", ".join(f'"{name}"' for name in dispatch_shape["keywords"])
    return f'''"""What Hermes actually looks like at the pinned revision.

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

HERMES_REPO = "{HERMES_REPO}"
HERMES_REV = "{rev}"

INSTALLER_PATH = "{INSTALLER_PATH}"
PLUGINS_PATH = "{PLUGINS_PATH}"
REGISTRY_PATH = "{REGISTRY_PATH}"

# `_SUPPORTED_MANIFEST_VERSION` in the installer: the ceiling it enforces
# *before* copying anything into place, so a manifest above it makes
# `hermes plugins install` exit 1 without installing.
INSTALLER_MANIFEST_VERSION_CEILING = {ceiling}

# `PluginContext.register_tool` parameters. Names, kinds and whether-defaulted
# only -- those decide whether a call binds; annotations and default values do
# not.
REGISTER_TOOL_PARAMETERS = [
{parameters}
]

# How `ToolRegistry.dispatch` invokes a handler: `handler(args, **kwargs)`.
DISPATCH_HANDLER_CALL = {{
    "positional": {dispatch_shape["positional"]},
    "forwards_kwargs": {dispatch_shape["forwards_kwargs"]!r},
    "keywords": [{keywords}],
}}
'''


def current_rev():
    text = SNAPSHOT.read_text(encoding="utf-8")
    match = re.search(r'^HERMES_REV = "([0-9a-f]{40})"', text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"no HERMES_REV in {SNAPSHOT}")
    return match.group(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", help="Hermes commit SHA to pin (default: the one already pinned)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed snapshot differs from what upstream yields",
    )
    args = parser.parse_args()

    rev = args.rev or current_rev()
    print(f"reading {HERMES_REPO}@{rev[:7]}", file=sys.stderr)

    installer = fetch(INSTALLER_PATH, rev)
    plugins = fetch(PLUGINS_PATH, rev)
    registry = fetch(REGISTRY_PATH, rev)

    rendered = render(
        rev,
        installer_ceiling(installer, rev),
        parameters_of(find_function(plugins, "PluginContext", "register_tool", PLUGINS_PATH, rev)),
        handler_call_shape(
            find_function(registry, "ToolRegistry", "dispatch", REGISTRY_PATH, rev), rev
        ),
    )

    if args.check:
        if SNAPSHOT.read_text(encoding="utf-8") == rendered:
            print(f"{SNAPSHOT.relative_to(ROOT)} is faithful to {rev[:7]}", file=sys.stderr)
            return 0
        SNAPSHOT.write_text(rendered, encoding="utf-8")
        subprocess.run(["git", "--no-pager", "diff", "--", str(SNAPSHOT)], cwd=ROOT, check=False)
        raise SystemExit(
            f"{SNAPSHOT.relative_to(ROOT)} does not match {HERMES_REPO}@{rev[:7]}; "
            "the diff above is what upstream actually says."
        )

    SNAPSHOT.write_text(rendered, encoding="utf-8")
    print(f"wrote {SNAPSHOT.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
