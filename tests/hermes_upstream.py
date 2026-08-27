"""The pinned Hermes revision every host-side guard reads from.

Two guards in this suite read real upstream source rather than a local
restatement of it: the installer ceiling that gates
``hermes plugins install`` (``tests/test_install_compat.py``) and the runtime
contract ``register()`` and the handlers must satisfy
(``tests/test_host_contract.py``). They have to read the *same* revision -- a
second copy of the SHA is one more thing that can drift -- so the pin lives
here alone.

Hermes Agent v0.20.5 (2026.8.19). The documented install and
``hermes plugins doctor usdctofiat --ci`` were both verified green against this
exact revision in an isolated HERMES_HOME on 2026-08-26. Bump deliberately:
re-run that isolated install + Doctor readback before changing this SHA or any
constant mirrored from it.
"""

from __future__ import annotations

import ast
import os
import time
import urllib.error
import urllib.request

import pytest

HERMES_REPO = "NousResearch/hermes-agent"
HERMES_REV = "057dcdf236f8a6a26721c10fcc6ccb72726e272a"

# Set in CI so a network failure is a hard failure there; offline runs skip the
# upstream reads and still exercise the rest of the suite.
REQUIRE_UPSTREAM_ENV = "HERMES_COMPAT_REQUIRE_UPSTREAM"

_CACHE: dict[str, str] = {}
_FAILURES: dict[str, Exception] = {}


# Every read is a required check in CI, so one transient blip must not turn a
# green plugin red. GitHub answers a secondary rate limit with 429 and often a
# Retry-After measured in tens of seconds, so honour that header when it is
# there and fall back to a widening wait when it is not. Bounded: four
# attempts and a capped wait, then the real error.
_ATTEMPTS = 4
_BACKOFF_SECONDS = (5, 15, 45)
_MAX_WAIT_SECONDS = 90


def _get(path):
    # The authenticated API contents endpoint, not raw.githubusercontent: raw
    # rate-limits unauthenticated reads per source IP, and GitHub-hosted
    # runners share theirs -- three of four matrix legs took a 429 from it in
    # one run while the fourth passed. A token buys 5000/hour instead.
    url = f"https://api.github.com/repos/{HERMES_REPO}/contents/{path}?ref={HERMES_REV}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github.raw"})
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def _retry_after(exc, attempt):
    """Seconds to wait before the next attempt, capped."""
    header = getattr(exc, "headers", None)
    raw = header.get("Retry-After") if header is not None else None
    try:
        requested = int(raw)
    except (TypeError, ValueError):
        requested = _BACKOFF_SECONDS[attempt - 1]
    return max(1, min(requested, _MAX_WAIT_SECONDS))


def _required():
    return os.environ.get(REQUIRE_UPSTREAM_ENV) == "1"


def _fetch(path):
    # Only spend the retry budget where the read is a required check. A local
    # or offline run skips instead, so it should find that out in one attempt
    # rather than sitting through a minute of backoff per file.
    attempts = _ATTEMPTS if _required() else 1
    for attempt in range(1, attempts + 1):
        try:
            return _get(path)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise
            time.sleep(_retry_after(exc, attempt))


def read_source(path):
    """Return one file from the pinned revision.

    Required in CI (``HERMES_COMPAT_REQUIRE_UPSTREAM=1``); skipped offline so
    the rest of the suite still runs without network.
    """
    if path in _CACHE:
        return _CACHE[path]
    # Remember the failure too. Several tests read the same file, and without
    # this an offline run pays the full retry budget once per test.
    if path in _FAILURES:
        _unreachable(path, _FAILURES[path])
    try:
        source = _fetch(path)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _FAILURES[path] = exc
        _unreachable(path, exc)
    _CACHE[path] = source
    return source


def _unreachable(path, exc):
    if _required():
        pytest.fail(f"could not read {HERMES_REPO}@{HERMES_REV[:7]}:{path}: {exc}")
    pytest.skip(f"upstream {path} unreachable: {exc}")


def find_function(source, class_name, func_name, path):
    """Return the ``ast.FunctionDef`` for ``class_name.func_name`` upstream.

    A rename upstream fails here rather than silently skipping the guard that
    depends on it.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == func_name:
                    return child
    raise AssertionError(
        f"{class_name}.{func_name} not found in {path} at {HERMES_REV[:7]}; "
        "upstream moved -- re-verify the plugin against the new shape before repinning."
    )
