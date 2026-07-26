"""The layer panel, organised the way an experiment is.

A run produces several acquisition types, each holding channels. The panel shows
them that way: a named group per acquisition type, with its channels as rows
underneath. These tests drive that in a real browser against synthetic OME-Zarr
stores of exactly the shape a run writes.

The point worth checking hardest is that a store holding several channels *inside*
one array yields one row per channel. Before this existed, such a store produced a
single row showing a single channel, and the others were not merely uncoloured —
they were unreachable, with nothing in the interface hinting they were there.
"""

from __future__ import annotations

import threading

import pytest
from demo_data import write_demo_zarr
from server import make_server


@pytest.fixture(scope="module")
def run_folder(tmp_path_factory):
    """A folder shaped like one experiment's output: two acquisition types."""
    root = tmp_path_factory.mktemp("run")
    # Each is a t,c,z,y,x store with three named, coloured channels inside it.
    write_demo_zarr(root / "overview.ome.zarr", timepoints=2)
    write_demo_zarr(root / "targetscan_cell042.ome.zarr", seed=3)
    return root


@pytest.fixture(scope="module")
def grouped_page(browser, built_dist, run_folder):
    server = make_server(
        port=0,
        data_dir=run_folder,
        site_dir=built_dist,
        store=["overview.ome.zarr", "targetscan_cell042.ome.zarr"],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_function(
            "() => window.zmartViewer?.layerManager.managedLayers.length >= 6",
            timeout=30_000,
        )
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _image_layers(page):
    return page.evaluate(
        """() => window.zmartViewer.layerManager.managedLayers
             .filter((m) => m.layer?.type === 'image')
             .map((m) => ({
               name: m.name,
               // Visibility belongs to the managed layer that wraps the image,
               // not to the image layer itself -- reading the wrong one of the
               // two reports everything as visible whatever the panel says.
               visible: m.visible,
               opacity: m.layer.opacity?.value ?? null,
               localPos: m.layer.localPosition?.value
                 ? Array.from(m.layer.localPosition.value) : null,
               sources: m.layer.dataSources?.length ?? null,
             }))"""
    )


class TestEveryChannelBecomesARow:
    """Channels inside one store must each get their own row, not be hidden."""

    def test_each_acquisition_type_is_a_named_group(self, grouped_page):
        assert grouped_page.get_by_label("toggle group overview").is_visible()
        assert grouped_page.get_by_label("toggle group targetscan").is_visible()

    def test_all_three_channels_of_each_store_appear(self, grouped_page):
        config = grouped_page.evaluate("() => window.zmartConfig")
        overview = [row for row in config["layers"] if row["group"] == "overview"]
        assert [row["name"] for row in overview] == ["structure", "marker-a", "marker-b"]
        # The engine really is given one layer per channel, not one per store.
        assert len(_image_layers(grouped_page)) == 6

    def test_each_row_is_pinned_to_its_own_channel(self, grouped_page):
        """This is what makes them different pictures rather than six copies."""
        pinned = [layer["localPos"] for layer in _image_layers(grouped_page)]
        assert pinned == [[0], [1], [2], [0], [1], [2]]

    def test_channels_carry_the_colours_the_store_declared(self, grouped_page):
        config = grouped_page.evaluate("() => window.zmartConfig")
        overview = [row for row in config["layers"] if row["group"] == "overview"]
        assert overview[0]["color"] == [1.0, 1.0, 1.0]        # structure, white
        assert overview[1]["color"] == pytest.approx([0.0, 1.0, 0.4], abs=0.01)
        assert overview[2]["color"] == pytest.approx([1.0, 0.2, 1.0], abs=0.01)

    def test_the_engine_gets_unique_layer_names(self, grouped_page):
        """Both acquisition types have a 'marker-a', and the engine needs them apart."""
        names = [layer["name"] for layer in _image_layers(grouped_page)]
        assert len(names) == len(set(names))
        assert "overview · marker-a" in names
        assert "targetscan · marker-a" in names


class TestGroupControls:
    """A whole acquisition type can be hidden or dimmed in one action."""

    def test_hiding_a_group_hides_its_channels(self, grouped_page):
        grouped_page.get_by_label("toggle group targetscan").click()
        grouped_page.wait_for_function(
            """() => window.zmartViewer.layerManager.managedLayers
                 .filter((m) => m.name.startsWith('targetscan'))
                 .every((m) => m.visible === false)""",
            timeout=10_000,
        )
        # The other acquisition type is untouched.
        assert all(
            layer["visible"]
            for layer in _image_layers(grouped_page)
            if layer["name"].startswith("overview")
        )
        grouped_page.get_by_label("toggle group targetscan").click()

    def test_group_opacity_multiplies_into_each_channel(self, grouped_page):
        """Dimming the group dims everything in it, keeping relative weights."""
        before = {
            layer["name"]: layer["opacity"]
            for layer in _image_layers(grouped_page)
            if layer["name"].startswith("overview")
        }
        grouped_page.evaluate(
            """() => {
              const el = document.querySelector("[aria-label='opacity group overview']");
              const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
              setter.call(el, '0.5');
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
            }"""
        )
        grouped_page.wait_for_function(
            """() => window.zmartViewer.layerManager.managedLayers
                 .filter((m) => m.name.startsWith('overview'))
                 .every((m) => Math.abs((m.layer.opacity?.value ?? 1) - 0.5) < 0.01)""",
            timeout=10_000,
        )
        after = {
            layer["name"]: layer["opacity"]
            for layer in _image_layers(grouped_page)
            if layer["name"].startswith("overview")
        }
        assert all(after[name] < before[name] for name in before)
        # And the other acquisition type is unaffected.
        assert all(
            layer["opacity"] == pytest.approx(1.0)
            for layer in _image_layers(grouped_page)
            if layer["name"].startswith("targetscan")
        )

    def test_a_group_can_be_collapsed_without_hiding_the_image(self, grouped_page):
        grouped_page.get_by_label("collapse overview").click()
        grouped_page.wait_for_timeout(300)
        # Collapsing tidies the panel; it must not change what is drawn.
        assert any(
            layer["visible"]
            for layer in _image_layers(grouped_page)
            if layer["name"].startswith("overview")
        )
        grouped_page.get_by_label("expand overview").click()


class TestChannelControlsStillWork:
    """Grouping must not have cost the per-channel controls."""

    def test_one_channel_can_be_hidden_on_its_own(self, grouped_page):
        grouped_page.get_by_label("toggle marker-b").first.click()
        grouped_page.wait_for_timeout(600)
        hidden = [
            layer for layer in _image_layers(grouped_page) if layer["visible"] is False
        ]
        assert hidden, "expected one channel to be hidden"
        grouped_page.get_by_label("toggle marker-b").first.click()

    def test_each_channel_still_has_its_own_contrast_and_opacity(self, grouped_page):
        assert grouped_page.get_by_label("black structure").first.is_visible()
        assert grouped_page.get_by_label("white structure").first.is_visible()
        assert grouped_page.get_by_label("opacity structure").first.is_visible()


def test_a_store_with_one_channel_still_shows_as_one_row(browser, built_dist, tmp_path_factory):
    """The mesoSPIM shape — one store per tile and channel — must keep working."""
    import json

    import numpy as np
    import zarr

    root = tmp_path_factory.mktemp("per_channel")
    for name in ("Mag5_Tile0_Ch488.ome.zarr", "Mag5_Tile0_Ch647.ome.zarr"):
        store = root / name
        group = zarr.open_group(str(store), mode="w", zarr_format=2)
        data = np.full((8, 64, 64), 3000, dtype=np.uint16)
        group.create_array("0", shape=data.shape, chunks=(1, 64, 64), dtype="uint16")[:] = data
        (store / ".zattrs").write_text(
            json.dumps(
                {
                    "multiscales": [
                        {
                            "version": "0.4",
                            "axes": [{"name": a} for a in ("z", "y", "x")],
                            "datasets": [
                                {
                                    "path": "0",
                                    "coordinateTransformations": [
                                        {"type": "scale", "scale": [2.0, 0.35, 0.35]}
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    server = make_server(
        port=0,
        data_dir=root,
        site_dir=built_dist,
        store=["Mag5_Tile0_Ch488.ome.zarr", "Mag5_Tile0_Ch647.ome.zarr"],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        config = page.evaluate("() => window.zmartConfig")
        # No channel axis inside, so one row each, named and coloured as before.
        assert len(config["layers"]) == 2
        assert [row["name"] for row in config["layers"]] == ["Tile0_Ch488", "Tile0_Ch647"]
        assert all(row["channelIndex"] is None for row in config["layers"])
        # Both share one acquisition type, so they gather under one group.
        assert config["groups"] == ["Mag5"]
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
