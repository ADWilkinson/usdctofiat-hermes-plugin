"""Guards the documented `hermes plugins install` entry point.

Hermes applies two independent manifest-version rules. Its runtime parser
(``hermes_cli/plugins.py``) understands v2 additively and reads the v2 fields
regardless of the declared number, but its Git installer
(``hermes_cli/plugins_cmd.py``) enforces its own ``_SUPPORTED_MANIFEST_VERSION``
ceiling *before* it copies anything into place. A manifest above that ceiling
therefore loads fine in-process while the documented owner/repo install exits 1
without installing anything -- which is exactly how this plugin shipped broken
while every mocked check stayed green.

These tests read the ceiling from the real upstream installer at a pinned
revision, so an upstream change is loud rather than silent.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.hermes_upstream import HERMES_REPO, HERMES_REV, read_source

# The revision these constants are mirrored from is pinned in
# tests/hermes_upstream.py; bump it there, not here.
INSTALLER_PATH = "hermes_cli/plugins_cmd.py"

# Mirrors `_SUPPORTED_MANIFEST_VERSION` in the installer at HERMES_REV.
SUPPORTED_INSTALLER_MANIFEST_VERSION = 1

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


def test_pinned_installer_ceiling_still_matches_upstream():
    """Read the real ceiling from the pinned installer source.

    Required in CI (`HERMES_COMPAT_REQUIRE_UPSTREAM=1`); skipped offline so the
    rest of the suite still runs without network.
    """
    source = read_source(INSTALLER_PATH)

    match = re.search(r"^_SUPPORTED_MANIFEST_VERSION\s*=\s*(\d+)", source, re.MULTILINE)
    assert match is not None, (
        f"_SUPPORTED_MANIFEST_VERSION not found in {INSTALLER_PATH} at {HERMES_REV[:7]}; "
        "the installer gate moved -- re-verify the isolated install before repinning."
    )

    upstream_ceiling = int(match.group(1))
    assert upstream_ceiling == SUPPORTED_INSTALLER_MANIFEST_VERSION, (
        f"pinned installer ceiling changed to {upstream_ceiling}; update "
        "SUPPORTED_INSTALLER_MANIFEST_VERSION after re-verifying the isolated install."
    )

    declared = declared_manifest_version((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert installer_accepts(declared, upstream_ceiling)
