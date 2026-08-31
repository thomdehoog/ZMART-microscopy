"""Sabotage the manifest-refresh invariants and require the focused tests to fail.

This is deliberately separate from the ordinary suite because it edits one real
source file at a time.  Every subject is restored byte-for-byte, even on Ctrl-C or
SIGTERM, and a red mutation counts only after the unmodified test file proved
green.  Run it with::

    python -m zmart_live.tests.check_the_live_refresh_tests_can_fail

The pixel-positive control has a browser companion in
``viz_studio/tests/test_manifest_refresh_browser.py``.  Its black-screen sabotage
requires Chromium and is therefore run with the real-browser campaign described
in ``viz_studio/TESTING.md`` rather than being disguised as a Python-only check.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._fault_check import (
    make_interruptions_reach_finally,
    replace_source,
    require_green_subject,
    require_restored_subject,
    run_pytest,
)

HERE = Path(__file__).resolve()
PACKAGE = HERE.parent.parent
REPO = PACKAGE.parent
VIZ = REPO / "viz_studio"


@dataclass(frozen=True)
class Fault:
    description: str
    source: Path
    tests: Path
    find: str
    replace_with: str


FAULTS = (
    Fault(
        "serve canonical pixels before their manifest commit",
        PACKAGE / "gateway.py",
        HERE.parent / "test_gateway.py",
        "return (position_id, moment, generation) in self._published_units()",
        "return True",
    ),
    Fault(
        "turn gapped committed time into a misleading high-water range",
        PACKAGE / "live_state.py",
        HERE.parent / "test_live_state.py",
        "ordered = sorted(set(moments))",
        "ordered = list(range(max(moments) + 1)) if moments else []",
    ),
    Fault(
        "report a damaged publication marker as current",
        PACKAGE / "live_state.py",
        HERE.parent / "test_live_state.py",
        "self._error = str(why)\n                return False",
        "self._error = None\n                return False",
    ),
    Fault(
        "ignore a stable source's higher committed revision",
        VIZ / "frontend" / "src" / "live-refresh.js",
        VIZ / "tests" / "test_frontend_live_refresh_contract.py",
        "&& now.revision > before;",
        "&& false;",
    ),
    Fault(
        "put the committed revision into the Neuroglancer source URL",
        PACKAGE / "scene.py",
        HERE.parent / "test_scene.py",
        "            url=_the_address_of(store_root, image.path),",
        "            url=_the_address_of(store_root, image.path)"
        ' + f"?revision={_revision_for(image, committed)}",',
    ),
    Fault(
        "globally invalidate a decoded source during a narrow refresh",
        VIZ / "frontend" / "src" / "engine.js",
        VIZ / "tests" / "test_frontend_live_refresh_contract.py",
        "  for (const question of matching.decoded) {",
        "  for (const question of remembered.keys()) {",
    ),
)


def _main() -> int:
    unnoticed: list[str] = []
    baselines: set[tuple[Path, Path]] = set()

    print(f"{'fault introduced':<67}{'caught?':>9}   noticed by")
    print("-" * 112)
    with make_interruptions_reach_finally():
        for fault in FAULTS:
            key = (fault.source, fault.tests)
            if key not in baselines:
                if not require_green_subject(REPO, fault.tests, fault.source):
                    return 2
                baselines.add(key)

            original = fault.source.read_text(encoding="utf-8")
            if fault.find not in original:
                print(
                    f"{fault.description:<67}{'STALE':>9}   source text moved"
                )
                unnoticed.append(fault.description)
                continue
            try:
                replace_source(
                    fault.source,
                    original.replace(fault.find, fault.replace_with, 1),
                )
                result = run_pytest(REPO, fault.tests)
            finally:
                replace_source(fault.source, original)

            if result.caught_the_fault:
                print(
                    f"{fault.description:<67}{'yes':>9}   "
                    f"{result.first_failure[:32]}"
                )
            elif result.could_not_run_tests:
                print(f"{fault.description:<67}{'ERROR':>9}   pytest did not finish")
                print(result.output)
                return 2
            else:
                print(f"{fault.description:<67}{'NO':>9}   nothing noticed")
                unnoticed.append(fault.description)

            if not require_restored_subject(REPO, fault.tests, fault.source, original):
                return 2

    print()
    if unnoticed:
        print("These deliberate faults went unnoticed:")
        for description in unnoticed:
            print(f"  - {description}")
        return 1
    print("Every manifest-refresh sabotage was caught, and every subject was restored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
