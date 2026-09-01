"""Which of the viewer's addresses reach the operator's canvas.

The viewer can put several addresses under one heading for two quite different
reasons, and the answer looks the same either way. One means "here is the same
picture again, opened afresh" and only the last of them can still be read. The
other means "here are the fields this one picture is made of" and every one of
them is wanted. Keeping the wrong ones has cost this project a picture twice,
in opposite directions, so both are pinned here.
"""

from __future__ import annotations

from application.parts.storage.viewer_service import _the_sources_in


def _config(*layers: dict) -> dict:
    """A viewer configuration holding the given image rows."""
    return {"layers": [{"kind": "image", **layer} for layer in layers]}


def test_every_field_of_a_composed_acquisition_is_kept():
    """A scan of many fields is one picture, and all of it should be drawn.

    The viewer composes a run of positions into one acquisition and names every
    field of it in the same row. Keeping one of them is keeping a single square
    of tissue out of a whole plate — and the scan still reports itself finished,
    so nothing on screen says a thing.
    """
    answered = _the_sources_in(
        _config({
            "group": "overview",
            "sources": [
                "/data/0/overview_P000000.ome.zarr/|zarr3:",
                "/data/0/overview_P000001.ome.zarr/|zarr3:",
                "/data/0/overview_P000002.ome.zarr/|zarr3:",
                "/data/0/overview_P000003.ome.zarr/|zarr3:",
            ],
        }),
        port=8848,
    )

    assert len(answered["overview"]) == 4
    assert all(one["name"] == "overview" for one in answered["overview"])
    # Whole addresses, with the host put back on: an engine handed an address
    # with no host builds a layer that waits for ever.
    assert all(
        one["url"].startswith("http://127.0.0.1:8848/") for one in answered["overview"]
    )


def test_a_superseded_generation_is_dropped():
    """Only the newest opening of a growing folder can still be read.

    Relinking a folder that is still being written opens it again under a new
    dataset number, and the older opening stops being able to build its pieces.
    A page handed the older one draws a layer that reports no error and asks for
    picture that is answered "not found" — present, correct, and invisible.
    """
    answered = _the_sources_in(
        _config({
            "group": "overview",
            "sources": [
                "/data/0/overview_P000000.ome.zarr/|zarr3:",
                "/data/2/overview_P000000.ome.zarr/|zarr3:",
                "/data/1/overview_P000000.ome.zarr/|zarr3:",
            ],
        }),
        port=8848,
    )

    assert [one["url"] for one in answered["overview"]] == [
        "http://127.0.0.1:8848/data/2/overview_P000000.ome.zarr/|zarr3:"
    ]


def test_the_newest_generation_keeps_all_of_its_fields():
    """The two reasons together, which is what a real growing scan looks like.

    A composed acquisition that has been linked again holds both: several
    fields, and more than one generation of them. What is wanted is every field
    of the newest generation and nothing of the older one.
    """
    answered = _the_sources_in(
        _config({
            "group": "overview",
            "sources": [
                "/data/0/overview_P000000.ome.zarr/|zarr3:",
                "/data/0/overview_P000001.ome.zarr/|zarr3:",
                "/data/1/overview_P000000.ome.zarr/|zarr3:",
                "/data/1/overview_P000001.ome.zarr/|zarr3:",
                "/data/1/overview_P000002.ome.zarr/|zarr3:",
            ],
        }),
        port=8848,
    )

    kept = sorted(one["url"] for one in answered["overview"])
    assert kept == [
        "http://127.0.0.1:8848/data/1/overview_P000000.ome.zarr/|zarr3:",
        "http://127.0.0.1:8848/data/1/overview_P000001.ome.zarr/|zarr3:",
        "http://127.0.0.1:8848/data/1/overview_P000002.ome.zarr/|zarr3:",
    ]


def test_acquisitions_are_kept_apart():
    """Two acquisitions are two headings, however many fields each holds."""
    answered = _the_sources_in(
        _config(
            {
                "group": "overview",
                "sources": [
                    "/data/0/overview_P000000.ome.zarr/|zarr3:",
                    "/data/0/overview_P000001.ome.zarr/|zarr3:",
                ],
            },
            {"group": "focussing", "sources": ["/data/1/focussing_P000000.ome.zarr/|zarr3:"]},
        ),
        port=8848,
    )

    assert sorted(answered) == ["focussing", "overview"]
    assert len(answered["overview"]) == 2
    assert len(answered["focussing"]) == 1


def test_the_viewers_own_decoration_does_not_make_a_second_heading():
    """A relinked acquisition wears a copy number; it is still one acquisition.

    The viewer decorates a label when names collide — a session prefix and a
    copy number — and both are its own bookkeeping rather than anything the
    acquisition is called. Left on, each relink would stand as a heading of its
    own and the panel would fill with acquisitions that do not exist.
    """
    answered = _the_sources_in(
        _config(
            {"group": "overview.zmartview.zarr", "sources": ["/data/0/a.ome.zarr/|zarr3:"]},
            {
                "group": "session-abc · overview.zmartview.zarr (2)",
                "sources": ["/data/1/b.ome.zarr/|zarr3:"],
            },
        ),
        port=8848,
    )

    assert list(answered) == ["overview"]
    assert [one["url"] for one in answered["overview"]] == [
        "http://127.0.0.1:8848/data/1/b.ome.zarr/|zarr3:"
    ]


def test_anything_that_is_not_a_picture_is_left_alone():
    """A row that is not an image is not something an engine can draw."""
    answered = _the_sources_in(
        {
            "layers": [
                {"kind": "segmentation", "group": "targets", "sources": ["/data/0/t.zarr/"]},
                {"kind": "image", "group": "overview", "sources": ["/data/0/o.zarr/"]},
            ]
        },
        port=8848,
    )

    assert list(answered) == ["overview"]
