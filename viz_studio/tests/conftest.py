"""Shared fixtures for the viz-studio tests.

The backend is a set of plain modules under ``backend/`` rather than an
installed package (the tool is launched by path, not imported by consumers), so
tests put that directory on ``sys.path`` the same way ``run_demo.py`` does. The
repository root is included as well because the backend's live-publication gate
is the installed `zmart_live` package in production, while a source-tree test
must be able to exercise it before the editable install has been made.

The browser-driven tests are opt-out rather than opt-in: they run wherever the
page has been built and a Chromium is available, and skip with a clear reason
where it has not. That keeps a bare checkout green while still failing loudly on
a machine that is supposed to be able to render.

Because a silent skip is the dangerous case, two things below work together. The
browser fixture goes looking for a Chromium this machine already has before it
gives up, so that a machine which *could* have drawn does draw. And if the tests
that look at the picture still did not run, the end of the run says so in a
banner that is hard to read past, whether or not anything failed.
"""

from __future__ import annotations

import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

_VIZ_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _VIZ_ROOT / "backend"
_REPO_ROOT = _VIZ_ROOT.parent

# Set this on any machine that is supposed to be able to draw — a CI runner, the
# microscope PC — and the run *fails* if the tests that look at pixels did not run,
# rather than skipping them and reporting a comfortable green.
#
# It exists because the two outcomes are indistinguishable from the outside. About
# a third of this suite opens a real browser and reads the picture it drew, and
# that third is the only part that catches the fault this project keeps meeting: a
# picture that is silently absent, with every piece fetched, every layer built, and
# the engine reporting itself perfectly content. If the browser cannot launch or
# the page was never built, all of those skip, and the run says "passed" — which is
# worse than no run at all, because somebody believes it.
#
# It is opt-in rather than the default so that a plain checkout on somebody's
# laptop still goes green without a browser, which is the promise TESTING.md makes.
REQUIRE_BROWSER = "ZMART_REQUIRE_BROWSER"

# Set this to the Chromium you want the picture tests driven by, if the search
# below picks the wrong one or finds nothing on a machine you know has a browser.
# It is the same variable the shipped render check (`backend/browsercheck.py`)
# already honours, so one setting covers both.
BROWSER_OVERRIDE = "ZMART_CHROMIUM"

# Why the pixel tests could not run, filled in by the fixtures below as they give
# up. Collected rather than raised on the spot because the answer is only wanted
# once, at the end, and because the first fixture to give up is not necessarily the
# most useful thing to report.
_why_the_pixels_were_not_looked_at: list[str] = []

# Every skip that means "nobody looked at the picture" starts with this phrase, so
# that the end-of-run summary can count those tests apart from the other, perfectly
# ordinary skips — a machine with no GPU, or no real acquisition to point at.
PIXELS_NOT_LOOKED_AT = "the picture was not looked at"

# If the fallback search below had to be used, this remembers which browser it
# settled on, so the summary can say which program actually drew the pixels.
_the_browser_we_found: list[str] = []


def _in_a_few_words(exc: Exception) -> str:
    """The first line of what went wrong, for a summary that stays readable.

    Playwright's own failure messages end with a large drawn box advising you to
    download a browser, which is fine on its own but drowns everything else when
    it is repeated for every reason in a summary.
    """
    return str(exc).strip().splitlines()[0].strip()


def _give_up_on_the_picture(reason: str) -> None:
    """Skip a test that needs a drawn picture, and remember why for the summary.

    Always use this rather than ``pytest.skip`` directly for anything that stops
    the picture being looked at. Both halves matter: the test itself is skipped
    (which is right on a machine that simply cannot draw), and the reason is kept
    so that the end of the run can say plainly that nothing was looked at.
    """
    _why_the_pixels_were_not_looked_at.append(reason)
    pytest.skip(f"{PIXELS_NOT_LOOKED_AT}: {reason}")


for source_root in (_REPO_ROOT, _BACKEND):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from demo_data import write_demo_zarr  # noqa: E402
from server import make_server  # noqa: E402

_DIST = _VIZ_ROOT / "frontend" / "dist"


@pytest.fixture(scope="session")
def viz_root() -> Path:
    return _VIZ_ROOT


def _newest_source_change() -> float:
    """When the viewer's own source was last edited."""
    newest = 0.0
    for path in (_VIZ_ROOT / "frontend" / "src").rglob("*"):
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    return newest


@pytest.fixture(scope="session")
def built_dist() -> Path:
    """The built viewer page — and a check that it was built from today's source.

    Every test that opens a browser reads the *built* page, not the source beside
    it, and the built page is not kept in the repository because it is generated.
    So it is entirely possible to edit the viewer, run the tests, and be told
    something confident and completely wrong about code that was never running.

    That is not a hypothetical. It cost this project a session: the tests for
    noticing a tile written into an open store were passing and failing against a
    bundle two days older than the source, and the conclusions drawn from them
    were nonsense in both directions.

    A missing build is a *skip*, because a machine that has never built the page
    has simply not been set up for these tests and there is nothing wrong with it.
    A build older than the source is a **failure**, because that machine is about
    to answer questions about the wrong program.
    """
    if not (_DIST / "index.html").exists():
        _give_up_on_the_picture(
            "the viewer page has not been built, so there was nothing to open "
            "(frontend/dist/index.html is missing). Build it with "
            "`npm --prefix frontend install && npm --prefix frontend run build`"
        )
    built = (_DIST / "index.html").stat().st_mtime
    changed = _newest_source_change()
    if changed > built:
        raise AssertionError(
            "the built viewer page is older than the source it was built from, so "
            "these tests would be measuring a program that is no longer the one in "
            "the repository. Rebuild it first:\n\n"
            "    npm --prefix frontend run build\n\n"
            f"(built {time.strftime('%H:%M:%S', time.localtime(built))}, "
            f"source last changed "
            f"{time.strftime('%H:%M:%S', time.localtime(changed))})"
        )
    return _DIST


@pytest.fixture(scope="session")
def demo_store(tmp_path_factory) -> Path:
    """A demo OME-Zarr volume, generated once for the whole session."""
    store = tmp_path_factory.mktemp("demo_store") / "demo.zarr"
    write_demo_zarr(store)
    return store.parent


@pytest.fixture(scope="session")
def live_server(built_dist: Path, demo_store: Path):
    """The real server, on a free port, serving the built page and the volume."""
    # The selection list is off unless asked for, so the shared test server asks
    # for it: most of these tests are about marking places on the image.
    server = make_server(
        port=0, data_dir=demo_store, site_dir=built_dist, allow_selection=True
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


# Where a Chromium that somebody else installed is likely to be sitting, and what
# the folder inside it is called on each operating system. These are Playwright's
# own layouts: it unpacks each browser into a folder named for the build it came
# from, such as ``chromium-1194``.
_CHROMIUM_INSIDE_A_BUILD_FOLDER = (
    "chrome-linux*/chrome",
    "chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    "chrome-win*/chrome.exe",
)


def _places_browsers_are_kept() -> list[Path]:
    """The folders worth searching for an already-installed Chromium.

    ``PLAYWRIGHT_BROWSERS_PATH`` is where Playwright itself was told to keep
    browsers, which is the setting a lab machine uses to put them somewhere the
    site's software policy allows. ``/opt/pw-browsers`` is where the containers
    this project is developed in keep theirs. The value ``0`` is special to
    Playwright and means "beside the package", which needs no searching.
    """
    folders: list[Path] = []
    told_to_use = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if told_to_use and told_to_use != "0":
        folders.append(Path(told_to_use))
    folders.append(Path("/opt/pw-browsers"))
    return list(dict.fromkeys(folders))


def _build_number(folder: Path) -> int:
    """The build number at the end of a folder name like ``chromium-1194``.

    Used only to prefer the newest of several, and any folder that does not end
    in a number sorts last rather than causing trouble.
    """
    trailing_digits = re.search(r"(\d+)$", folder.name)
    return int(trailing_digits.group(1)) if trailing_digits else -1


def find_a_chromium() -> Path | None:
    """Find a Chromium this machine already has, or return ``None`` if it has none.

    Playwright will only offer the one exact build it was packaged against, and
    refuses to launch anything else — so on a machine that has a perfectly good
    Chromium of a slightly different build, and no way to download the expected
    one, every test that looks at the picture skips and the run reports a
    comfortable green having never drawn a pixel. That is precisely the outcome
    this suite exists to prevent, so before giving up we go and look.

    No build number is written down here on purpose: whichever ones are present
    are found, and the newest is preferred. Set ``ZMART_CHROMIUM`` to a browser
    of your own choosing to skip the search entirely.
    """
    chosen_by_hand = os.environ.get(BROWSER_OVERRIDE, "").strip()
    if chosen_by_hand:
        named = Path(chosen_by_hand)
        return named if named.exists() else None

    candidates: list[Path] = []
    for folder in _places_browsers_are_kept():
        if not folder.is_dir():
            continue
        for build in sorted(folder.glob("chromium-*"), key=_build_number, reverse=True):
            for layout in _CHROMIUM_INSIDE_A_BUILD_FOLDER:
                candidates.extend(sorted(build.glob(layout)))
        # Some machines also leave a plain ``chromium`` pointing at whichever
        # build they want used. It is a weaker hint than a real build folder, so
        # it comes last.
        plain = folder / "chromium"
        if plain.is_file():
            candidates.append(plain)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _launch_chromium(playwright, args: list[str]):
    """Start a Chromium, trying Playwright's own first and this machine's second.

    Playwright's own browser is the right answer wherever it is installed, so it
    is tried first and nothing changes on an ordinary machine. Only if that fails
    do we look for a Chromium the machine already has and launch that instead,
    which is what turns a silent skip into a run that actually draws.

    Returns the running browser. Raises if neither could be started, and the
    caller decides whether that is a skip or a failure.
    """
    try:
        return playwright.chromium.launch(args=args)
    except Exception as playwright_could_not:
        already_here = find_a_chromium()
        if already_here is None:
            raise
        browser = playwright.chromium.launch(
            executable_path=str(already_here), args=args
        )
        # Worth saying out loud at the end of the run: the pixels were drawn by a
        # browser other than the one Playwright expected, which is useful to know
        # if anything about the picture later looks unfamiliar.
        note = (
            "Playwright's own Chromium could not be started "
            f"({_in_a_few_words(playwright_could_not)}), so the picture tests used the "
            f"Chromium already on this machine, at {already_here}."
        )
        if note not in _the_browser_we_found:
            _the_browser_we_found.append(note)
        return browser


@pytest.fixture(scope="session")
def _playwright():
    """One Playwright instance for the whole session.

    Playwright's sync API allows only one live context per thread, so every
    browser the tests launch must come from this single instance rather than
    each opening its own — otherwise a second launch fails with an asyncio-loop
    error. Skips (rather than errors) where playwright is not installed.
    """
    try:
        import playwright.sync_api as pw_api
    except ImportError:
        _give_up_on_the_picture(
            "playwright is not installed, so no browser could be driven "
            "(install it with `pip install playwright`)"
        )
    with pw_api.sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(_playwright):
    """A headless Chromium with software GL, or skip if none is usable.

    Software GL is the default because neuroglancer needs WebGL2 and CI
    machines have no GPU. On a machine that HAS one — the workstation pass —
    set ``ZMART_REAL_GPU=1`` and the same fixture launches against the real
    graphics stack instead, so every browser gate measures the hardware the
    operator will actually use. Without the variable, a workstation would
    silently run the gates on software rendering and call it a GPU pass.

    A machine whose policy blocks the downloaded browser fails at launch
    rather than at import, so both are treated as "cannot run here" — but
    only after we have looked for a Chromium the machine already has.
    """
    if os.environ.get("ZMART_REAL_GPU"):
        gl_args = ["--ignore-gpu-blocklist", "--enable-gpu"]
    else:
        gl_args = ["--use-gl=angle", "--use-angle=swiftshader",
                   "--ignore-gpu-blocklist"]
    try:
        launched = _launch_chromium(_playwright, gl_args)
    except Exception as exc:
        _give_up_on_the_picture(
            f"no usable Chromium on this machine: {_in_a_few_words(exc)}"
        )
    try:
        yield launched
    finally:
        launched.close()


@pytest.fixture(scope="session")
def gpu_browser(_playwright):
    """A Chromium left to use the machine's real graphics stack, not forced to
    software — so a test can tell whether a GPU is actually present. Shares the
    one session Playwright instance with ``browser`` to avoid a second context.
    """
    args = ["--ignore-gpu-blocklist", "--enable-gpu"]
    try:
        launched = _launch_chromium(_playwright, args)
    except Exception as exc:
        _give_up_on_the_picture(
            f"no usable Chromium on this machine: {_in_a_few_words(exc)}"
        )
    try:
        yield launched
    finally:
        launched.close()


@pytest.fixture
def viewer_page(browser, live_server: str, demo_store: Path):
    """A page with the viewer booted and the demo volume fully rendered.

    The saved targets are cleared first. Every test here shares one demo volume,
    and targets are saved to a file beside it a moment after they change — so a
    target drawn at the end of one test can be written after its page has closed
    and still be sitting there when the next one opens. Starting from a known
    empty list keeps each test honest about what it drew itself.
    """
    sidecar = demo_store / "zmart-annotations.json"
    if sidecar.exists():
        sidecar.unlink()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    page.goto(live_server, wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30_000)
    page.wait_for_function(
        """() => {
          const v = window.zmartViewer;
          let needed = 0, available = 0;
          for (const managed of v.layerManager.managedLayers) {
            for (const rl of (managed.layer && managed.layer.renderLayers) || []) {
              const p = rl.layerChunkProgressInfo;
              if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
            }
          }
          return available > 0 && available >= needed;
        }""",
        timeout=60_000,
    )
    try:
        yield page
    finally:
        page.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# How many tests were skipped because nobody looked at the picture, as opposed to
# the ordinary skips this suite also has — no GPU on this machine, no real
# acquisition to point at. Counted so the summary can give a number rather than a
# vague warning, because "forty-one tests" lands where "some tests" does not.
_pixel_tests_skipped = 0


def pytest_runtest_logreport(report):
    """Count the tests that skipped because the picture was never looked at."""
    global _pixel_tests_skipped
    if report.skipped and PIXELS_NOT_LOOKED_AT in str(report.longrepr):
        _pixel_tests_skipped += 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Say loudly, at the end of every run, if nobody looked at the picture.

    This is the part that matters most on an ordinary developer's machine, where
    ``ZMART_REQUIRE_BROWSER`` is not set and so nothing fails. The run is still
    green, and it should be — a laptop without Node or a browser has simply not
    been set up for this, and there is nothing wrong with it. But the person
    reading that green needs to know which questions it answered and which it did
    not, because "the viewer draws the picture correctly" is not among them.

    So the banner goes out whether or not anything failed, and it says how many
    tests did not run, why, and what to do about it.
    """
    if _the_browser_we_found and not _why_the_pixels_were_not_looked_at:
        for note in _the_browser_we_found:
            terminalreporter.write_line(note, yellow=True)
    if not _why_the_pixels_were_not_looked_at:
        return

    required = bool(os.environ.get(REQUIRE_BROWSER))
    terminalreporter.write_sep("=", "NO PICTURE WAS LOOKED AT", red=True, bold=True)
    if _pixel_tests_skipped:
        terminalreporter.write_line(
            f"{_pixel_tests_skipped} tests that open a real browser and read the "
            "pixels it drew were skipped."
        )
    terminalreporter.write_line("Why:")
    for why in dict.fromkeys(_why_the_pixels_were_not_looked_at):
        terminalreporter.write_line(f"  - {why}")
    terminalreporter.write_line(
        "\nThose tests are the only part of this suite that catches the fault this "
        "project keeps meeting: a picture that is silently absent, with every piece "
        "of image fetched, every layer built, and the engine reporting itself "
        "perfectly content. Without them the run says nothing at all about whether "
        "the viewer still draws."
    )
    if required:
        terminalreporter.write_line(
            f"\n{REQUIRE_BROWSER} is set, so this machine is supposed to be able to "
            "draw and this run is being failed. Put right whatever is listed above, "
            f"or unset {REQUIRE_BROWSER} if this machine genuinely cannot draw.",
            red=True,
            bold=True,
        )
    else:
        terminalreporter.write_line(
            f"\nThis run is not failed for it, because {REQUIRE_BROWSER} is not set "
            "and a plain checkout is allowed to be missing a browser. Set that "
            "variable on any machine that is supposed to draw — a CI runner, the "
            "microscope PC — and a run like this one fails instead.",
            yellow=True,
        )
    terminalreporter.write_sep("=", red=True, bold=True)


def pytest_sessionfinish(session, exitstatus):
    """Fail a run that never looked at a picture, where it was supposed to.

    A skipped test is not a failure, and on a bare checkout that is exactly right —
    somebody without Node or a browser has simply not set that part up, and there is
    nothing wrong with their machine. But on a machine that *is* meant to draw, the
    same skip is the suite quietly stopping doing the one thing it is here for, and
    it reports the same comfortable green either way.

    So where ``ZMART_REQUIRE_BROWSER`` is set, "the pixel tests did not run" ends the
    run as a failure. The explanation has already been printed by the summary above;
    this only settles the exit code. Decided here rather than in a test of its own
    because the question is only answerable once everything has been tried: a browser
    that launches and then dies halfway through is worth catching too, and no check
    made at the start would see it.
    """
    if not os.environ.get(REQUIRE_BROWSER):
        return
    if not _why_the_pixels_were_not_looked_at:
        return
    # 1 is pytest's own code for "tests failed", which is what this is: the suite
    # did not do what this machine promised it would.
    session.exitstatus = 1
