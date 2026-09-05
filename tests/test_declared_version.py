"""Guards the product version Hermes actually prints.

Hermes reads ``version`` out of ``plugin.yaml`` and renders it in
``hermes plugins list``, ``list --plain``, ``list --json``, and
``plugins info``. The installed git revision is recorded in install metadata
but no read command surfaces it, so this number is the only build identity a
user or a support conversation can see.

``pyproject.toml`` declares the same number for the wheel. ``CHANGELOG.md``
is the third copy: its newest heading is what a caller is told changed.
Nothing else keeps the three honest, so they can drift independently and CI
would still be green.

These tests check the three declarations against each other. They do not pin
a literal current version: that would make the next bump edit the assertion
instead of the changelog. ``manifest_version`` is a different field, owned by
``tests/test_install_compat.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def declared_plugin_version(text: str) -> str | None:
    """Read product ``version`` out of a manifest without a YAML dependency."""
    match = re.search(r"^version:\s*(\S+)", text, re.MULTILINE)
    return None if match is None else match.group(1)


def declared_pyproject_version(text: str) -> str | None:
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return None if match is None else match.group(1)


def newest_changelog_version(text: str) -> str | None:
    """First ``## X.Y.Z`` heading, ignoring the title and any Unreleased block."""
    for line in text.splitlines():
        match = re.match(r"^##\s+(\d+\.\d+\.\d+)\b", line)
        if match:
            return match.group(1)
    return None


def versions_agree(plugin: str | None, pyproject: str | None, changelog: str | None) -> bool:
    return (
        plugin is not None
        and plugin == pyproject == changelog
        and re.fullmatch(r"\d+\.\d+\.\d+", plugin) is not None
    )


def test_declared_versions_agree():
    plugin = declared_plugin_version((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    pyproject = declared_pyproject_version((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    changelog = newest_changelog_version((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert versions_agree(plugin, pyproject, changelog), (
        f"plugin.yaml version={plugin!r}, pyproject.toml version={pyproject!r}, "
        f"CHANGELOG.md newest={changelog!r}; Hermes will print plugin.yaml's number "
        "and the other two will describe a different install."
    )


def test_guard_rejects_a_lone_drift():
    """The durable half: editing one declaration without the others must fail.

    The live files are checked by test_declared_versions_agree. These fixtures
    prove the comparison itself bites, so a later bump cannot pass by
    coincidentally sharing a leftover 1.0.0 in only one of the three.
    """
    assert versions_agree("2.0.0", "2.0.0", "2.0.0")
    assert not versions_agree("1.0.0", "2.0.0", "2.0.0")
    assert not versions_agree("2.0.0", "1.0.0", "2.0.0")
    assert not versions_agree("2.0.0", "2.0.0", "1.0.0")
    assert not versions_agree(None, "2.0.0", "2.0.0")
    assert not versions_agree("2.0.0", "2.0.0", None)
    assert not versions_agree("not-a-version", "not-a-version", "not-a-version")


def test_changelog_parser_takes_the_newest_heading():
    text = (
        "# Changelog\n\n"
        "## 2.0.0 — 2026-09-05\n\n"
        "- a caller-visible change (#25)\n\n"
        "## 1.0.0 — 2026-08-14\n\n"
        "- initial\n"
    )
    assert newest_changelog_version(text) == "2.0.0"
    assert newest_changelog_version("# Changelog\n\nNo headings yet.\n") is None
    assert newest_changelog_version("## Unreleased\n\n## 1.0.0\n") == "1.0.0"


def test_manifest_parser_ignores_manifest_version():
    """``manifest_version`` is the installer ceiling. Mixing it in here would
    either pin the product version to 1 or raise the ceiling and break install.
    """
    text = (
        "name: usdctofiat\n"
        "version: 2.0.0\n"
        "manifest_version: 1\n"
        "api_version: 1\n"
    )
    assert declared_plugin_version(text) == "2.0.0"
    assert declared_pyproject_version('name = "usdctofiat-hermes-plugin"\nversion = "2.0.0"\n') == "2.0.0"
    assert declared_plugin_version("manifest_version: 1\n") is None
