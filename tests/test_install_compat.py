"""Guards the documented `hermes plugins install` entry point.

Hermes applies two independent manifest-version rules. Its runtime parser
(``hermes_cli/plugins.py``) understands v2 additively and reads the v2 fields
regardless of the declared number, but its Git installer
(``hermes_cli/plugins_cmd.py``) enforces its own ``_SUPPORTED_MANIFEST_VERSION``
ceiling *before* it copies anything into place. A manifest above that ceiling
therefore loads fine in-process while the documented owner/repo install exits 1
without installing anything -- which is exactly how this plugin shipped broken
while every mocked check stayed green.

These tests check the manifest against the ceiling the real installer enforces,
captured from the pinned revision in tests/hermes_pinned.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.hermes_pinned import (
    HERMES_REPO,
    HERMES_REV,
    INSTALLER_MANIFEST_VERSION_CEILING as SUPPORTED_INSTALLER_MANIFEST_VERSION,
)

# The manifest version this plugin shipped with while the install was broken.
# Kept as the regression fixture so the guard is proven to bite.
INCOMPATIBLE_MANIFEST_VERSION = 2

ROOT = Path(__file__).resolve().parents[1]


def installer_accepts(manifest_version, ceiling=SUPPORTED_INSTALLER_MANIFEST_VERSION):
    """Mirror the installer's pre-install gate. Absent means v1, always fine."""
    if manifest_version is None:
        return True
    return int(manifest_version) <= ceiling


def declared_manifest_version(text):
    """Read `manifest_version` out of a manifest without a YAML dependency."""
    match = re.search(r"^manifest_version:\s*(\S+)", text, re.MULTILINE)
    return None if match is None else match.group(1)


def test_manifest_version_is_installable():
    declared = declared_manifest_version((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert installer_accepts(declared), (
        f"plugin.yaml declares manifest_version {declared}, above the "
        f"{HERMES_REPO}@{HERMES_REV[:7]} installer ceiling of "
        f"{SUPPORTED_INSTALLER_MANIFEST_VERSION}; "
        "`hermes plugins install` would exit 1 before installing."
    )


def test_guard_rejects_the_manifest_that_broke_the_install():
    assert not installer_accepts(INCOMPATIBLE_MANIFEST_VERSION)
    assert not installer_accepts(
        declared_manifest_version(f"name: usdctofiat\nmanifest_version: {INCOMPATIBLE_MANIFEST_VERSION}\n")
    )


def test_guard_reads_a_real_installer_ceiling():
    """The snapshot is derived from upstream, so sanity-check what it yielded.

    scripts/refresh_hermes_pin.py fails loudly if `_SUPPORTED_MANIFEST_VERSION`
    is missing, and the scheduled hermes-pin workflow re-derives this file and
    fails if it drifted. This only catches a hand-edit that made the ceiling
    meaningless.
    """
    assert isinstance(SUPPORTED_INSTALLER_MANIFEST_VERSION, int)
    assert SUPPORTED_INSTALLER_MANIFEST_VERSION >= 1
    assert re.fullmatch(r"[0-9a-f]{40}", HERMES_REV), HERMES_REV
    assert HERMES_REPO == "NousResearch/hermes-agent"
