"""A fault while answering must not be served as the truth about the ground.

The viewer's HTTP layer treats a 404 as an answer: there is nothing here, stop
asking. That is exactly right for ground that was never imaged — most of a live
survey, most of the time — and exactly wrong for a picture that merely could
not answer at this moment: a derive that lost a race, a description briefly
unreadable while another process replaces it, a manifest mid-repair. Serving
those as 404 leaves a hole in the operator's picture that nothing ever comes
back to fill, because the viewer was told, with confidence, that the ground is
empty. The only cure the operator has for such a hole is a reload — the very
symptom a whole diagnostic campaign was spent chasing.

So the server keeps the two answers apart. Genuine absence stays 404. A
failure that a retry may cure is answered 503, which the viewer's own HTTP
layer retries with bounded backoff — no ZMART timer, no invented policy. These
tests hold that seam in place from the outside, over real HTTP: they sabotage
a served run the way a real fault would, watch the status codes, repair the
damage, and check the picture comes back without anyone reloading anything.
"""

from __future__ import annotations

import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "app" / "picture"))

import measure_a_governed_run_at_scale as harness  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from server import make_server  # noqa: E402


def _status_of(url: str) -> int:
    """The HTTP status one request comes back with, errors included."""
    try:
        with urllib.request.urlopen(url, timeout=30) as answer:
            return answer.status
    except urllib.error.HTTPError as told:
        return told.code


def _a_served_piece(shown: Path, name: str, port: int) -> str:
    """The URL of one piece that really exists as a baked file on disk.

    Found by looking, not assumed: which levels are baked and which pieces
    they hold depends on the survey's size and the declaration, and a test
    that guessed a path could quietly test the wrong door. The file door is
    the sharper subject here — a piece whose bytes sit right there on disk,
    and which the server must still refuse to hand over when the manifest
    cannot be consulted.
    """
    for found in sorted(shown.rglob("c/*/*/*")):
        if found.is_file():
            inside = "/".join(found.relative_to(shown).parts)
            return f"http://127.0.0.1:{port}/data/0/{name}/{inside}"
    raise AssertionError(
        "the declared picture holds no baked piece files at all, so there is "
        "nothing to test the governed file door with"
    )


def _serving(tmp_path: Path):
    """One small governed run, declared with a bake and served over HTTP.

    Returns the run, the picture's folder, the server, its thread and its
    port. Every position is committed before the picture is declared, so the
    baseline is a complete, quiet picture — any status change the tests see
    afterwards is caused by their own sabotage and by nothing else.
    """
    harness.FIXTURES = tmp_path
    run, order = harness.the_run(4)
    for position_id in order:
        harness.fast_publish(run, position_id)
    shown = run.folder / "views" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live",
                                       bake=True)
    server = make_server(port=0, data_dir=shown,
                         site_dir=_VIZ / "app" / "page" / "dist",
                         store=[store.name], window=harness.BRIGHT, live=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return run, store, server, thread, server.server_address[1]


def test_a_broken_manifest_answers_try_again_not_absence(tmp_path):
    """While the manifest cannot be read, a piece is 503 — and heals to 200.

    The sabotage is the shape of a real fault: the manifest's committed-state
    file is overwritten with bytes that cannot be parsed, exactly what a
    reader can see mid-replace or after a torn write. The derive then fails,
    and the server must say "try again shortly" rather than "there is nothing
    here" — the baked file for the piece is sitting on disk the whole time,
    which is precisely why handing it over, or denying it exists, would both
    be wrong. Restoring the file must heal the answer with no reload and no
    waiting period, because a fresh derive is attempted on the next ask.
    """
    run, store, server, thread, port = _serving(tmp_path)
    try:
        piece = _a_served_piece(Path(store), store.name, port)
        assert _status_of(piece) == 200, (
            "the baseline must serve before any sabotage means anything"
        )

        truth = Path(run.folder) / "views" / "live" / "metadata" / "signed.json"
        held = truth.read_bytes()
        truth.write_bytes(b"{ this is not json, as a torn write would be")
        try:
            assert _status_of(piece) == 503, (
                "with the manifest unreadable the derive fails, and the "
                "answer must be 'try again shortly' (503) — a 404 here is "
                "believed by the viewer and leaves a hole in the operator's "
                "picture that only a reload would repair, and a 200 from the "
                "baked file would outrun the manifest entirely"
            )
        finally:
            truth.write_bytes(held)

        assert _status_of(piece) == 200, (
            "with the manifest repaired the very next ask derives afresh and "
            "answers the piece — recovery must not need a reload, a restart, "
            "or a waiting period"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_an_unopenable_picture_answers_try_again_until_it_recovers(tmp_path):
    """While the picture cannot be classified, its pieces are 503, not 404.

    The other door to the same mistake: the picture's own description
    (``zarr.json``) is what says the picture is governed at all, and while it
    cannot be read the server cannot know whether a piece file on disk may be
    served. Refusing to answer is right — but the refusal is remembered for a
    couple of seconds (so a broken picture cannot make every request re-read
    the world), and for that remembered moment the answer must still be
    "try again shortly". After the memory expires and the description is back,
    the picture reclassifies itself and serves again, no reload needed.
    """
    _run, store, server, thread, port = _serving(tmp_path)
    try:
        piece = _a_served_piece(Path(store), store.name, port)
        assert _status_of(piece) == 200

        described = Path(store) / "zarr.json"
        held = described.read_bytes()
        described.write_bytes(b"not a description")
        try:
            assert _status_of(piece) == 503, (
                "with the description unreadable the picture cannot be "
                "classified, so nothing may be served from its files — and "
                "the refusal must read as temporary (503), not as absence"
            )
        finally:
            described.write_bytes(held)

        # The failed opening is remembered briefly (see _refused in
        # served.py), so the repaired picture may answer 503 for up to two
        # more seconds. That is the deliberate cost of not re-reading a
        # broken picture on every request. What matters is that the memory
        # expires on its own: keep asking a little past the window and the
        # answer must return to 200 without anyone doing anything.
        deadline = time.monotonic() + 10.0
        answered = None
        while time.monotonic() < deadline:
            answered = _status_of(piece)
            if answered == 200:
                break
            assert answered == 503, (
                f"while recovering, every answer must be 503 or the healed "
                f"200 — a {answered} means the refusal changed meaning"
            )
            time.sleep(0.25)
        assert answered == 200, (
            "the repaired picture never came back within ten seconds — the "
            "timed refusal is supposed to expire and reclassify it"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
