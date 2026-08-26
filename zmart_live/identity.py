"""Giving a run's descriptions names you can trust, and keeping them on disk.

A published position is only as good as the things it points back at. It names
the profile it was written under and the layout snapshot that says who owns
which specimen, and a reader coming back next week has to be able to resolve
both of those names and get exactly what the microscope meant at the time.

This module is what makes that possible. It does two jobs.

Naming a profile after its contents
-----------------------------------

A name that does not cover what it names is not really a name. If two confocal
acquisitions with the same frame size can both be called ``confocal-1152-128``
while one writes 16-bit pixels in eight planes and the other writes 8-bit pixels
in a hundred, then that name tells a reader nothing they can rely on, and the
"sealed" promise the profile makes is empty.

So a profile's name is worked out **from the profile itself**. Everything that
could make one acquisition differ from another — the frame, the pixel type, the
voxel size, the colours, the overlap, the chunks, the file bundles, the
compression, the arrangement of positions and the ownership policies — is turned
into one short fingerprint, and that fingerprint is part of the name. Change any
of it and you get a different name. Change none of it, on any machine, on any
day, and you get the same name, which is what lets two runs be compared at all.

The fingerprint is a *hash*: a fixed-length summary of a piece of text, worked
out so that two different texts practically never come out the same. The one
used here is SHA-256, shortened to twelve characters, which is plenty to keep
the profiles of one facility apart while staying short enough to read in a log.

Keeping the records where they can be found again
-------------------------------------------------

Profiles and location snapshots are written into the live view's own
``metadata`` folder, beside the store that view serves:

.. code-block:: text

    the-run/
      data/
        survey.ome.zarr/ ...
      views/
        live/
          live.ome.zarr/ ...
          metadata/
            profiles/confocal-1152-128-3f9a2c7d1e5b.json
            locations/locations-000001.json
            locations/locations-000002.json
            locations.json   <- a copy of the newest snapshot, for convenience

Two rules govern that folder, and both exist for the same reason.

**Nothing is ever written over.** A numbered layout snapshot is written once and
then left alone. When a new position arrives and changes the arrangement, that
makes snapshot 2; snapshot 1 goes on saying what it always said, so a
measurement published against snapshot 1 stays correct even though the run has
moved on. A moment that changes nothing spatial — the next timepoint over tiles
already in place — reuses the snapshot that exists rather than minting a
thousand identical copies of the same arrangement.

**Everything is put in place in one step.** Each file is written beside its
destination under a temporary name, pushed all the way to the disk, and then
renamed over the top. Renaming is the one filesystem operation that is
genuinely all-or-nothing, so a reader looking at the exact moment a run is
saving something sees either the whole old file or the whole new one, never half
of each.

How a run uses this
-------------------

Two calls, in two places.

When the run is being set up, once the profile has been planned, store it::

    profile, geometry = plan_the_writing("confocal", frame=(1152, 2304), z_planes=8)
    store_the_profile(run_folder, profile)

Then, each time the run is about to publish something — before the commit record
is written, and after any newly arrived position has been placed — record the
arrangement and use the snapshot that comes back::

    layout = record_the_layout(run_folder, layout)
    ...
    CommitEvent(..., scene_layout_revision=layout.revision, ...)

Using the returned snapshot rather than the one that went in is what makes the
commit refer to a snapshot that genuinely exists on disk, at the number it was
genuinely given.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

# The durable write already exists once, in the module that publishes commit
# records, and getting the write-then-rename dance right matters far too much to
# have two versions of it drifting apart. It is reused here rather than copied,
# which is why this reaches for a name the manifest keeps to itself.
from .manifest import _write_and_replace as _put_in_place_in_one_step
from .manifest import now_in_words
from .model import (
    AcquisitionProfile,
    SceneLayoutRevision,
    ZmartLiveError,
    check_the_name_is_safe,
    is_a_safe_name,
)

__all__ = [
    "FINGERPRINT_LENGTH",
    "RECORDS_FOLDER",
    "check_the_name_is_safe",
    "fingerprint_of_a_profile",
    "is_a_safe_name",
    "latest_layout_revision",
    "load_a_layout_revision",
    "load_the_profile",
    "name_for_a_profile",
    "record_the_layout",
    "spatial_fingerprint_of_a_layout",
    "store_a_layout_revision",
    "store_the_profile",
    "stored_layout_revisions",
    "stored_profile_ids",
    "the_records_folder",
]

#: The folder, inside a run, that holds the run's own descriptions of itself as
#: opposed to its pixels. It lives with the view it serves — the contract in
#: ``zmart-viewer/app/picture/CONTRACT_the_files_the_viewer_needs.md`` explains why:
#: the data folder belongs to the microscope, and everything of ours is
#: bundled under ``views/`` where it can be deleted without losing science.
RECORDS_FOLDER = "views/live/metadata"

#: How many characters of the fingerprint end up in a name. Twelve hexadecimal
#: characters is a little under fifty bits, which keeps every profile a facility
#: will ever write comfortably distinct while staying short enough that a person
#: can compare two of them by eye in a log line.
FINGERPRINT_LENGTH = 12

_LAYOUT_POINTER = "locations.json"


def the_records_folder(run_folder: Path | str) -> Path:
    """Where one run keeps its own descriptions, beside its images."""
    return Path(run_folder) / RECORDS_FOLDER


def _one_settled_line_of_text(payload: object) -> str:
    """Turn a record into text that comes out identical every time.

    Sorting the keys is what makes this dependable. Two dictionaries holding the
    same information can be written out in different orders, and if the order
    were allowed to vary then the same profile would fingerprint differently on
    two machines, which would defeat the entire purpose.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _short_hash(text: str) -> str:
    """A short, stable summary of a piece of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


# ---------------------------------------------------------------------------
# Naming a profile after everything it says
# ---------------------------------------------------------------------------


def fingerprint_of_a_profile(profile: AcquisitionProfile) -> str:
    """A short summary of everything this profile says about itself.

    Everything the profile records goes in: the axes, the frame, the pixel type,
    the voxel size and its unit, the colours, the overlap and the band it was
    chosen from, the arrangement of positions, both ownership policies, the
    analysis halo, every zoom level with its chunks and file bundles, and the
    compression. The only thing left out is the profile's own name, because the
    name is what is being worked out.

    Two profiles that agree on all of that get the same fingerprint on any
    machine and on any day. Two that differ anywhere at all get different ones.
    """
    described = profile.to_json()
    described.pop("profile_id", None)
    return _short_hash(_one_settled_line_of_text(described))


def name_for_a_profile(profile: AcquisitionProfile, *, readable_prefix: str) -> str:
    """A readable name for a profile, ending in its fingerprint.

    The prefix is there for people: ``confocal-1152-128`` in a log line says at a
    glance what kind of acquisition this was. The fingerprint after it is there
    for correctness, and it is not optional — whatever prefix a run chooses, two
    profiles that differ in any way still end up with different names.
    """
    check_the_name_is_safe(readable_prefix, what="acquisition profile")
    return f"{readable_prefix}-{fingerprint_of_a_profile(profile)}"


# ---------------------------------------------------------------------------
# Keeping a profile where it can be found again
# ---------------------------------------------------------------------------


def _profile_file(run_folder: Path | str, profile_id: str) -> Path:
    check_the_name_is_safe(profile_id, what="acquisition profile")
    return the_records_folder(run_folder) / "profiles" / f"{profile_id}.json"


def store_the_profile(run_folder: Path | str, profile: AcquisitionProfile) -> Path:
    """Write a profile beside the run, and return where it was written.

    This is the step that makes a published position mean anything later. Without
    it a commit record names a profile that exists only in the memory of the
    process that ran the acquisition, and once that process ends the pixels on
    disk have no description at all.

    Storing the same profile twice is deliberately harmless, so that setting a
    run up again — after a restart, or because the operator ran the setup step
    twice — is never a destructive act. Storing a *different* profile under a
    name that is already taken is refused, because a sealed description that
    could be replaced would not be sealed.
    """
    expected = fingerprint_of_a_profile(profile)
    if not profile.profile_id.endswith(expected):
        raise ZmartLiveError(
            f"Acquisition profile {profile.profile_id!r} does not end in the "
            f"fingerprint {expected!r} of its own contents. Storing it under "
            "that name would create a record this package refuses to load later. "
            "Create it through plan_the_writing() or name_for_a_profile() first."
        )

    for stored_id in stored_profile_ids(run_folder):
        if stored_id != profile.profile_id and stored_id.casefold() == profile.profile_id.casefold():
            raise ZmartLiveError(
                f"Acquisition profiles {stored_id!r} and {profile.profile_id!r} "
                "differ only by letter case and would be one file on a "
                "case-insensitive Windows microscope computer. Refusing to store "
                "the second prevents either profile from changing meaning."
            )

    where = _profile_file(run_folder, profile.profile_id)
    text = json.dumps(profile.to_json(), indent=2, sort_keys=True) + "\n"
    if where.exists():
        if where.read_text(encoding="utf-8") == text:
            return where
        raise ZmartLiveError(
            f"A different acquisition profile is already stored under the name "
            f"'{profile.profile_id}' in {where.parent}. A profile's name is worked "
            f"out from its contents, so two different profiles should never reach "
            f"this point sharing one. Rather than overwrite a description that "
            f"published positions may already point at, this refuses."
        )
    _put_in_place_in_one_step(where, text)
    return where


def load_the_profile(run_folder: Path | str, profile_id: str) -> AcquisitionProfile:
    """Read back the profile a published position names.

    The stored contents are fingerprinted again on the way in and checked against
    the name they were filed under. That catches the one failure this design
    cannot otherwise see: somebody opening the file and changing, say, the pixel
    type, leaving a description that quietly disagrees with the pixels while
    still carrying the name every commit points at.
    """
    where = _profile_file(run_folder, profile_id)
    if not where.exists():
        stored = stored_profile_ids(run_folder)
        raise ZmartLiveError(
            f"This run has no stored acquisition profile called '{profile_id}'. "
            f"It holds "
            + (f"{', '.join(stored)}." if stored else "no profiles at all.")
            + " A published position naming a profile that was never stored cannot "
            "be interpreted, so this is worth chasing rather than working around."
        )
    try:
        profile = AcquisitionProfile.from_json(json.loads(where.read_text(encoding="utf-8")))
    except ZmartLiveError:
        raise
    except Exception as trouble:
        raise ZmartLiveError(
            f"The acquisition profile stored at {where} could not be read: {trouble}"
        ) from trouble
    if profile.profile_id != profile_id:
        raise ZmartLiveError(
            f"The file for '{profile_id}' holds a profile calling itself "
            f"'{profile.profile_id}'. One of the two has been renamed by hand, and "
            f"there is no safe way to guess which is right."
        )
    expected = fingerprint_of_a_profile(profile)
    if not profile_id.endswith(expected):
        raise ZmartLiveError(
            f"The stored acquisition profile '{profile_id}' no longer matches its "
            f"own fingerprint; its contents summarise to '{expected}'. A profile's "
            f"name is worked out from its contents, so this means the file has been "
            f"edited since it was written and no longer describes the pixels that "
            f"were published under that name."
        )
    return profile


def stored_profile_ids(run_folder: Path | str) -> tuple[str, ...]:
    """The names of every profile this run has stored, in a settled order."""
    folder = the_records_folder(run_folder) / "profiles"
    if not folder.is_dir():
        return ()
    return tuple(sorted(path.stem for path in folder.glob("*.json")))


# ---------------------------------------------------------------------------
# Layout snapshots, which are written once and then left alone
# ---------------------------------------------------------------------------


def spatial_fingerprint_of_a_layout(layout: SceneLayoutRevision) -> str:
    """A short summary of what this snapshot says about the specimen.

    "Realized membership" in the architecture record means which tiles exist,
    where each one sits, which neighbours it turned out to have, and the exact
    regions each one owns — together with the policies that decided those
    regions. That is what a later measurement depends on, and that is what has to
    change before a new snapshot is worth making.

    The snapshot's own number and the time it was written are deliberately left
    out. Neither says anything about the specimen, and including them would make
    every repeat of an unchanged arrangement look like a change.
    """
    described = layout.to_json()
    for bookkeeping in ("revision", "created_at"):
        described.pop(bookkeeping, None)
    return _short_hash(_one_settled_line_of_text(described))


def _layout_file(run_folder: Path | str, revision: int) -> Path:
    if revision < 1:
        raise ZmartLiveError(
            f"Stored layout snapshots are numbered from one, so that 'revision 0' "
            f"can mean 'nothing recorded yet'; got {revision}."
        )
    return the_records_folder(run_folder) / "locations" / f"locations-{revision:06d}.json"


def stored_layout_revisions(run_folder: Path | str) -> tuple[int, ...]:
    """Every location snapshot this run has written, in order."""
    folder = the_records_folder(run_folder) / "locations"
    if not folder.is_dir():
        return ()
    numbers = []
    for path in folder.glob("locations-*.json"):
        try:
            numbers.append(int(path.stem.split("-", 1)[1]))
        except ValueError:  # pragma: no cover - a file somebody put there by hand
            continue
    return tuple(sorted(numbers))


def load_a_layout_revision(run_folder: Path | str, revision: int) -> SceneLayoutRevision:
    """Read back one numbered snapshot, exactly as it was written."""
    where = _layout_file(run_folder, revision)
    if not where.exists():
        stored = stored_layout_revisions(run_folder)
        raise ZmartLiveError(
            f"This run has no stored layout snapshot numbered {revision}. It holds "
            + (f"{stored}." if stored else "no snapshots at all.")
        )
    return SceneLayoutRevision.from_json(json.loads(where.read_text(encoding="utf-8")))


def latest_layout_revision(run_folder: Path | str) -> SceneLayoutRevision | None:
    """The newest snapshot, or ``None`` when nothing has been recorded yet."""
    stored = stored_layout_revisions(run_folder)
    if not stored:
        return None
    return load_a_layout_revision(run_folder, stored[-1])


def store_a_layout_revision(run_folder: Path | str, layout: SceneLayoutRevision) -> Path:
    """Write one numbered snapshot, and refuse to disturb one already there.

    Writing the same snapshot again is harmless: repeating a description is not a
    change. Writing a *different* one under a number that is already taken is
    refused, because that is precisely the act that would make an already
    published measurement start meaning something else.

    Most callers should use :func:`record_the_layout`, which works the number out
    for them. This is the guard underneath it, and it holds even when a caller
    chooses the number itself and gets it wrong.
    """
    where = _layout_file(run_folder, layout.revision)
    text = json.dumps(layout.to_json(), indent=2, sort_keys=True) + "\n"
    if where.exists():
        if where.read_text(encoding="utf-8") == text:
            return where
        raise ZmartLiveError(
            f"Layout snapshot {layout.revision} has already been written for this "
            f"run, and what is being offered now is different. Snapshots are never "
            f"edited: a measurement published against snapshot {layout.revision} has "
            f"to keep meaning what it meant when it was published. An arrangement "
            f"that has genuinely changed becomes snapshot "
            f"{layout.revision + 1} instead."
        )
    _put_in_place_in_one_step(where, text)
    return where


def record_the_layout(run_folder: Path | str, layout: SceneLayoutRevision) -> SceneLayoutRevision:
    """Store the arrangement, numbering it only when it has actually changed.

    This is the call a run makes each time it is about to publish something. Hand
    it the arrangement as it now stands and it does the right thing on its own:

    * The first arrangement of a run becomes snapshot 1.
    * An arrangement that differs from the newest stored one — a position has
      arrived, or moved, or the ownership policy has been settled differently —
      becomes the next snapshot. The earlier ones are left exactly as they were.
    * An arrangement that says the same thing as the newest stored one reuses
      that snapshot. This is the ordinary case in a timelapse: the next moment
      over tiles already in place has not moved anything, so it references the
      snapshot that exists and gets its own commit record instead.

    Returns the snapshot as it was actually recorded, carrying the number that
    was decided. Use *that* returned object when building a commit record, so
    that the commit refers to a snapshot which genuinely exists on disk.

    A copy of the newest snapshot is also left at ``locations.json`` in the
    records folder, replaced in one indivisible step, for readers that simply
    want the current arrangement without first working out which number is
    newest.
    """
    fingerprint = spatial_fingerprint_of_a_layout(layout)
    newest = latest_layout_revision(run_folder)

    if newest is not None and spatial_fingerprint_of_a_layout(newest) == fingerprint:
        recorded = newest
    else:
        recorded = replace(
            layout,
            revision=(newest.revision + 1) if newest is not None else 1,
            created_at=layout.created_at or now_in_words(),
        )
        store_a_layout_revision(run_folder, recorded)

    _put_in_place_in_one_step(
        the_records_folder(run_folder) / _LAYOUT_POINTER,
        json.dumps(recorded.to_json(), indent=2, sort_keys=True) + "\n",
    )
    return recorded
