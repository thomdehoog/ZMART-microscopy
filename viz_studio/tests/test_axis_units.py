"""A store whose axis units are spelled the everyday way still opens.

OME-Zarr asks for axis units named the long way — ``micrometer`` — and the engine
refuses a store that says anything else, rejecting the whole image rather than the
axis. That refusal is correct by the letter of the format and useless in a
facility: a real 75 GB fused acquisition on this machine says ``um``, which every
microscopist writes and no reader but this one minds, and the whole dataset is
unviewable for two characters of metadata.

So the description is repaired on its way out of the server. This is not working
around a shortcoming in the engine — the store is the thing that is out of spec —
and it is the one place a fix costs nothing, since descriptions are already read
and remembered there.

The repair is deliberately timid. Anything it does not recognise is passed through
untouched, and a description it cannot parse is served exactly as it was found: a
store that opens today must not stop opening because a repair went wrong.
"""

from __future__ import annotations

import http.client
import json
import threading

import numpy as np
import zarr
from server import make_server
from stores import normalise_units


def _described(unit: str) -> bytes:
    return json.dumps(
        {
            "multiscales": [
                {
                    "version": "0.4",
                    "axes": [
                        {"name": "z", "type": "space", "unit": unit},
                        {"name": "y", "type": "space", "unit": unit},
                        {"name": "x", "type": "space", "unit": unit},
                    ],
                    "datasets": [{"path": "0"}],
                }
            ]
        }
    ).encode("utf-8")


def _units_in(raw: bytes) -> list[str]:
    return [axis["unit"] for axis in json.loads(raw)["multiscales"][0]["axes"]]


class TestRepairingAUnit:
    def test_the_everyday_spelling_becomes_the_one_the_format_asks_for(self):
        assert _units_in(normalise_units(_described("um"))) == ["micrometer"] * 3

    def test_the_micro_sign_and_greek_mu_are_both_understood(self):
        """Two characters that look identical and are not, and both occur."""
        assert _units_in(normalise_units(_described("µm"))) == ["micrometer"] * 3
        assert _units_in(normalise_units(_described("μm"))) == ["micrometer"] * 3

    def test_other_short_spellings_are_repaired_too(self):
        for short, long in (("nm", "nanometer"), ("mm", "millimeter"), ("ms", "millisecond")):
            assert _units_in(normalise_units(_described(short))) == [long] * 3

    def test_a_store_that_is_already_correct_is_left_byte_for_byte_alone(self):
        """The common case, and it must not be rewritten — the browser keeps these."""
        already = _described("micrometer")
        assert normalise_units(already) is already

    def test_an_unfamiliar_unit_is_passed_through_rather_than_guessed_at(self):
        assert _units_in(normalise_units(_described("furlong"))) == ["furlong"] * 3

    def test_an_axis_with_no_unit_at_all_is_untouched(self):
        raw = json.dumps({"multiscales": [{"axes": [{"name": "x"}], "datasets": []}]}).encode()
        assert normalise_units(raw) is raw


class TestNotBreakingWhatAlreadyWorks:
    """The repair must never be the reason a store stops opening."""

    def test_something_that_is_not_json_is_served_as_it_was_found(self):
        raw = b"\x93NUMPY\x01\x00 not json at all"
        assert normalise_units(raw) is raw

    def test_a_description_with_no_multiscales_is_served_as_it_was_found(self):
        raw = json.dumps({"zarr_format": 2}).encode("utf-8")
        assert normalise_units(raw) is raw

    def test_an_ome_zarr_0_5_description_is_repaired_in_its_own_place(self):
        """0.5 moves multiscales under an ``ome`` key; the units move with it."""
        raw = json.dumps(
            {"ome": {"multiscales": [{"axes": [{"name": "x", "unit": "um"}], "datasets": []}]}}
        ).encode("utf-8")
        repaired = json.loads(normalise_units(raw))
        assert repaired["ome"]["multiscales"][0]["axes"][0]["unit"] == "micrometer"


class TestTheRepairReachesTheBrowser:
    """The repair has to happen where the description leaves the machine.

    Everything above asks the repair itself whether it works, and it does. None of
    it asks the question that actually matters: does what the **browser** receives
    have the corrected spelling in it? Those are different questions, and the second
    is the one an operator's afternoon depends on. A perfect repair that the server
    forgets to call leaves the engine refusing the store exactly as before, and every
    test above still passes.

    So this starts the real server on a store that says ``um``, fetches its
    description the way the page does, and reads the units out of what came back.
    """

    def _a_store_saying(self, folder, unit: str):
        """A small but real OME-Zarr whose axes are spelled the everyday way."""
        folder.mkdir(parents=True, exist_ok=True)
        store = folder / "acquisition.ome.zarr"
        store.mkdir()
        group = zarr.open_group(str(store), mode="w", zarr_format=2)
        array = group.create_array("0", shape=(4, 32, 32), chunks=(1, 32, 32), dtype="uint16")
        array[:] = np.full((4, 32, 32), 2000, dtype=np.uint16)
        (store / ".zattrs").write_text(
            json.dumps(
                {
                    "multiscales": [
                        {
                            "version": "0.4",
                            "axes": [
                                {"name": name, "type": "space", "unit": unit}
                                for name in ("z", "y", "x")
                            ],
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
        return store

    def _fetch(self, port: int, path: str) -> bytes:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("GET", path)
            return connection.getresponse().read()
        finally:
            connection.close()

    def _served_units(self, tmp_path, unit: str) -> list[str]:
        data = tmp_path / "data"
        self._a_store_saying(data, unit)
        site = tmp_path / "site"
        site.mkdir()
        (site / "index.html").write_text("<!doctype html>", encoding="utf-8")
        server = make_server(
            port=0, data_dir=data, site_dir=site, store="acquisition.ome.zarr"
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = self._fetch(
                server.server_address[1], "/data/0/acquisition.ome.zarr/.zattrs"
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
        return [
            axis["unit"] for axis in json.loads(body)["multiscales"][0]["axes"]
        ]

    def test_a_store_saying_um_is_served_saying_micrometer(self, tmp_path):
        assert self._served_units(tmp_path, "um") == ["micrometer"] * 3

    def test_a_store_that_was_already_correct_is_served_unchanged(self, tmp_path):
        """The far commoner case, and the repair must not disturb it."""
        assert self._served_units(tmp_path, "micrometer") == ["micrometer"] * 3
