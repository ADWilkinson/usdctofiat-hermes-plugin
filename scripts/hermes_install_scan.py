#!/usr/bin/env python3
"""Run Hermes' real install-time security scanner against this plugin.

``hermes plugins install`` clones a repo and scans it with
``tools/plugin_guard.py`` before copying anything into place. A ``caution``
verdict refuses the install unless the caller passes ``--force`` or answers a
prompt, and ``dangerous`` refuses it outright -- so the scan is a gate on the
one-line install the README documents, not an advisory.

``tests/test_install_scan.py`` re-implements the scanner's *structural* half
offline against the pinned constants, which is the half this repo's tree can
trip. Its *content* half is ~1200 lines of threat regexes; the honest way to
check those is to run the real thing, which is what this does. It reads two
files from the pinned Hermes revision and executes them over a ``git archive``
of the tracked tree -- the same content a fresh clone would hold.

Network-bound and therefore not a required check, for the reason spelled out in
.github/workflows/hermes-pin.yml: GitHub answers repeated content reads of a
repo you do not own with 429, and an unrelated throttle must not turn a required
check red. The weekly hermes-pin workflow runs it beside the snapshot re-derive.

    python scripts/hermes_install_scan.py

Exits non-zero when the tracked tree would not install unprompted.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_hermes_pin import HERMES_REPO, ROOT, current_rev, fetch  # noqa: E402

sys.path.insert(0, str(ROOT))

from tests.hermes_pinned import (  # noqa: E402
    PLUGIN_SCANNER_VERSION,
    UNATTENDED_INSTALL_VERDICT,
)

# ``plugin_guard`` imports from ``skills_guard`` by absolute ``tools.`` path, so
# both have to land in a package of that name. Both are stdlib-only, so nothing
# else from Hermes is needed.
GUARD_MODULES = {
    "tools.skills_guard": "tools/skills_guard.py",
    "tools.plugin_guard": "tools/plugin_guard.py",
}


def load_guard(rev, workdir):
    """Import the pinned scanner as a ``tools`` package rooted at *workdir*."""
    workdir.mkdir(parents=True, exist_ok=True)
    package = types.ModuleType("tools")
    package.__path__ = [str(workdir)]
    sys.modules["tools"] = package

    for module_name, path in GUARD_MODULES.items():
        source = workdir / f"{module_name.split('.')[-1]}.py"
        source.write_text(fetch(path, rev), encoding="utf-8")
        spec = importlib.util.spec_from_file_location(module_name, source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

    return sys.modules["tools.plugin_guard"]


def export_tracked_tree(destination):
    """Materialise the tracked tree, which is what a fresh clone would hold."""
    destination.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(destination)], input=archive, check=True)
    return destination


def main():
    rev = current_rev()
    print(f"scanning with {HERMES_REPO}@{rev[:7]} plugin_guard", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        guard = load_guard(rev, tmp / "tools")
        tree = export_tracked_tree(tmp / "clone")

        if guard.PLUGIN_SCANNER_VERSION != PLUGIN_SCANNER_VERSION:
            raise SystemExit(
                f"pinned scanner is {PLUGIN_SCANNER_VERSION}, upstream now reports "
                f"{guard.PLUGIN_SCANNER_VERSION}; re-run scripts/refresh_hermes_pin.py "
                "and re-verify the isolated install before repinning."
            )

        result = guard.scan_plugin(tree, source="ADWilkinson/usdctofiat-hermes-plugin")
        allowed, reason = guard.should_allow_plugin_install(result, force=False)
        print(guard.format_scan_report(result))

    if allowed is not True or result.verdict != UNATTENDED_INSTALL_VERDICT:
        raise SystemExit(
            f"\n`hermes plugins install ADWilkinson/usdctofiat-hermes-plugin` would not "
            f"install unprompted: verdict {result.verdict!r}, {reason}.\n"
            "The README documents that command with no --force and no prompt."
        )

    print(f"\nverdict {result.verdict!r}: {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
