"""Guards the security scan `hermes plugins install` runs before it installs.

``_install_plugin_core`` applies three gates to a fresh clone. Two are already
guarded: the manifest-version ceiling (``tests/test_install_compat.py``) and,
after load, the host runtime (``tests/test_host_contract.py``). The third is
``_scan_plugin_tree`` -- ``tools/plugin_guard.py`` scans the cloned tree and
maps its verdict to an install decision:

    safe      -> installs
    caution   -> refused unless the caller passes --force or answers a prompt
    dangerous -> refused; --force does not override

So a ``caution`` verdict does not merely warn. It breaks the one-line install
this repo's README documents, in the same silent way the manifest version did:
every local check green, ``hermes plugins install ADWilkinson/usdctofiat-hermes-plugin``
exits 1. Nothing here checked that.

Scope. The scanner has two halves. Its structural half is self-contained and is
what this repo's own tree can realistically trip -- ship a wheel, a ``.so``, a
symlink out of the tree -- so it is re-implemented here against the pinned
constants and run over the tracked tree. Its content half is ~1200 lines of
threat regexes in ``tools/skills_guard.py``; re-implementing those would pin
this repo to upstream's regex style and rot immediately. That half is checked
against the real scanner by ``scripts/hermes_install_scan.py``, which the
weekly hermes-pin workflow runs. Offline here, real upstream engine weekly.

The tracked tree is the subject, not the working directory: the installer clones
the repo, so ignored build output (``build/``, ``*.egg-info/``, ``dist/``) is not
present at scan time and must not be scanned here either.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.hermes_pinned import (
    HERMES_REV,
    SCAN_BINARY_EXTENSIONS,
    SCAN_EXCLUDED_DIRS,
    SCAN_MAX_FILE_COUNT,
    SCAN_MAX_SINGLE_FILE_KB,
    SCAN_MAX_TOTAL_SIZE_KB,
    SCAN_SEVERITY_REMAP,
    SCAN_VERDICT_BY_SEVERITY,
    UNATTENDED_INSTALL_VERDICT,
)

ROOT = Path(__file__).resolve().parents[1]


def tracked_files():
    """What a fresh clone contains, which is what the installer scans."""
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [name for name in listing.split("\0") if name]


def structural_findings(root, paths):
    """Re-implement ``plugin_guard._check_plugin_structure`` over *paths*.

    Returns ``(pattern_id, severity, path)`` per finding, with the plugin
    scanner's severity remap already applied.
    """
    findings = []
    file_count = 0
    total_size = 0

    for rel in paths:
        if any(part in SCAN_EXCLUDED_DIRS for part in Path(rel).parts):
            continue
        path = root / rel
        file_count += 1

        if path.is_symlink():
            # Non-strict, as upstream resolves it: a dangling symlink still has
            # a target, and one pointing out of the tree is an escape whether or
            # not it currently resolves. Only an OSError (a resolution loop) is
            # the weaker `broken_symlink`.
            try:
                resolved = path.resolve()
            except OSError:
                findings.append(("broken_symlink", "medium", rel))
                continue
            if not resolved.is_relative_to(root.resolve()):
                findings.append(("symlink_escape", "critical", rel))
            continue

        if not path.is_file():
            continue

        size = path.stat().st_size
        total_size += size
        if size > SCAN_MAX_SINGLE_FILE_KB * 1024:
            findings.append(("oversized_file", "medium", rel))
        if path.suffix.lower() in SCAN_BINARY_EXTENSIONS:
            findings.append(
                ("binary_file", SCAN_SEVERITY_REMAP.get("binary_file", "critical"), rel)
            )

    if file_count > SCAN_MAX_FILE_COUNT:
        findings.append(("too_many_files", "medium", "(directory)"))
    if total_size > SCAN_MAX_TOTAL_SIZE_KB * 1024:
        findings.append(("oversized_bundle", "medium", "(directory)"))
    return findings


def verdict(findings):
    """``skills_guard._determine_verdict``: worst severity wins."""
    for severity in ("critical", "high"):
        if severity in SCAN_VERDICT_BY_SEVERITY and any(f[1] == severity for f in findings):
            return SCAN_VERDICT_BY_SEVERITY[severity]
    return "safe"


@pytest.fixture(scope="module")
def tracked():
    return tracked_files()


def test_tracked_tree_is_what_the_installer_would_scan(tracked):
    """Sanity-check the subject before asserting anything about it."""
    assert "plugin.yaml" in tracked
    assert "__init__.py" in tracked
    assert not any(name.startswith(("build/", "dist/")) for name in tracked), (
        "build output is tracked; the installer would scan it"
    )


def test_the_shipped_tree_installs_without_a_confirmation_prompt(tracked):
    findings = structural_findings(ROOT, tracked)
    blocking = [f for f in findings if f[1] in SCAN_VERDICT_BY_SEVERITY]
    assert not blocking, (
        f"plugin_guard at {HERMES_REV[:7]} would raise {blocking}; "
        f"`hermes plugins install` no longer just works."
    )
    assert verdict(findings) == UNATTENDED_INSTALL_VERDICT


def test_no_finding_at_all_from_the_structural_scan(tracked):
    """Even non-blocking findings are the tree drifting from what it ships.

    A medium is not refused, but every one of them is build output, an
    oversized file or a broken symlink that has no business in a plugin clone.
    """
    assert structural_findings(ROOT, tracked) == []


def test_a_bundled_binary_would_stop_the_documented_install(tmp_path):
    """Prove the guard bites: `.so` -> binary_file -> high -> caution."""
    (tmp_path / "plugin.yaml").write_text("name: usdctofiat\n", encoding="utf-8")
    (tmp_path / "_vendor.so").write_bytes(b"\x7fELF")

    findings = structural_findings(tmp_path, ["plugin.yaml", "_vendor.so"])
    assert ("binary_file", "high", "_vendor.so") in findings
    assert verdict(findings) == "caution"
    assert verdict(findings) != UNATTENDED_INSTALL_VERDICT


def test_a_symlink_out_of_the_tree_would_be_refused_outright(tmp_path):
    """`--force` does not override a dangerous verdict."""
    tree = tmp_path / "plugin"
    tree.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secrets", encoding="utf-8")
    (tree / "escape").symlink_to(outside)

    findings = structural_findings(tree, ["escape"])
    assert ("symlink_escape", "critical", "escape") in findings
    assert verdict(findings) == "dangerous"


def test_pinned_scan_constants_are_still_meaningful():
    """Catch a hand-edit that made the snapshot vacuous.

    scripts/refresh_hermes_pin.py fails loudly if any of these is missing from
    upstream, and the weekly workflow re-derives the file, so this only covers
    an edit in between.
    """
    assert SCAN_VERDICT_BY_SEVERITY.get("critical") == "dangerous"
    assert SCAN_VERDICT_BY_SEVERITY.get("high") == "caution"
    assert UNATTENDED_INSTALL_VERDICT == "safe"
    assert ".so" in SCAN_BINARY_EXTENSIONS and ".exe" in SCAN_BINARY_EXTENSIONS
    assert ".git" in SCAN_EXCLUDED_DIRS
    assert SCAN_MAX_FILE_COUNT > 0 and SCAN_MAX_SINGLE_FILE_KB > 0
