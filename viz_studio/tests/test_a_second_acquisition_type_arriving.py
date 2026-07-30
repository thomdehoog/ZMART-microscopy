"""A second kind of scan landing in a folder the viewer is already watching.

This is the ordinary shape of a smart-microscopy run. The microscope images an
overview of the specimen, something in it is worth a closer look, and a target
scan of that place is written into the same folder — at a much finer voxel size,
because that is what "closer look" means. The viewer is watching the folder while
all of this happens, so it meets the target scan on its own, with nobody at the
keyboard to be asked about it.

The two are not one picture and must not be shown as one. An overview at five
micrometres to a voxel and a target scan at a third of one, merged into a single
row, would share a single set of controls: no heading of its own for the target
scan, no eye to hide the overview and look at it, one brightness taken from
whichever arrived first, and closing either one closing both. The operator would
not even be able to tell that the target scan was open.

So the newcomer is opened as a dataset of its own, and the tests below are in two
halves. The first half is that this happens and that it is visible in the panel.
The second half is the ordinary case, which is far more common and must not be
disturbed: another position, or another channel, of the acquisition already open
still joins it and still makes one picture.
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
import zarr
from library import Library
from server import group_labels, make_server

_VIZ_ROOT = Path(__file__).resolve().parent.parent
if str(_VIZ_ROOT) not in sys.path:
    # run_demo.py is the command an operator types, and one of the tests below is
    # about what it prints. It sits beside the viewer rather than inside the
    # backend, so it needs its own entry on the import path.
    sys.path.insert(0, str(_VIZ_ROOT))

# How coarse an overview is, and how fine a target scan of something found in it
# is, in micrometres. These are the figures from a real run, and the only thing
# that matters about them here is that they are not the same: the voxel size is
# what says two stores are different acquisitions, because it is the magnification
# the microscope actually used and cannot be anything else.
OVERVIEW_VOXEL = (5.0, 2.0, 2.0)
TARGET_SCAN_VOXEL = (1.0, 0.3, 0.3)


def _store(
    path: Path,
    *,
    voxel=OVERVIEW_VOXEL,
    brightness=2000,
    axes=("z", "y", "x"),
    channels=None,
):
    """A small but real OME-Zarr store, written the way a run writes one.

    ``voxel`` is what makes it one acquisition or another, and ``brightness`` fills
    it with a single value so that a row measured from this store can be told from a
    row measured from a different one.
    """
    path.mkdir(parents=True)
    shape = tuple(4 if name in "tcz" else 32 for name in axes)
    chunks = tuple(1 if name in "tcz" else 32 for name in axes)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    array = group.create_array("0", shape=shape, chunks=chunks, dtype="uint16")
    array[:] = np.full(shape, brightness, dtype=np.uint16)
    described = {
        "multiscales": [
            {
                "version": "0.4",
                "axes": [{"name": name} for name in axes],
                "datasets": [
                    {
                        "path": "0",
                        "coordinateTransformations": [
                            # The voxel size has one number per axis, so a store with
                            # a channel axis needs a number for that axis too. It says
                            # nothing about magnification and is ignored when two
                            # stores are compared.
                            {"type": "scale", "scale": [1.0] * (len(axes) - 3) + list(voxel)}
                        ],
                    }
                ],
            }
        ]
    }
    if channels:
        described["omero"] = {"channels": [{"label": name} for name in channels]}
    (path / ".zattrs").write_text(json.dumps(described), encoding="utf-8")
    return path


def _store_without_a_voxel_size(path: Path):
    """A store that is readable but says nothing about how large its voxels are.

    Instruments in the wild leave these behind, and a store that has not said
    cannot be argued with, so it must never be split off on suspicion.
    """
    path.mkdir(parents=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    array = group.create_array("0", shape=(4, 32, 32), chunks=(1, 32, 32), dtype="uint16")
    array[:] = np.full((4, 32, 32), 2000, dtype=np.uint16)
    (path / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": name} for name in ("z", "y", "x")],
                        "datasets": [{"path": "0"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _by_dataset(library: Library) -> dict[int, list[str]]:
    """What is open, gathered under the dataset each store belongs to.

    This is the shape the question is really about: not "which stores are open"
    but "how many pictures does the viewer think it has, and which stores make up
    each one". A merge and a split look identical in a flat list of names.
    """
    gathered: dict[int, list[str]] = {}
    for number, _root, name in library.entries():
        gathered.setdefault(number, []).append(name)
    return gathered


@pytest.fixture
def a_run_being_watched(tmp_path):
    """An overview being written, opened and watched, one position in so far."""
    folder = tmp_path / "run_2026-07-29"
    _store(folder / "overview_pos001.ome.zarr")
    library = Library()
    library.open(folder)
    return library, folder


class TestASecondAcquisitionArrivesDuringTheRun:
    """It becomes a picture of its own, and the operator can see that it has."""

    def test_it_does_not_disappear_into_the_acquisition_already_open(self, a_run_being_watched):
        """The defect this file exists for: it used to be swallowed silently.

        Three overview positions and a target scan became one dataset of four
        stores, so the target scan had no heading, no row and no eye of its own —
        the operator could not tell it was open at all, and closing the overview
        closed it too.
        """
        library, folder = a_run_being_watched
        _store(folder / "overview_pos002.ome.zarr")
        _store(folder / "targetscan_cell001.ome.zarr", voxel=TARGET_SCAN_VOXEL)

        open_now = _by_dataset(library)
        assert len(open_now) == 2, (
            "the target scan and the overview were shown as one picture: "
            f"{open_now}"
        )
        overview, target = (sorted(names) for names in open_now.values())
        assert overview == ["overview_pos001.ome.zarr", "overview_pos002.ome.zarr"]
        assert target == ["targetscan_cell001.ome.zarr"]

    def test_it_is_named_after_the_kind_of_scan_it_is(self, a_run_being_watched):
        """The heading has to mean something to the person reading it.

        A run names its outputs after the scan and then the position, so
        ``targetscan_cell001`` is a target scan and the panel can say so.
        """
        library, folder = a_run_being_watched
        _store(folder / "targetscan_cell001.ome.zarr", voxel=TARGET_SCAN_VOXEL)
        library.entries()

        named = [dataset.name for dataset in library.datasets()]
        assert named == ["run_2026-07-29", "targetscan"], named

    def test_the_panel_shows_it_under_a_heading_of_its_own(self, a_run_being_watched):
        """Two headings, distinct, which is how the operator can tell it is open.

        This is the observable half. A dataset the operator cannot see is no better
        than one that was never opened, and the heading is what the panel puts the
        eye and the close button beside.
        """
        library, folder = a_run_being_watched
        _store(folder / "targetscan_cell001.ome.zarr", voxel=TARGET_SCAN_VOXEL)
        library.entries()

        headings = list(group_labels(library.datasets()).values())
        assert len(headings) == 2, f"only one heading, so only one picture: {headings}"
        assert len(set(headings)) == 2, (
            f"two headings reading the same thing cannot be told apart: {headings}"
        )

    def test_hiding_or_closing_one_leaves_the_other_alone(self, a_run_being_watched):
        """Two pictures mean two of everything, including the close button."""
        library, folder = a_run_being_watched
        _store(folder / "targetscan_cell001.ome.zarr", voxel=TARGET_SCAN_VOXEL)
        library.entries()

        library.close_group("targetscan")
        left = [name for _, _, name in library.entries()]
        assert left == ["overview_pos001.ome.zarr"], (
            f"closing the target scan should leave the overview: {left}"
        )

    def test_closing_it_keeps_it_closed_while_the_folder_is_still_watched(
        self, a_run_being_watched
    ):
        """Otherwise the close button would undo itself a second later.

        The overview goes on being watched after the target scan is closed, and it
        goes on finding the target scan's files sitting there in the folder. An
        operator who has said they are finished with something has to be taken at
        their word, or the button is a lie.
        """
        library, folder = a_run_being_watched
        _store(folder / "targetscan_cell001.ome.zarr", voxel=TARGET_SCAN_VOXEL)
        library.entries()
        library.close_group("targetscan")

        # Two more looks, as the viewer takes several a second during a run.
        library.entries()
        open_now = [name for _, _, name in library.entries()]
        assert "targetscan_cell001.ome.zarr" not in open_now, (
            f"the closed target scan came back on its own: {open_now}"
        )

    def test_a_later_position_of_it_joins_it_rather_than_starting_again(
        self, a_run_being_watched
    ):
        """A target scan of a second cell is another piece of the same picture.

        If each newcomer started a dataset of its own, a run visiting forty targets
        would end the day with forty headings — which would be a worse answer than
        the merge this whole file is about.
        """
        library, folder = a_run_being_watched
        _store(folder / "targetscan_cell001.ome.zarr", voxel=TARGET_SCAN_VOXEL)
        library.entries()
        _store(folder / "targetscan_cell002.ome.zarr", voxel=TARGET_SCAN_VOXEL)

        open_now = _by_dataset(library)
        assert len(open_now) == 2, f"a heading per target rather than per scan: {open_now}"
        targets = sorted(
            names for names in open_now.values() if names[0].startswith("targetscan")
        )[0]
        assert sorted(targets) == [
            "targetscan_cell001.ome.zarr",
            "targetscan_cell002.ome.zarr",
        ]

    def test_a_third_acquisition_gets_a_heading_of_its_own_too(self, a_run_being_watched):
        """A run has a handful of kinds of scan: a prescan, an overview, a target."""
        library, folder = a_run_being_watched
        _store(folder / "targetscan_cell001.ome.zarr", voxel=TARGET_SCAN_VOXEL)
        _store(folder / "prescan_whole.ome.zarr", voxel=(20.0, 10.0, 10.0))

        assert len(_by_dataset(library)) == 3, _by_dataset(library)


class TestWhatTheOperatorIsShown:
    """The same thing again, through the server, because that is what the panel reads."""

    def _serving(self, folder: Path, site: Path):
        """The real server on a free port, watching ``folder``, and its port."""
        site.mkdir()
        (site / "index.html").write_text("x", encoding="utf-8")
        # ``loads=[{}]`` is "open the folder itself, all of it, and keep watching
        # it", which is what the viewer does when it is started on a run.
        server = make_server(port=0, data_dir=folder, site_dir=site, loads=[{}])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def _config(self, port: int) -> dict:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        try:
            conn.request("GET", "/api/config")
            return json.loads(conn.getresponse().read())
        finally:
            conn.close()

    def test_the_target_scan_arrives_as_its_own_row_with_its_own_brightness(self, tmp_path):
        """A row's brightness is measured from the store it is drawn from.

        Merged into the overview's row, the target scan was drawn with the
        overview's black and white points — so a dim target scan could be
        invisible, or a bright one solid white, with no handle to correct it. The
        two stores here are filled with deliberately different values, so a row
        carrying the overview's window can be told from one carrying its own.
        """
        folder = tmp_path / "run"
        _store(folder / "overview_pos001.ome.zarr", brightness=400)
        server, thread = self._serving(folder, tmp_path / "site")
        try:
            port = server.server_address[1]
            _store(
                folder / "targetscan_cell001.ome.zarr",
                voxel=TARGET_SCAN_VOXEL,
                brightness=9000,
            )
            config = self._config(port)
        finally:
            server.shutdown()
            thread.join(timeout=5)

        assert len(config["groups"]) == 2, (
            f"the panel would show one picture, not two: {config['groups']}"
        )
        rows = {row["group"]: row for row in config["layers"]}
        assert len(rows) == 2, f"one row for two acquisitions: {config['layers']}"
        overview = rows[[g for g in config["groups"] if g == "run"][0]]
        target = rows[[g for g in config["groups"] if g != "run"][0]]
        assert len(target["sources"]) == 1, (
            f"the target scan's row reads from the overview as well: {target['sources']}"
        )
        assert "targetscan_cell001.ome.zarr" in target["sources"][0]
        assert target["window"]["high"] != overview["window"]["high"], (
            "the target scan is being shown with the overview's brightness"
        )


class TestTheOrdinaryCaseIsUndisturbed:
    """Far more common than the above, and the reason to be careful about it.

    Almost everything that appears in a watched folder during a run is another
    piece of the picture already on screen. If those started arriving as separate
    headings, a tiled overview of a hundred positions would fill the panel with a
    hundred rows and never be drawn as one specimen again.
    """

    def test_more_positions_of_the_same_acquisition_still_merge(self, a_run_being_watched):
        library, folder = a_run_being_watched
        for position in range(2, 6):
            _store(folder / f"overview_pos{position:03d}.ome.zarr")

        open_now = _by_dataset(library)
        assert len(open_now) == 1, f"the overview was broken into pieces: {open_now}"
        assert len(next(iter(open_now.values()))) == 5

    def test_another_channel_of_the_same_position_still_merges(self, tmp_path):
        """The shape a mesoSPIM transfer writes: one store per tile and channel.

        The channel is in the name rather than inside the store, so there is no
        channel list to compare and nothing to disagree about — which is right,
        because a tile that has not been imaged in every channel yet is a normal
        state during a run and not a mismatch.
        """
        folder = tmp_path / "mesospim_run"
        _store(folder / "scan_Tile0_Ch488.ome.zarr")
        library = Library()
        library.open(folder)
        _store(folder / "scan_Tile0_Ch647.ome.zarr")
        _store(folder / "scan_Tile1_Ch488.ome.zarr")

        open_now = _by_dataset(library)
        assert len(open_now) == 1, f"channels and tiles were split apart: {open_now}"
        assert len(next(iter(open_now.values()))) == 3

    def test_a_store_that_declares_the_same_channels_still_merges(self, tmp_path):
        """Where stores do name their channels, agreeing is the ordinary case."""
        folder = tmp_path / "declared"
        axes = ("c", "z", "y", "x")
        _store(folder / "overview_pos001.ome.zarr", axes=axes, channels=["Ch488", "Ch647"])
        library = Library()
        library.open(folder)
        _store(folder / "overview_pos002.ome.zarr", axes=axes, channels=["Ch488", "Ch647"])

        assert len(_by_dataset(library)) == 1, _by_dataset(library)

    def test_a_store_that_says_nothing_about_its_voxel_size_is_not_split_off(self, tmp_path):
        """Silence is not disagreement, so it joins what is open.

        The alternative would be to treat every store from an instrument that does
        not record its voxel size as a separate picture, which would break those
        runs completely for the sake of a suspicion the data does not support.
        """
        folder = tmp_path / "quiet"
        _store(folder / "overview_pos001.ome.zarr")
        library = Library()
        library.open(folder)
        _store_without_a_voxel_size(folder / "overview_pos002.ome.zarr")

        open_now = _by_dataset(library)
        assert len(open_now) == 1, (
            f"a store that never said what it was got a heading of its own: {open_now}"
        )

    def test_a_folder_that_is_not_watched_is_still_left_alone(self, tmp_path):
        """A selection the operator asked for stays as they asked for it.

        Nothing is looked for in an unwatched folder, so a target scan landing in it
        does not appear — by the operator's own choice, which is the one reason the
        viewer ever shows less than what is on disk.
        """
        folder = tmp_path / "finished_run"
        _store(folder / "overview_pos001.ome.zarr")
        library = Library()
        library.open(folder, watch=False)
        _store(folder / "targetscan_cell001.ome.zarr", voxel=TARGET_SCAN_VOXEL)

        assert [name for _, _, name in library.entries()] == ["overview_pos001.ome.zarr"]


class TestStartingTheViewerOnSuchAFolder:
    """The other half of the same disagreement, met at the command line."""

    def test_the_refusal_is_explained_rather_than_thrown(self, tmp_path, capsys):
        """A biologist should read the message that was written for them.

        Opening a folder that already holds two acquisitions is refused, and the
        refusal says which stores are in each so that the answer is to open one of
        them. That message used to arrive as a Python traceback with itself buried
        at the bottom, which is not something anyone should have to read at a
        microscope.
        """
        if not (_VIZ_ROOT / "frontend" / "dist" / "index.html").exists():
            pytest.skip(
                "frontend/dist is not built, so run_demo.py stops before it gets "
                "as far as the folder — build it with "
                "`npm --prefix frontend install && npm --prefix frontend run build`"
            )
        import run_demo

        folder = tmp_path / "mixed"
        _store(folder / "overview_pos001.ome.zarr")
        _store(folder / "targetscan_cell001.ome.zarr", voxel=TARGET_SCAN_VOXEL)

        answer = run_demo.main(["--data", str(folder)])
        printed = capsys.readouterr().out

        assert answer == 1, "a refusal should leave the command reporting failure"
        assert "more than one acquisition" in printed, printed
        assert "targetscan_cell001.ome.zarr" in printed, printed
        assert "Traceback" not in printed
