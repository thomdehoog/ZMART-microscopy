"""Naming a target, and being told whether it saved.

Two small pieces of polish that matter more than they look. A target you can name
is one you can still recognise a week later; and a save that silently failed
looks exactly like one that worked, right up until the acquisition is reopened
and the targets are gone. Both are checked here in a real browser.
"""

from __future__ import annotations

import json
import threading

import pytest
from server import make_server


def add_box(page, annotation_id="detail-box"):
    """Place a box through Neuroglancer's own annotation source, as the tools do."""
    page.evaluate(
        """(id) => {
          const source = window.zmartAnnotationSource;
          const reference = source.add({
            id,
            type: 2,
            description: "",
            pointA: new Float32Array([2, 3, 4]),
            pointB: new Float32Array([8, 9, 10]),
            properties: [],
          }, true);
          reference.dispose();
        }""",
        annotation_id,
    )


def _described(page, annotation_id):
    """What the engine itself now holds as that annotation's description."""
    return page.evaluate(
        "(id) => window.zmartAnnotationSource.get(id)?.description",
        annotation_id,
    )


@pytest.fixture
def details_page(browser, built_dist, tmp_path_factory):
    """A viewer over a store of its own, one fresh copy per test.

    These tests are about saving, so they must not share a store with anything
    else. Saving happens on a short delay after each change, which means a target
    deleted at the very end of a test can still be written to the file
    afterwards — harmless on its own, but it would leave a stray target behind for
    whatever ran next. Its own directory makes that impossible to matter.
    """
    from demo_data import write_demo_zarr

    root = tmp_path_factory.mktemp("details")
    write_demo_zarr(root / "demo.zarr")
    server = make_server(port=0, data_dir=root, site_dir=built_dist, store="demo.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartAnnotationSource !== undefined", timeout=30_000)
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


class TestNamingATarget:
    """The name has to land in Neuroglancer's annotation, not beside it."""

    def test_typing_a_name_reaches_the_annotation_layer(self, details_page):
        add_box(details_page, "named-box")
        field = details_page.get_by_label("description for target 1")
        field.wait_for()
        field.fill("ventricle, double-positive")
        details_page.wait_for_function(
            "() => window.zmartAnnotationSource.get('named-box')?.description "
            "=== 'ventricle, double-positive'",
            timeout=10_000,
        )
        assert _described(details_page, "named-box") == "ventricle, double-positive"
        details_page.get_by_label("delete target 1").click()

    def test_the_name_is_saved_to_the_sidecar(self, details_page):
        """Persistence goes through the same route as everything else drawn."""
        saved = []
        details_page.on(
            "request",
            lambda request: saved.append(request.post_data)
            if request.url.endswith("/api/annotations") and request.method == "POST"
            else None,
        )
        add_box(details_page, "saved-name")
        details_page.get_by_label("description for target 1").fill("keep me")
        details_page.wait_for_timeout(600)
        assert saved, "expected the panel to save after a change"
        document = json.loads(saved[-1])
        descriptions = [a.get("description") for a in document["annotations"]]
        assert "keep me" in descriptions
        details_page.get_by_label("delete target 1").click()

    def test_an_empty_name_is_allowed(self, details_page):
        """Clearing a name must not be mistaken for an error."""
        add_box(details_page, "cleared-name")
        field = details_page.get_by_label("description for target 1")
        field.fill("temporary")
        details_page.wait_for_function(
            "() => window.zmartAnnotationSource.get('cleared-name')?.description === 'temporary'",
            timeout=10_000,
        )
        field.fill("")
        details_page.wait_for_function(
            "() => window.zmartAnnotationSource.get('cleared-name')?.description === ''",
            timeout=10_000,
        )
        details_page.get_by_label("delete target 1").click()


class TestSaveStatus:
    """The panel must say what happened, in both directions."""

    def test_a_successful_save_is_reported(self, details_page):
        add_box(details_page, "status-box")
        details_page.get_by_text("Saved beside the image.").wait_for(timeout=10_000)
        details_page.get_by_label("delete target 1").click()


@pytest.fixture(scope="module")
def unsavable_page(browser, built_dist, tmp_path_factory):
    """The viewer over a store whose sidecar cannot possibly be written.

    Saves fail in real life for ordinary reasons — a transfer mounted read-only, a
    share the operator has no permission on, a full disk. Any of those would do
    here, but file permissions are not a reliable way to arrange one in a test
    (the administrator account most lab machines run as ignores them). So the
    failure is arranged structurally instead: a *directory* is put exactly where
    the sidecar file belongs, and the save cannot replace a directory with a file
    no matter who is running.
    """
    from demo_data import write_demo_zarr

    root = tmp_path_factory.mktemp("unsavable")
    write_demo_zarr(root / "demo.zarr")
    (root / "zmart-annotations.json").mkdir()

    server = make_server(port=0, data_dir=root, site_dir=built_dist, store="demo.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartAnnotationSource !== undefined", timeout=30_000)
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_failed_save_is_shown_not_swallowed(unsavable_page):
    """The one that matters: an unsaved list must not look like a saved one."""
    add_box(unsavable_page, "unsavable")
    unsavable_page.get_by_text("Not saved:", exact=False).wait_for(timeout=15_000)
