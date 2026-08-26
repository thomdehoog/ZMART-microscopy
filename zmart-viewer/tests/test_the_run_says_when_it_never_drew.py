"""Check that a run which never looked at the picture admits it.

About a third of this suite opens a real browser and reads the pixels it drew.
That third is the only part that catches the fault this project keeps meeting: a
picture that is silently absent, with every piece of image fetched, every layer
built, and the engine reporting itself perfectly content. When those tests cannot
run — no browser on the machine, or the viewer page never built — they skip, and
a skipped test is not a failure. The danger is that the run then looks exactly
like one that opened a browser and was satisfied.

So the suite says so at the end, loudly, and on a machine that is supposed to be
able to draw it fails outright. That safeguard is itself worth testing, because a
safeguard nobody has watched work is only a comment.

The way to test it is to run the suite again, inside this one, on a machine made
to look as though it has no browser at all. That is what the helper below does:
it starts a fresh pytest in a separate process, with the environment arranged so
that neither Playwright's own Chromium nor any browser already on the machine can
be found, and then reads what that run said about itself.

These tests take a few seconds each, because starting a second pytest is not
free. They need no browser themselves — which is rather the point.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import conftest

_VIZ_ROOT = Path(__file__).resolve().parent.parent

# One browser test to run in the inner pytest. Any would do — every one of them
# needs a browser, so every one of them skips on a machine that has none. A
# single test is chosen rather than the whole file simply to keep it quick.
_A_TEST_THAT_NEEDS_A_BROWSER = (
    "tests/test_interaction.py::test_the_viewer_opens_as_a_single_panel"
)


def _run_the_suite_with_no_browser(tmp_path: Path, require_browser: bool):
    """Run one browser test in a fresh pytest, on a machine that cannot draw.

    Two settings together make the machine look browser-less, because the suite
    now has two ways to find a browser and both must be closed off for this to be
    an honest test of the safeguard:

    - ``PLAYWRIGHT_BROWSERS_PATH`` points at an empty folder, so Playwright's own
      Chromium is not there.
    - ``ZMART_CHROMIUM`` names a file that does not exist, which is how you tell
      the suite to stop searching for a browser of its own.

    Returns the finished process, so a test can look at both what it printed and
    the exit code it gave.
    """
    empty = tmp_path / "no-browsers-here"
    empty.mkdir(exist_ok=True)

    environment = dict(os.environ)
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(empty)
    environment[conftest.BROWSER_OVERRIDE] = str(tmp_path / "there-is-no-browser-here")
    environment.pop(conftest.REQUIRE_BROWSER, None)
    if require_browser:
        environment[conftest.REQUIRE_BROWSER] = "1"
    # The inner run must not be caught by any plugin that reorders or repeats
    # tests, and must not go looking for a browser to launch of its own accord.
    return subprocess.run(
        [sys.executable, "-m", "pytest", _A_TEST_THAT_NEEDS_A_BROWSER, "-q"],
        cwd=_VIZ_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_a_plain_machine_stays_green_but_is_told_it_drew_nothing(tmp_path):
    """Without the strict setting, the run passes — and still says what it missed.

    This is the everyday case: somebody's laptop with no browser installed. The
    run should not fail, because there is nothing wrong with that machine. But
    the person reading the green needs to know that the questions about the
    picture were not asked, so the banner goes out anyway.
    """
    finished = _run_the_suite_with_no_browser(tmp_path, require_browser=False)
    said = finished.stdout + finished.stderr

    assert finished.returncode == 0, (
        "a machine with no browser should still finish green, since a plain "
        f"checkout is allowed to be missing one. It said:\n{said}"
    )
    assert "NO PICTURE WAS LOOKED AT" in said, (
        "the run drew nothing and did not say so, which is the exact silence "
        f"this safeguard exists to break. It said:\n{said}"
    )
    # Which reason it gives depends on the machine — usually that no Chromium
    # could be started, but on a machine without Playwright at all it is that
    # instead. Either is a proper answer; saying nothing is not.
    assert "no usable Chromium" in said or "playwright is not installed" in said, (
        f"the run should say why it could not draw. It said:\n{said}"
    )


def test_a_machine_that_should_have_drawn_fails_the_run(tmp_path):
    """With ``ZMART_REQUIRE_BROWSER`` set, the same run must fail instead.

    That variable is a promise from whoever set it: this machine can draw. A run
    where the picture was never looked at has broken that promise, and saying so
    quietly is not enough — CI reads exit codes, not banners.
    """
    finished = _run_the_suite_with_no_browser(tmp_path, require_browser=True)
    said = finished.stdout + finished.stderr

    assert finished.returncode != 0, (
        f"{conftest.REQUIRE_BROWSER} was set and no picture was looked at, so this "
        f"run had to fail and did not. It said:\n{said}"
    )
    assert "NO PICTURE WAS LOOKED AT" in said, (
        f"the run failed without explaining itself. It said:\n{said}"
    )
    assert "this run is being failed" in said, (
        "the run should say plainly that it is being failed for having drawn "
        f"nothing. It said:\n{said}"
    )


def test_a_browser_already_on_the_machine_is_found(tmp_path):
    """The search finds a Chromium laid out the way Playwright lays them out.

    This is the half that keeps a capable machine from skipping. Playwright will
    only launch the one exact build it was packaged against; a machine that has a
    perfectly good Chromium of a different build, and no way to download the
    expected one, would otherwise skip every test that looks at the picture.

    The folders are made up here rather than looked for on the real machine, so
    that this test says the same thing everywhere.
    """
    pretend = tmp_path / "browsers"
    for build, contents in (("chromium-1194", b"older"), ("chromium-1208", b"newer")):
        chrome = pretend / build / "chrome-linux" / "chrome"
        chrome.parent.mkdir(parents=True)
        chrome.write_bytes(contents)

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(pretend)
    os.environ.pop(conftest.BROWSER_OVERRIDE, None)
    try:
        found = conftest.find_a_chromium()
    finally:
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

    assert found is not None, "a Chromium was sitting there and was not found"
    assert found.read_bytes() == b"newer", (
        "two builds were present and the older one was chosen; the newest is the "
        f"one most likely to match what the tests expect. Chose: {found}"
    )


def test_being_told_where_the_browser_is_settles_it(tmp_path):
    """``ZMART_CHROMIUM`` overrides the search, and stops it when it names nothing.

    Naming a browser is how somebody rescues a machine the search gets wrong. It
    is also how this file makes a machine look browser-less above, so the second
    half matters just as much: a name that points at nothing means "there is no
    browser", not "go and look for one anyway".
    """
    chosen = tmp_path / "my-own-chrome"
    chosen.write_bytes(b"a browser")

    os.environ[conftest.BROWSER_OVERRIDE] = str(chosen)
    try:
        assert conftest.find_a_chromium() == chosen
        os.environ[conftest.BROWSER_OVERRIDE] = str(tmp_path / "not-here")
        assert conftest.find_a_chromium() is None, (
            "a browser was named that does not exist, and the search carried on "
            "and found another one — which would quietly ignore what it was told"
        )
    finally:
        os.environ.pop(conftest.BROWSER_OVERRIDE, None)
