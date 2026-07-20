"""capture_positions drives the controller surface only (mock instrument)."""

from __future__ import annotations

from pathlib import Path

import pytest
from workflow._capture_run import capture_positions

import zmart_controller
from zmart_controller.tests.mock_driver import register_mock

_MOCK = {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api", "client": "mock-client"}


@pytest.fixture
def mic():
    register_mock()
    session = zmart_controller.set_instrument(_MOCK)
    yield session
    session.disconnect()


def test_visits_each_position_and_returns_records(mic):
    positions = [{"x": 10.0, "y": 20.0, "z": 5.0}, {"x": 30.0, "y": 40.0, "z": 6.0}]

    records = capture_positions(mic, positions, "overview")

    assert [r["position"] for r in records] == positions
    assert [r["position_label"] for r in records] == ["1", "2"]
    assert all(r["acquisition_type"] == "overview" for r in records)


def test_applies_state_once_before_capturing(mic):
    capture_positions(
        mic,
        [{"x": 0.0, "y": 0.0, "z": 0.0}],
        "target",
        state={"changeable": {"laser_power": 9.0}},
    )

    assert mic.get_state()["changeable"]["laser_power"] == 9.0


def test_label_callable_overrides_the_index(mic):
    positions = [{"x": 1.0, "y": 2.0, "z": 3.0}, {"x": 4.0, "y": 5.0, "z": 6.0}]

    records = capture_positions(mic, positions, "target", label=lambda i, p: f"t{i:03d}")

    assert [r["position_label"] for r in records] == ["t001", "t002"]


def test_on_record_streams_each_acquisition():
    class _Session:
        def __init__(self):
            self.n = 0

        def set_xyz(self, x, y, z):
            pass

        def acquire(self, *, acquisition_type, position_label, options=None):
            self.n += 1
            return {"position_label": position_label}

    streamed = []
    records = capture_positions(
        _Session(),
        [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 1.0, "y": 0.0, "z": 0.0}],
        "overview",
        on_record=lambda index, pos, record: streamed.append((index, pos["x"], record)),
    )
    assert [s[0] for s in streamed] == [1, 2]
    assert [s[1] for s in streamed] == [0.0, 1.0]
    assert [s[2] for s in streamed] == records


def test_cancel_stops_between_sites_and_commits_nothing():
    """A cancel lands cleanly at a site boundary: no further move, no records."""
    from workflow._capture_run import RunCancelled, capture_positions

    class _Session:
        def __init__(self):
            self.moves = []
            self.acquired = 0

        def set_xyz(self, x, y, z, **_kw):
            self.moves.append((x, y, z))

        def acquire(self, **kwargs):
            self.acquired += 1
            return {"n": self.acquired}

    session = _Session()
    stop_after = {"n": 1}

    def _cancel():
        return session.acquired >= stop_after["n"]

    positions = [{"x": float(i), "y": 0.0, "z": 0.0} for i in range(3)]
    with pytest.raises(RunCancelled, match="before site 2 of 3"):
        capture_positions(session, positions, "overview", cancel=_cancel)
    assert session.acquired == 1  # the site in progress finished...
    assert len(session.moves) == 1  # ...and no further move was made


def test_cancel_checked_before_the_first_move_too():
    from workflow._capture_run import RunCancelled, capture_positions

    class _Session:
        def set_xyz(self, *a, **k):
            raise AssertionError("must not move at all")

        def acquire(self, **kwargs):
            raise AssertionError("must not acquire at all")

    with pytest.raises(RunCancelled, match="before site 1"):
        capture_positions(
            _Session(), [{"x": 0.0, "y": 0.0, "z": 0.0}], "overview", cancel=lambda: True
        )


def test_output_run_uses_driver_hash_vendor_location_and_full_final_paths(tmp_path):
    class _Session:
        count = 0

        def set_xyz(self, x, y, z):
            pass

        def acquire(self, *, acquisition_type, position_label, options=None):
            assert options == {"format": "ome-tiff"}  # workflow never injects its hash
            self.count += 1
            acquisition_hash = f"00000{self.count}"
            path = tmp_path / ".staging" / (
                f"{acquisition_type}_{acquisition_hash}_{position_label}_"
                "T000000_C00_Z00000.ome.tiff"
            )
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"image")
            return {
                "acquisition_type": acquisition_type,
                "acquisition_hash": acquisition_hash,
                "position_label": position_label,
                "images": [str(path)],
                "planes": [{"t": 0, "c": 0, "z": 0, "path": str(path)}],
            }

    experiment = tmp_path / "organoid-screen_abc123"
    positions = [
        {
            "x": 1.0,
            "y": 2.0,
            "z": 3.0,
            "location": {"carrier": 2, "compartment": 31, "group": 4, "position": 8},
        },
        {"x": 4.0, "y": 5.0, "z": 6.0},
    ]

    records = capture_positions(
        _Session(),
        positions,
        "overview",
        options={"format": "ome-tiff"},
        output_root=experiment,
    )

    assert [record["position_label"] for record in records] == [
        "K02_M000031_G000004_P000008_V00",
        "K00_M000000_G000000_P000001_V00",
    ]
    assert [record["acquisition_hash"] for record in records] == ["000001", "000002"]
    data = experiment / "overview/data"
    assert all(Path(path).parent == data for record in records for path in record["images"])
    assert all(Path(path).is_file() for record in records for path in record["images"])
    assert all(record["planes"][0]["path"] == record["images"][0] for record in records)


def test_output_run_accepts_one_driver_minted_hash_per_position(tmp_path):
    class _Session:
        count = 0

        def set_xyz(self, x, y, z):
            pass

        def acquire(self, *, acquisition_type, position_label, options=None):
            self.count += 1
            hash6 = f"00000{self.count}"
            path = tmp_path / ".staging" / f"{position_label}-{hash6}.ome.tiff"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"image")
            return {
                "acquisition_hash": hash6,
                "position_label": position_label,
                "images": [str(path)],
            }

    records = capture_positions(
        _Session(),
        [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 1.0, "y": 0.0, "z": 0.0}],
        "overview",
        output_root=tmp_path / "experiment_abc123",
    )
    assert [record["acquisition_hash"] for record in records] == ["000001", "000002"]
    assert {Path(record["images"][0]).parent for record in records} == {
        tmp_path / "experiment_abc123/overview/data"
    }
