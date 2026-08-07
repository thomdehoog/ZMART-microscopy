"""The built page must ship real worker files, not neuroglancer's source stubs.

neuroglancer hands its two background workers to the bundler as tiny stubs full
of ``#src/...`` imports that only a bundler can resolve. If the build copies a
stub through instead of compiling it, the browser cannot load the worker, no
image chunk is ever decoded, and the viewer shows a correct-looking outline over
flat grey. That regression is invisible to anything that only checks the page
loads, so it is asserted here on the artifacts themselves — cheaply, with no
browser.
"""

from __future__ import annotations

import pytest

_STUB_MARKER = "#src/"
_MIN_WORKER_BYTES = 100_000


def worker_files(built_dist):
    """The two compiled workers, wherever the build placed them."""
    chunk = list(built_dist.glob("**/chunk_worker.bundle*.js"))
    asynchronous = list(built_dist.glob("**/async_computation.bundle*.js"))
    assert chunk, "no chunk_worker bundle in the build output"
    assert asynchronous, "no async_computation bundle in the build output"
    return chunk[0], asynchronous[0]


def test_index_html_is_emitted(built_dist):
    assert (built_dist / "index.html").is_file()


def test_workers_are_emitted_as_real_files(built_dist):
    for worker in worker_files(built_dist):
        assert worker.stat().st_size > _MIN_WORKER_BYTES, (
            f"{worker.name} is {worker.stat().st_size} bytes — too small to be compiled"
        )


def test_workers_are_compiled_not_raw_stubs(built_dist):
    """A stub still containing `#src/` imports cannot load in a browser."""
    for worker in worker_files(built_dist):
        head = worker.read_text(encoding="utf-8", errors="replace")[:4000]
        assert _STUB_MARKER not in head, f"{worker.name} looks like an uncompiled stub"


def test_async_worker_sits_where_the_page_asks_for_it(built_dist):
    """The copy step places it at the dist root; a miss here is a 404 at runtime."""
    assert (built_dist / "async_computation.bundle.js").is_file()


@pytest.mark.parametrize("asset", ["index.html"])
def test_page_references_its_bundle(built_dist, asset):
    html = (built_dist / asset).read_text(encoding="utf-8")
    assert "assets/" in html, "built page does not reference its own assets"
