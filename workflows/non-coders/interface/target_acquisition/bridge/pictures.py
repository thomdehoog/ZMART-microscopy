"""What a capture becomes once it has landed: its OME-Zarr position, and the pictures the page fetches.

Every capture is converted the moment it lands into one OME-Zarr position
(``keep_position_as_zarr``), which the viewer beside the bridge links into
one live picture. The small JPEG copies the page's panels show and the
copies drawn with the canvas's own display settings are made from the
records here, on request, under the run's ``view`` folders, and handed out
by :func:`a_picture` at ``/api/target_acquisition/view/<kind>/<name>``. A
focus stack's slices are served as they were written; a field's detection
masks are drawn on request.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import shutil
import urllib.parse
from pathlib import Path

from zmart_interface.framework.bridge.api import Bytes, Refusal

from ..microscope.focus_run import FOCUSSING
from ..storage import output, viewer_service
from ..storage.zarr_positions import frame_um_of, position_store_from_record
from . import ledgers, state


def keep_position_as_zarr(record: dict, acquisition_type: str) -> None:
    """The capture's canonical form: one OME-Zarr 0.5 position in
    ``positions/<acquisition type>/``, converted from the vendor's own files
    the moment they land — see :mod:`target_acquisition.storage.zarr_positions`.
    The folder is named by the type because the viewer names the one picture
    it links a folder into after the folder itself.

    A conversion that fails is filed on the record rather than felling the
    scan: the vendor's files are on disk and the conversion can be run again,
    while a stage drive cut short cannot.
    """
    try:
        store = the_drivers_store(record)
        projections_in = None
        if store is not None:
            # The driver saved the capture as one OME-Zarr image: that is the
            # capture's one copy, used as it is. So is its projection: the
            # driver's, under the store's name in ``projections`` beside the
            # folder the store is in, or a flat capture itself.
            folder = store.parent
            record["zarr"] = str(store)
            if (folder.parent / "projections" / store.name).is_dir():
                projections_in = folder.parent / "projections"
            elif len({plane.get("z") for plane in record.get("planes") or []}) == 1:
                projections_in = folder
        else:
            folder = state.the_run() / "positions" / acquisition_type
            record["zarr"] = str(position_store_from_record(record, folder))
        # The frame's true width on the sample. A recording made before the
        # run says what was promised; the instrument may have stood on
        # another job by the time it captured, and the page draws, crops and
        # opens the ground over what actually landed.
        record["frame_um"] = frame_um_of(record["zarr"])
    except Exception as why:  # noqa: BLE001 -- filed, not fatal
        record["zarr_error"] = str(why)
        return
    # The viewer beside this bridge links the folder into one live picture;
    # the first position of a kind opens it, the rest ring the doorbell.
    viewer_service.a_position_landed(
        acquisition_type, folder, store=record["zarr"], projections_in=projections_in,
    )


def the_drivers_store(record: dict) -> Path | None:
    """The OME-Zarr store the driver saved the capture as, or None for files a plane.

    Every plane then names the same store (its ``c``, ``z``, ``t`` index into
    it), as the controller's acquire contract allows.
    """
    paths = {str(plane.get("path")) for plane in record.get("planes") or []}
    if len(paths) != 1:
        return None
    store = Path(next(iter(paths)))
    return store if store.name.endswith(".ome.zarr") and store.is_dir() else None


#: Where a scan's display copies go: beside ``data``, under the acquisition
#: type. They are made *from* the pixels rather than being pixels, which is
#: what puts them next to ``data`` instead of inside it.
VIEW = "view"


def the_display_asked_for(query: str) -> list | None:
    """The ``display=`` of a picture request, or None when none was asked."""
    asked = urllib.parse.parse_qs(query or "").get("display")
    if not asked:
        return None
    try:
        display = json.loads(asked[0])
    except ValueError:
        return None
    return display if isinstance(display, list) else None


#: How many display copies are kept at once. Each is up to a megapixel
#: JPEG, and the operator trying brightness settings on a large overview
#: makes a new one per setting per field: without a limit the bridge grew for
#: as long as the scan stood. Enough for the fields on screen and a few
#: settings each; one asked again past the limit is drawn again.
DISPLAYED_KEPT = 64


def a_picture_as_displayed(acquisition_type: str, label: str, display: list) -> bytes | None:
    """One field's copy drawn with the canvas's own settings, or None when the
    field was never captured. See :func:`jpeg_tiles.picture_as_displayed`.

    Copies are remembered up to :data:`DISPLAYED_KEPT`; past it, the one used
    longest ago is let go.
    """
    from ..storage import jpeg_tiles

    record = next(
        (one for one in state.records.get(acquisition_type, []) if one.get("position_label") == label),
        None,
    )
    if record is None:
        return None
    key = (acquisition_type, label, json.dumps(display, sort_keys=True))
    kept = state.displayed_pictures
    picture = kept.pop(key, None)
    if picture is None:
        captured = record.get("planes") or []
        first_time = min((int(p.get("t", 0)) for p in captured), default=0)
        planes = [(int(p.get("c", 0)), p["path"]) for p in captured
                  if p.get("path") and int(p.get("t", 0)) == first_time]
        # The whole frame: the operator judges a diameter against this
        # picture, and a thumbnail blown up to the panel's width is blocks.
        picture = jpeg_tiles.picture_as_displayed(
            planes, display, budget_px=1024 * 1024, store=record.get("zarr"))
    # Put back last, so the order of the dictionary is the order of use.
    kept[key] = picture
    while len(kept) > DISPLAYED_KEPT:
        kept.pop(next(iter(kept)), None)
    return picture


def view_of(acquisition_type: str) -> Path:
    """Where this kind of scan's pictures are, in this run's own folder.

    The kind arrives from the page, so it is checked to be a plain folder
    name first: anything else could name a folder outside the run.
    """
    return state.the_run() / output.checked_name(acquisition_type, field="acquisition_type") / VIEW


def the_view_of(acquisition_type: str) -> Path | None:
    """Ask the viewer to bring this scan's pictures up to date, and say where.

    Every field the run captured, the files it left behind, and where on the
    sample it was taken -- all read off the records, because the acquisition is
    what says where it was. What a display copy is, and how one is made, is the
    viewer's own business.

    The records are copied at the door: a field that lands while a build runs
    is not in the snapshot and must not be signed for -- counting the live
    list once marked a run's last stride built without building it.
    """
    from ..storage.jpeg_tiles import make_what_is_missing  # noqa: PLC0415

    with state.view_lock:
        records = list(state.records.get(acquisition_type, []))
        note = view_of(acquisition_type) / "tiles.json"
        if state.view_built.get(acquisition_type) == len(records) and note.is_file():
            return note if records else None
        made = make_what_is_missing(view_of(acquisition_type), {
            record["position_label"]: (record["planes"], the_middle_of(record))
            for record in records
        })
        state.view_built[acquisition_type] = len(records)
        return made


#: What a view folder is allowed to hold, and what to call it when sent.
#: A short list rather than a guess, because this hands out files by a name
#: the page chose: anything not on it is not a picture and is not sent.
PICTURES = {".jpg": "image/jpeg", ".png": "image/png", "tiles.json": "application/json"}


def a_picture(asked: dict, query: str, rest: str) -> Bytes:
    """One file from a scan's view folder: ``view/<acquisition type>/<name>``.

    Browsers will not let a page read files off a disk, so the pictures a
    scan makes have to be served, and this is the only reason the bridge
    serves anything that is not JSON.

    The name is taken apart rather than joined on: a name with a path in it
    would otherwise reach out of the folder and hand out any file this
    process can read.
    """
    kind, _, name = rest.partition("/")
    wanted = PICTURES.get(name if name in PICTURES else Path(name).suffix)
    if not kind or not name or name != Path(name).name or wanted is None:
        raise Refusal(f"no picture {rest!r}", status=404)
    display = the_display_asked_for(query)
    raw = kind == FOCUSSING
    if display is not None and name.endswith(".jpg") and not raw:
        # The copy drawn with the picture's own display settings: what the
        # page's canvas shows, not the scan-wide stretch the small copies
        # wear. Rendered on request and remembered by its asking.
        body = a_picture_as_displayed(kind, name[: -len(".jpg")], display)
        if body is None:
            raise Refusal(f"nothing has been imaged at {rest}", status=404)
        return Bytes(body, wanted)
    drawn = next(((ending, draw) for ending, draw in DRAWN.items() if name.endswith(ending)), None)
    if drawn is not None:
        # A picture drawn on request (a field's detection mask, say), asked
        # for by the field's label; one that cannot be drawn answers 404
        # rather than a broken picture.
        ending, draw = drawn
        where = draw(kind, name[: -len(ending)])
    elif raw:
        # The focus stack's slices, written into its view folder as each
        # point lands, served as they are.
        where = view_of(kind) / name
    else:
        note = the_view_of(kind)
        where = None if note is None else (note if name == "tiles.json" else note.parent / name)
    if where is None or not where.is_file():
        raise Refusal(f"nothing has been imaged at {rest}", status=404)
    return Bytes(where.read_bytes(), wanted)


def the_mask_view_for(kind: str, label: str):
    """The colorized mask PNG for the *kind* field labelled *label*, or None."""
    from ..analysis.mask_view import mask_view_of

    for record in state.records.get(kind, []):
        if record.get("position_label") == label:
            return mask_view_of(record, label)
    return None


def the_label_map_for(kind: str, label: str):
    """The raw label-mask PNG for the *kind* field labelled *label*, or None."""
    from ..analysis.mask_view import label_map_of

    for record in state.records.get(kind, []):
        if record.get("position_label") == label:
            return label_map_of(record, label)
    return None


#: The pictures drawn on request, by the end of their name: each draws the
#: file to send for ``(kind, label)``, or None for 404.
DRAWN = {".mask.png": the_mask_view_for, ".labels.png": the_label_map_for}


def the_middle_of(record: dict) -> tuple:
    """Where on the sample a capture was taken, from what it reported.

    Every plane of one capture is at the same place, so the first is enough.
    """
    first = record["planes"][0]
    return float(first["x_um"]), float(first["y_um"])


def replace_the_acquisition(acquisition_type: str, keeping: set[str] = frozenset()) -> None:
    """A scan of this kind is starting again: what the new run will not rewrite goes.

    The records were already forgotten, but the position stores and the
    display copies stayed on disk, and the viewer kept listing every store it
    had once seen. A shorter rerun therefore showed the fields the new run
    never captured. ``keeping`` names the stores the new run will write
    again; those stay and are replaced in place as each lands, which is what
    lets the picture grow without being reopened. Any other store of this
    kind is stale and is removed; the viewer service then leaves it out of
    what the page is handed. The display copies are always made again, from
    the new run's own records.
    """
    run = state.the_run()
    # Checked before the first deletion: this removes folders by a name the
    # page chose, and an absolute path in its place replaced the run folder.
    positions = run / "positions" / output.checked_name(acquisition_type, field="acquisition_type")
    stale = [
        child for child in (positions.iterdir() if positions.is_dir() else [])
        if child.is_dir() and child.name.endswith(".ome.zarr") and child.name not in keeping
    ]
    if stale:
        for child in stale:
            shutil.rmtree(child, ignore_errors=True)
        viewer_service.stores_were_retired(acquisition_type, positions)
    # The stores a driver saved are the captures themselves, in ``data``:
    # never deleted, only no longer shown.
    viewer_service.forget_stores(acquisition_type, keeping=set(keeping))
    # A store half-written when something crashed is in the shared staging
    # folder beside the positions; swept only while nothing is writing there.
    leftovers = [view_of(acquisition_type)]
    if not ledgers.a_run_has_the_stage():
        leftovers.append(positions.parent / ".writing")
    for leftover in leftovers:
        shutil.rmtree(leftover, ignore_errors=True)
    with state.view_lock:
        state.view_built.pop(acquisition_type, None)
