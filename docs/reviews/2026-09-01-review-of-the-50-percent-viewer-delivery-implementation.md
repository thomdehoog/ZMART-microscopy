# Review of the 50% viewer-delivery implementation

**Date:** 2026-09-01.
**What was reviewed, as code:**

- ZMART-microscopy, `thomdehoog/ZMART-microscopy`, branch
  `claude/viewer-port-remaining-steps-ofm5qp`, commit `ca8e176d`
  ("implement half of viewer display contract");
- ZMART Viewer, `thomdehoog/zmart-viewer`, branch
  `codex/viewer-delivery-50-percent`, commit `d243736`
  ("implement acquisition-wide display windows"), whose parent is the released
  `9ff10b0` (version 0.2.0).

**Read alongside:** `docs/design/viewer-delivery-implementation-plan-50-percent.md`
and its review prompt at `ca8e176d`, `docs/design/lazy-jpeg-pyramids-for-the-viewer.md`
at `f1e7190a`, and the two earlier reviews at `48f72d64` and `e73aa7f1`.

**How it was reviewed:** both commits were checked out into fresh worktrees and
clones; neither working folder was touched and neither implementation branch was
changed. Tests were run (section 8). Two failing tests and one differential
probe were written as review evidence only; they are reproduced in full below
and were not committed to either implementation branch.

**Verdict: revise before continuing.**

Three things stand in the way. One is a regression against the released Viewer
that stops a picture opening at all; one can lose a whole scan without saying
so; and one means the single objective this work exists to meet — no camera
range for an unresolved acquisition — is still not met on the live path. None
of the three is deep, and the parts that are right are genuinely right: the two
independent validators agree on every adversarial document put to them, the
browser evidence is real and passes, and the descriptor contract itself is well
shaped.

Throughout, an **observed** fact is one read in the code or produced by a test
run named here. An **inference** is labelled as such.

---

## 1. Blocking findings

### B1. A descriptor whose channel count disagrees with the pixels loses every position, silently

This is the most serious finding, because its failure mode is the one this
project has already spent weeks on: everything reports success and nothing is on
the screen.

The chain, observed:

1. `application/framework/bridge.py:840-846` publishes the descriptor from the
   browser's `/api/scan` payload, using
   `acquisition_description(acquisition_type, channels)`.
2. `application/parts/storage/acquisition_description.py:172-181` derives
   `channel_count` **from the document itself** — `len(document["channels"])` —
   so the count is validated against nothing. A browser that declares two
   channels for a three-channel job is accepted, and the scan starts.
3. Each landing calls `position_store_from_record`, which at
   `application/parts/storage/zarr_positions.py:120-124` re-validates the
   sidecar against the channel count of the pixels actually captured, and
   raises.
4. `application/framework/bridge.py:726-731` catches every exception from that
   call, writes `record["zarr_error"]`, and **returns without calling
   `viewer_service.a_position_landed`**.
5. `zarr_error` is never shown. The only other place in the repository that
   reads it is `application/parts/microscope/focus_score.py:93`, which uses it
   to fall back to plane files.

So: the stage drives the whole scan, the vendor TIFFs are written, the step
reports every tile, and not one OME-Zarr position exists. Nothing on screen, in
the panel, or in the run's own error field says why.
`docs/reviews/2026-09-01-why-the-acquired-overview-never-appeared.md` opens with
that exact sentence — "every one of them reported success" — and this
implementation adds a new way to produce it.

**What to change.** Two independent fixes, both wanted:

- Check the channel count against the acquisition before the scan starts. The
  job/state that the scan is about to apply knows how many channels it records;
  `acquisition_description()` should take that count as an argument rather than
  reading it off the document.
- Make a descriptor-caused conversion failure loud. `_keep_position_as_zarr`'s
  swallow is right for a vendor file that cannot be read — the pixels are on
  disk and the conversion can be re-run — and wrong for a contract that will
  fail identically for every remaining position. Distinguish them, and stop the
  scan on the second kind.

### B2. `read_the_transfer` now refuses folders that composed a picture before

Observed, and reproduced against both commits (evidence in section 7).

`zmart_viewer/acquisition.py:285-291` raises `ValueError` when positions
disagree, and `zmart_viewer/compose.py:558-570` calls it with no guard. Two
ordinary legacy shapes now stop a transfer opening at all:

- **one position with no `omero` block beside positions that have one.** The
  identity tuple for a position without metadata falls back to
  `f"channel {index + 1}"` with no colour (`acquisition.py:277-283`), which
  differs from a described position, so the reconciliation raises "the positions
  disagree about channel count, labels, colours, ranges, or visibility".
- **positions differing only in a non-channel `omero` key.**
  `acquisition.py:271-273` copies every `omero` key except `channels` into
  `other_omero` and demands strict equality across positions
  (`acquisition.py:285-287`). Foreign OME-Zarr routinely carries a per-image
  `id`, `name`, and `version` in that block. Channel metadata identical, picture
  refused.

Both cases pass at `9ff10b0` and fail at `d243736`. The old code took the first
readable `omero` and carried on; the new code refuses the whole picture.

Two aggravating details. The `try/except ValueError: continue` that used to
wrap `_the_description_of(tile.store)` was removed in the same hunk, so one
unreadable position description now fails the transfer rather than being
skipped. (*Inference:* tile construction earlier in `read_the_transfer` probably
already requires a readable description, so this may be unreachable — but the
guard was deliberate and its removal is not discussed.) And
`zmart_viewer/compose.py:566` takes `channel_count` from `next(iter(rooms))[1]`,
which is safe only because `len(rooms) > 1` is refused six lines above.

**What to change.** A legacy disagreement must degrade, never refuse. The
composed source's job here is to decide a *window*; failing to decide one means
carrying no declared window and letting the Viewer measure — which is precisely
what the plan says ("if only `start`/`end` disagree, preserve shared identity and
range but omit the display pair"). Compare only the fields the contract names —
label, colour, range, visibility, per channel — and ignore everything else in
the `omero` block. Reserve refusal for a disagreement that would make the drawn
picture wrong, and even then prefer omitting metadata to withholding pixels.

### B3. The camera-range fallback is still there, one layer up, on the live path

The objective this whole work package exists to meet is that missing display
information stays explicitly unresolved. V1 achieves that in the *reader*:
`zmart_viewer/contrast.py:320-326` and `:551-556` now return `None` instead of
`(0.0, 65535.0)`. Observed and correct.

But the *writer* still manufactures the same numbers, and the plan's own gate
legitimises them. `zmart_viewer/record/model.py` (`Channel.described`, around
lines 1719-1721 — and the identical `zmart_storage/canvas.py:1070-1072` in this
repository) writes:

```python
window = {"min": 0, "max": depth_max}
window["start"], window["end"] = self.window or (0, depth_max)
```

That is the camera range as a *declared* display window whenever a run named no
window. `zmart_viewer/record/omezarr.py:373-385` (`the_channels_described`) calls
it for every channel of a manifest-governed run; `zmart_viewer/live.py:543` feeds
the result into `_display_for` at `:548-560`, which passes the numeric pair
straight into the live config row. `contrast._omero_window` then honours it,
because it is a complete `start`/`end` pair.

So a live, manifest-governed run whose channels declare no window still opens
very nearly black — and V1's gate cannot detect it, because the gate says "a
declared `0…65535` window remains valid only when the source explicitly wrote
both `start` and `end`", and this source did write both.

The plan lists `zmart_viewer/live.py` as a V1 target with the note "preserve
`_display_for`'s absent channel window through live rows". `_display_for` does
preserve `None` correctly. Nothing upstream ever produces one. V1 is nominally
done and substantively half done.

**What to change.** This is the other half of V1, and the descriptor already
contains the mechanism: `windowProvenance` is exactly how a reader tells
"declared because somebody chose it" from "declared because nothing was known".
Either extend the acquisition-profile path to carry that provenance, or stop
those writers emitting a whole-range display pair. Do not leave the decision to
a gate that reads the value without its provenance.

### B4. M3 as planned would write OME-Zarr that ngio refuses

Not yet code, but decided in the plan and already half-built, so it belongs here
rather than in the forward plan.

The plan's M3 section says: "unresolved descriptor: write `min`/`max` but omit
`start`/`end`". `zmart_storage/canvas.py:1050-1058` records a checked experiment
against exactly that shape:

> a describing block with an incomplete window is refused outright. Checked
> against ngio, a block naming a channel without `start` and `end` fails to open,
> while the same image with no describing block at all opens perfectly well.

ZMART reads its own position stores with ngio — focus scoring was moved onto
them for that reason. And `ome_channel_blocks`
(`acquisition_description.py:246-262`) already produces the forbidden shape
whenever `fallback_windows` is `None`; today the M1 compatibility hint always
supplies one, which is the only thing keeping it out of the files.

**What to change.** Settle this before writing M3. Either an unresolved
acquisition writes **no** `omero` channel block at all — accepting the loss of
labels and colours, which is what that docstring concluded last time — or the
ngio finding is re-checked against the pinned version and the evidence recorded
beside the decision.

---

## 2. Important findings

### I2. The descriptor is published in three places, from three folder derivations, and one of them is dead

Observed:

- `bridge._start_scan` writes to `_the_run() / "positions" / acquisition_type`
  (`bridge.py:843-845`), before the scan thread starts. Correct, and it is the
  folder the positions land in (`bridge.py:727`).
- `capture_run.capture_positions` writes to
  `Path(output_root) / "positions" / acquisition_type`
  (`capture_run.py:93-99`), before the first `set_state` and the first move.
  But `capture_positions` never writes position stores: it prepares
  `<experiment>/<type>/data` through `prepare_acquisition`
  (`output.py:75-86`, which has no `positions/` level) and moves vendor files
  there. `position_store_from_record` is called from exactly one place in the
  whole repository — `bridge.py:728`.
- `position_store_from_record` publishes again on every landing
  (`zarr_positions.py:120-124`).

So the in-process publication is either an exact duplicate of the bridge's (when
`output_root` happens to be the run folder) or writes a contract into a folder
nothing populates. Neither is intended behaviour anyone chose.

And nothing in production supplies `channels` at all: the only callers of
`scanOverview` are `application/framework/window/main.js:605` and `:743` and
`application/parts/microscope/backend-contract.js:295`, none of which pass it.
The plan says this is deliberate — the real Leica source is unwired on purpose —
which is a reasonable decision, but it means the descriptor path has never run
outside tests.

**What to change.** One publisher, named, at run start, on the path that writes
positions. The per-landing call becomes a read-and-verify, not a write.

### I3. Atomic replacement is not durable, is not locked, and can leave litter

`write_acquisition_description` (`acquisition_description.py:213-227`) writes a
uniquely named sibling with `open("x")`, `flush`, `os.fsync`, then `os.replace`.
Three gaps against the review objective:

- **The directory is never fsynced.** After `os.replace` the file's contents are
  durable but its name may not be. A power loss on the microscope PC can leave a
  run whose positions exist and whose descriptor does not — which does not fail,
  it silently falls through to legacy consensus and changes the picture's
  windows.
- **There is no lock.** The immutability check reads the existing file
  (`:218-224`) and then writes; two processes that both see no file each write a
  different document and one wins silently. The plan's own rule is that a
  differing attempt is "refused before another position is written".
- **A killed process leaves a stale temporary.** `finally: unlink(missing_ok)`
  covers an exception, not a `SIGKILL` between create and replace. The leftover
  `.zmart-acquisition.json.<hex>.tmp` sits in the folder the Viewer scans, and
  nothing sweeps it.

*Inference, not observed:* the Viewer's collection scan globs `*.zarr`
(`compose.py:497-501`), so a stray dotfile should be ignored; worth a test
rather than an assumption.

### I4. The microscopy reader validates a document against itself

`read_acquisition_description` (`acquisition_description.py:186-201`) defaults
both `acquisition_type` and `channel_count` from the document being validated,
so for a bare `read_acquisition_description(folder)` the folder-name check and
the pixel-count check are no-ops. A descriptor naming `targets` sitting in the
`overview` folder reads clean.

The Viewer's twin is strictly better: `acquisition.py:178-189` requires
`channel_count` and always passes `folder.name`. Make the microscopy reader
match it. (The one place that does pass both is `zarr_positions.py:126-128`,
which is why this has not bitten yet.)

### I5. A corrupt store and an empty one are now indistinguishable to the operator

`tests/test_contrast.py` replaced a fallback whose docstring explained why it
existed: "A store that cannot be read must not stop the viewer from opening…
the fallback is a window covering the full range of the data type, which shows
*something*." That fallback was wrong, and removing it is right.

What replaced it, though, gives a store containing `{ this is not json` and a
valid live store with no pixels yet the same answer — `window: null`,
`histogram: null`, `settled: false` — and therefore the same words on screen,
"waiting for measurable pixels". The broken one waits forever.

This repository already has the principle, in
`zmart_viewer/tests/test_a_fault_is_not_absence.py`:

> A fault while answering must not be served as the truth about the ground. …
> So the server keeps the two answers apart.

The same distinction is now owed to brightness. `measure` knows which case it is
in — `_samples` returns `None` both for a missing store and for a store whose
levels hold no pixels, but the two are separable at that point — and the panel
should say "this acquisition cannot be read" rather than "waiting".

### I6. `settled` is written into every config row and read nowhere

`contrast.Measurements._measure` now emits `"settled": bool(found.get("settled"))`
(`contrast.py:677`). No file under `app/page/src/` references it — searched.
So a provisional measurement taken from a partly written run is presented
exactly like a resolved one, which is the state V1 was added to make visible.
Either wire it into the panel or drop it; a field that exists and is ignored
will be assumed to work.

### I7. Display provenance is merged into the picture's own `zmart` namespace

`building.py:136` and `:198` changed `described["attributes"][OURS] = {...}` to
`setdefault(OURS, {}).update({...})`, so `acquisitionDisplaySchema`,
`acquisitionType`, `displayWindowSource` and `displayWindows` now share one
object with the picture's own `what`, `held`, `piece`, `tiles`, `baked` — and the
picture's keys win on collision. Nothing collides today. Give the display
contract its own key (`zmart.display`) before something does.

### I8. The source can disagree with its own provenance

Two places in `zmart_viewer/acquisition.py`:

- `source_metadata:197-201` — a channel with a `displayWindow` but no `range`
  cannot happen (validation forbids it), but a channel with neither emits no
  `window` key at all, so the composed channel carries a label and colour and
  nothing else. Whether ngio accepts that shape is the same open question as B4.
- `legacy_source_metadata:299-311` — when positions agree on a display pair but
  declare no `min`/`max`, the consensus pair is recorded in `displayWindows`
  provenance and never written into `omero`. The source then says, in one place,
  that a window was resolved, and in the other that none exists.

### I9. The contract is bound to a folder name

Both validators require `acquisitionType == folder.name`
(`acquisition_description.py:207-212`, `acquisition.py:75-81`). For
`positions/<type>` that is exactly right and it is a good check. But
`read_the_transfer` also serves the plate path (`compose.py:492-495`), where the
folder is not an acquisition type, and the coupling is nowhere stated. Pass the
expected type from the caller that knows it, defaulting to the folder name.

---

## 3. Minor observations

- **Off-by-one in the legacy channel label.** The Viewer's fallback is
  `f"channel {index + 1}"` (`acquisition.py:280`) and the operator page uses the
  same (`steps/scan_the_overview/overview.js:193`), while the position writer
  names channels `f"channel {index}"` (`zarr_positions.py:150`). Harmless today,
  confusing on the day somebody compares two labels.
- **Unknown fields are handled three different ways.** Dropped at the top level,
  dropped per channel (a fresh dict is built), preserved inside
  `windowProvenance` (`deepcopy`). One consequence worth knowing: because the
  immutability check compares canonical forms, republishing with different
  unknown fields is accepted as identical.
- **The remaining `65535` in `LayerPanel.jsx`** (lines 137, 256, 809) are axis
  bounds and the image range, not display windows. That is correct and matches
  the plan's "camera range remains available separately as `range`". A one-line
  comment saying so would stop the next reader filing it as a violation.
- **`ome_channel_blocks` drops what `Channel.described` added.** With a
  descriptor, a channel's block is `{label, window, color?}`; without one it is
  whatever `Channel.described` builds, which always includes a colour (falling
  back to `_CHANNEL_COLORS` by name, then white). A descriptor that omits
  `color` therefore produces a position store with no colour where the previous
  writer always wrote one.

---

## 4. What was checked and is right

These were verified rather than assumed, and they are the reason this is a
"revise" and not a "start again".

- **The two validators agree.** A differential probe (section 7) put 24
  adversarial documents through
  `application/parts/storage/acquisition_description.validate_acquisition_description`
  and `zmart_viewer.acquisition.validate_acquisition_description`: unknown fields
  at three levels, booleans as numbers, `NaN` and `Infinity`, duplicate keys,
  duplicate indices, shuffled indices, indices not starting at zero, seven-digit
  and `#`-prefixed colours, whitespace-only keys, padded labels, a degenerate
  range, a window without a range, a negative `sampleCount`, a non-string
  `algorithm`, and `channels` as an object. **Zero disagreements** — identical
  accept/reject, and byte-identical canonical output on every acceptance.
- **Publication happens before the stage moves,** on both paths that publish
  (`bridge.py:840-846` before the scan thread starts;
  `capture_run.py:93-99` before `set_state` and before the loop). The
  cancellation test at `test_capture_run.py:127` proves the descriptor is
  complete before the first move.
- **Immutability and idempotency work and are tested.** A second identical
  publication returns the same path and does not touch `st_mtime_ns`; a changed
  one raises without altering the first
  (`test_acquisition_description.py:50-71`).
- **V1's browser evidence is real.** `test_contrast.py::test_an_empty_live_source_says_it_is_waiting_instead_of_showing_camera_range`
  drives a real Chromium against a served, valid, pixel-empty live store and
  asserts the waiting text and the absence of min/max controls. It is skipped in
  a plain checkout; built and run here, it passes.
- **The `uint8` door is not closed.** `compose.codecs_for:663-665` already emits
  the one-byte codec chain without an endianness declaration, so a future whole-
  `uint8` picture needs no codec work, and `source_metadata`'s clean separation
  of `range` from `displayWindow` is exactly what such a picture would need to
  translate its controls. This answers question 7: nothing added here makes that
  experiment harder, and two things make it easier.
- **Geometry, Z, and pixels are untouched.** The diffs contain no change to
  levels, decimation, corners, transforms, or `_the_corner_of`. Confirmed by
  reading both diffs in full.

---

## 5. Milestone assessment, and whether "50%" is defensible

| Package | Claimed | Observed |
|---|---|---|
| V1 — absent window | implemented | **half.** Reader correct; the writers still declare the camera range (B3), fault and absence collapsed (I5), `settled` unread (I6). |
| V2 — composed authority | implemented | **descriptor path yes; legacy path regressed** (B2). |
| M1 — write the descriptor | implemented | **library yes, integration no.** Well tested in isolation; three publishers (I2); unsafe on a count mismatch (B1); unwired in production. |
| I1 — one authority end to end | partial | partial, as claimed. |
| M2, M3, S1, H1, Z1 | not started | not started. `zmart_viewer/scratch.py` does not exist. |

**"50%" is not defensible as stated.** Counting three of six packages plus part
of a fourth requires V1 and V2 to be complete, and neither is. A fair name for
what has been reached is:

> *The contract exists, is specified, and is validated identically on both
> sides. One consumer path reads it correctly. Nothing in production produces
> it, and one previously working consumer path regressed.*

By the plan's own dependency order that is roughly **30–35%** — the reader half
of V1, the descriptor half of V2, and M1 as an unwired library.

---

## 6. From here to about 80%, in dependency order

Each step lands on its own, with its own evidence. No step may start before the
one above it is deployed.

0. **Fix B2 and release it alone.** It is a regression against `9ff10b0`, so it
   blocks any Viewer release, including one that carries nothing else. Legacy
   reconciliation degrades to "no declared window"; it never refuses a picture.
   Add the two cases from section 7 as permanent tests.
1. **Fix B1.** `acquisition_description()` takes the acquisition's real channel
   count; a descriptor-caused conversion failure stops the scan and says so
   instead of being filed on a record nobody reads.
2. **Finish V1.** B3 first — decide whether an undeclared profile channel stops
   writing a whole-range display pair, or carries provenance that lets a reader
   tell it from a chosen one. Then I5 (a fault is not absence) and I6 (use
   `settled`, or remove it).
3. **Settle B4 before any M3 code.** Re-run the ngio check against the pinned
   version, record the result beside the decision, and choose between "no omero
   block" and "no `start`/`end`".
4. **Consolidate publication.** One publisher (I2), a strict reader (I4), a
   directory fsync and a lock (I3), and a swept temporary file.
5. **Wire one real source of channel descriptions.** Until something in the
   operator path supplies `channels`, M1 has never run outside tests. This is
   the plan's open decision 2 and it should be closed here, not later.
6. **M2.** The embedded panel gains the same waiting behaviour, and the
   capability handshake (`acquisition-display-window-v1` plus
   `absent-display-window-v1`) refuses the integrated canvas at startup against
   an older Viewer, with a plain upgrade sentence.
7. **Only then M3.**

S1 (session scratch) and Z1 (the `z=0`/`z=0.5` evidence) are independent of all
of the above after step 2 and can run in parallel.

### Evidence required before `_a_window_onto` may be removed

1. M2 deployed, and the capability handshake observed refusing an old Viewer.
2. B4 resolved, with the ngio check recorded against the pinned version.
3. One real bridge-driven run in which the descriptor, every position's mirrored
   OME window, the composed source, the standalone config, and the embedded
   panel all show the same window — the plan's five equalities, in a screenshot.
4. The legacy-disagreement fixture opening and measuring provisionally, not
   refusing.
5. `measure/measure_cold_open.py` before and after, showing that a declared
   window removes the pixel reads done only to choose opening brightness. This
   is the number that makes the contract pay for itself.

### Answers to the remaining questions

- **Old Viewer + new Microscopy:** safe *only* because M1 still stamps the
  per-position window; the sidecar is an ignored file. Confirmed by reading
  `9ff10b0`, which never opens `zmart-acquisition.json`.
- **New Viewer + old Microscopy:** unsafe today, for B2's reason, not for the
  window's — an older run whose positions carry heterogeneous `omero` blocks
  refuses to open.
- **Is retaining `_a_window_onto` the right compatibility decision?** Yes, and it
  should be retained past M2 as well, until step 5 has produced a real
  descriptor on a real run.
- **Storage roots (question 8):** still outside the accounting rules.
  `zmart_viewer/scratch.py` does not exist and `server.py::_a_session_folder` is
  unchanged, so `~/.zmart-viewer/scenes` and `replays` are as they were in the
  previous review.

### Deliberately deferred, and still correct to defer

JPEG in any form; request-time content negotiation on a Zarr array; any
`uint8` picture before a measured comparison; removing per-position windows
before the handshake; any change to pixel pyramids, decimation, or Z transforms;
and treating stage or focus Z as registered specimen placement.

---

## 7. Review evidence

Neither file below was committed to an implementation branch. Both are
reproducible from a clean checkout.

### 7a. Two legacy shapes that regressed (B2)

Save as `tests/test_review_evidence.py` in a checkout of the Viewer and run
`python3 -m pytest tests/test_review_evidence.py -q`. It passes at `9ff10b0` and
fails at `d243736`.

```python
"""REVIEW EVIDENCE ONLY. Runs unchanged at 9ff10b0 and at d243736."""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_a_transfer_is_built_into_one_picture import a_transfer  # noqa: F401
from zmart_viewer.compose import read_the_transfer

ONE = [{"label": "GFP", "color": "00FF00",
        "window": {"min": 0, "max": 65535, "start": 200, "end": 3200}}]

def _omero(store: Path, block: dict) -> None:
    held = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    held["attributes"]["ome"]["omero"] = block
    (store / "zarr.json").write_text(json.dumps(held), encoding="utf-8")

def test_a_position_without_omero_beside_positions_with_it(a_transfer: Path):
    for at, position in enumerate(sorted(a_transfer.glob("*.ome.zarr"))):
        if at:
            _omero(position, {"channels": ONE})
    assert read_the_transfer(a_transfer).omero is not None

def test_positions_differing_only_in_a_non_channel_omero_key(a_transfer: Path):
    for at, position in enumerate(sorted(a_transfer.glob("*.ome.zarr"))):
        _omero(position, {"id": at, "name": position.name,
                          "version": "0.4", "channels": ONE})
    assert read_the_transfer(a_transfer).omero is not None
```

Observed:

```
--- zmart-viewer @ 9ff10b0 ---   2 passed
--- zmart-viewer @ d243736 ---   2 failed
    ValueError: the positions disagree about their non-channel OME display metadata
    ValueError: the positions disagree about channel count, labels, colours, ranges, or visibility
```

### 7b. The validator equivalence probe

A standalone script that imports both validators and puts the same 24 documents
through each, comparing accept/reject and the canonical output. Observed result:
**24 cases, 0 disagreements.** The cases are listed in section 4; the script is
short enough to reconstruct from that list, and is worth keeping as a shared
fixture rather than as a one-off.

**Recommendation on the two validators.** Keeping them is acceptable *for now* —
they agree today, and a shared package across two repositories would be its own
coupling. But agreement was demonstrated by a probe that lives nowhere. Before
M2, add one **shared JSON fixture directory** — a set of documents, each with
its expected verdict and, for accepted ones, its expected canonical form — vendored
into both repositories and asserted by a test in each. That catches drift on the
day somebody edits one validator, which is the only day it matters.

---

## 8. Tests run

Environment: Linux container, Python 3.11, numpy 2.4.6, zarr 3.1.6, software
rendering. `numpy`, `zarr`, `tifffile`, `scikit-image`, `pooch`, `pytest`, and
`playwright` were installed to make the suites runnable; the Viewer page was
built with `npm --prefix app/page run build`.

| Suite | Result |
|---|---|
| microscopy `application/parts/storage` + `application/framework` | 89 passed |
| microscopy `application/parts/microscope/test_capture_run.py` | 9 passed |
| Viewer `test_a_transfer_is_built_into_one_picture.py`, `test_contrast.py`, `test_harsh_omezarr.py` | 86 passed, 1 skipped (browser, before the page was built) |
| Viewer `test_the_window_a_run_asked_for_reaches_the_screen.py`, `test_brightness_is_measured_honestly.py`, `test_an_acquisition_folder_offers_one_image.py`, `test_a_plate_lays_itself_out.py`, `test_acquisition_groups.py`, `test_server.py` | 66 passed, 5 skipped |
| Viewer V1 browser test, page built, real Chromium | 1 passed |
| Viewer full suite (`tests/`, less the transfer file already run above) | **539 passed, 321 skipped** in 16m 40s |
| Review evidence 7a at `9ff10b0` / at `d243736` | 2 passed / **2 failed** |
| Validator equivalence probe, 24 documents | 0 disagreements |

The full Viewer suite is green on the Python side: no non-browser regression
anywhere. But **321 of its tests were skipped**, and those are the browser tests
— the ones the suite's own closing message calls "the only part of this suite
that catches the fault this project keeps meeting: a picture that is silently
absent". They skipped because that run started before the page was built. So the
539 passes do not tell us whether the composed picture still *draws*, which is
exactly the question B2 raises.

Not run: the 321 browser tests as a set, the ZMART-microscopy Playwright walks,
and anything on the microscope PC. **Before B2's fix is judged complete, run the
Viewer suite with the page built and `ZMART_REQUIRE_BROWSER=1` set**, so that a
missing browser fails the run instead of quietly passing it. The V1 evidence is
one of the tests that variable protects, and it does pass when actually driven —
verified here.

---

## 9. Instructions to the main process

Paste-back summary.

```text
Verdict: revise before continuing. Do not merge as the first half of the
migration yet. Nothing needs redesigning; four things need fixing.

Fix in this order, each landing on its own:

1. VIEWER, alone and first. legacy_source_metadata must never raise. A
   disagreement between positions means "no declared window", not "refuse the
   picture". Compare only label, colour, range and visibility per channel;
   ignore every other omero key (foreign runs carry per-image id/name/version).
   Restore tolerance for a position with no omero block, and for one whose
   description cannot be read. Two failing cases are in section 7a of the review
   — add them as permanent tests. This is a regression against 9ff10b0 and
   blocks any Viewer release.

2. MICROSCOPY. acquisition_description() must take the acquisition's real
   channel count rather than reading it off its own document, so a wrong count
   is refused before the scan starts. And _keep_position_as_zarr must not
   swallow a descriptor-contract failure: that failure will repeat for every
   position, so it stops the scan and says so. Today a wrong count writes a
   whole scan's TIFFs, reports every tile, and produces no position stores, with
   nothing anywhere to say why.

3. VIEWER. Finish V1. contrast.py is right; record/model.py Channel.described
   still writes start/end = 0..depth_max whenever a run declared no window, and
   live.py serves it as a declared window. Decide: stop writing that pair, or
   carry provenance so a reader can tell it from a chosen one. Also: a corrupt
   store and an empty one must not both say "waiting for measurable pixels", and
   the new "settled" field is currently emitted and read nowhere.

4. BOTH. Settle the M3 question before writing M3: canvas.py's own docstring
   records that ngio refuses a channel block with min/max and no start/end,
   which is exactly what M3 plans to write. Re-check it against the pinned
   version and record the answer.

Then: one publisher instead of three (capture_run's write is on a path that
never creates position stores), a strict reader in microscopy, a directory
fsync and a lock around publication, and finally a real source of channel
descriptions — until something in the operator path passes `channels`, none of
this has run outside tests.

Keep: the descriptor schema, both validators (they agree on 24 adversarial
documents, verified), immutability and idempotency, the browser evidence,
publication before the stage moves, and every deferral — no JPEG, no
negotiation on a Zarr array, no uint8 before measurement, no removal of
_a_window_onto before the capability handshake.

Call the milestone what it is: the contract exists and is validated identically
on both sides; nothing produces it and one consumer path regressed. That is
about 30-35%, not 50%.
```
