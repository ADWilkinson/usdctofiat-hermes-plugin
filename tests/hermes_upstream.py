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
# green plugin red. Bounded: three attempts, then the real error.
_ATTEMPTS = 3
_BACKOFF_SECONDS = 1


def _get(path):
    # raw.githubusercontent, not the API contents endpoint: hermes-agent is
    # public and the revision is pinned, so this needs no credential, and a
    # cacheable CDN read is not subject to the API's secondary rate limit --
    # which four matrix legs reading three files each will otherwise trip.
    url = f"https://raw.githubusercontent.com/{HERMES_REPO}/{HERMES_REV}/{path}"
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8")


def _fetch(path):
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            return _get(path)
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == _ATTEMPTS:
                raise
            time.sleep(_BACKOFF_SECONDS * attempt)


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
    if os.environ.get(REQUIRE_UPSTREAM_ENV) == "1":
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
