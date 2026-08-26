# Two viewers, one contract: the module plan

This plan answers one design conversation (2026-08-15): a standalone
viewer that is its own product, the same canvas embedded in the operator
window, an "open" plugin that can precompute, views that may live apart
from their data, and the wish underneath all of it — modules that can be
used again in other places. It also answers the two questions the
conversation raised: do we need two contracts, and is everything live by
default?

The rule this plan is written under: simple solutions, compartmentalized,
nothing invented before something needs it.

## The three groups, named

The whole system is three groups of software, and the boundary between
any two of them is a folder of files, never an import:

1. **The microscope** writes `data/` — pixels, translations, and the
   member declaration. We do not own this pen; the tests impersonate it
   with `a_microscope.py`, which imports nothing of ours on purpose.
2. **The view builder** watches the declaration and constructs views —
   the view's `metadata/` (its fast restatement of what the data says)
   and its stores, baked or virtual. Today this is `zmart_live`'s
   publisher machinery plus `building/` (declare, governed, bake).
3. **The viewer** loads views and draws them — the serving doors, the
   patched engine, the frontend. Today this is `zmart-viewer`'s backend
   and frontend.

Group 2 talks to group 1 only by reading files; group 3 talks to group 2
only by reading files (and one optional hurry-up announcement). That is
why the pieces can be plugged in elsewhere: the interfaces are the
contract's folders, and folders travel.

## One contract, two doors

No second contract. A second contract would drift from the first the
week after it was written, and every module would then need to know
which one it is under. Instead the one contract has two **doors** — two
things a viewer may be pointed at:

- **The acquisition door** (smart microscopy): open an acquisition or an
  experiment. The viewer finds `data/` and `views/` side by side, the
  live view refreshes as the run grows, detections drive the stage. This
  is the operator-window use, and it is what everything so far builds.
- **The view door** (standalone): open ONE view folder. The view is
  self-contained by exactly the ladder the contract already defines:
  a *sealed* view carries its truth-slice and baked coarse levels and
  resolves fine detail through its data; a *materialized* view carries
  everything and needs nothing. Opening a view folder is opening a
  complete thing — the door does not care whether an experiment exists
  around it.

The one rule that makes views-apart-from-data legal without a second
contract: **data never knows about views; every view names its data.**
The view's `metadata/` records what it was built from (today
`governed_from`; tomorrow possibly a URL). Beside its data is where a
view *ideally* lives — but a view built from read-only ground (an
archive, a collaborator's share, one day a cloud store over HTTP — zarr
is served over HTTP natively, so this is an address change, not a
design change) simply lives wherever it was built and points home. The
arrow keeps its one direction either way.

## Live by default: yes, because live is observed, not declared

Nothing needs a live/not-live switch. **Live is a fact the declaration
reveals, not a property anybody sets.** Every opened view watches its
one declaration file (and the run's `signed.json` where there is one);
if the numbers move, the view refreshes — that is all "live" ever meant.
For finished data the watch costs one file stat per poll and never
fires. Sealing is therefore not "turning live off"; it is the record
stating that it has stopped, plus a stamp of the moment. One code path,
no mode flag, and a viewer pointed at a ten-year-old archive and a
running acquisition behaves identically — one of them just never hears
news.

## The standalone viewer, concretely

One application, assembled from the same modules the operator window
uses, plus one small plugin:

- **The opening plugin** is the only new piece. Point it at data (or at
  an existing view). If it is data, the plugin calls the view builder:
  *make me a view of this* — with one choice, **precompute or not**
  (bake the canvas pyramid now, or serve it on the fly), a **progress
  bar** (the builder already counts pieces; progress is piece counts,
  not guesswork), and at the end it **says where the view was saved**
  (beside the data when writable, in the viewer's own views home when
  not — recorded in the view's metadata either way). If it is already
  a view, it just opens.
- Everything after the plugin IS the existing viewer: same doors, same
  engine, same refresh, same gates guarding it.

The operator-window version embeds the same canvas component and skips
the plugin — the smart-microscopy loop already knows its views.

## The module map (what exists, what moves, what is new)

| Module | Today | Becomes |
| --- | --- | --- |
| data writer | vendor's / `a_microscope.py` (tests) | unchanged — never ours |
| view builder | `zmart_live` publisher + `building/` declare/governed/bake | one importable package with a progress callback; CLI wrapper for the plugin |
| serving doors | `zmart-viewer/app/server` | unchanged; already keyed off files |
| canvas component | `zmart-viewer/app/page` | exported as an embeddable component (it already speaks only HTTP to the doors) |
| opening plugin | — | new, small: UI over the view builder's CLI/progress |

No module imports across a group boundary; each is testable alone
(the suites already test them alone — that is what this campaign built).

## Review of this plan, adversarially

- *Is the view door real or aspirational?* Real at the sealed and
  materialized rungs today (a declared baked picture is exactly a
  materialized coarse view; the gates open one every run). The
  bookmark rung through the view door needs the declaration watcher,
  which is also what live-by-default needs — one small piece, two
  wishes served.
- *What could force a second contract anyway?* Only remote data whose
  members cannot be addressed by relative path. The answer stays inside
  the one contract: the view's metadata names its data by address, and
  an address may be remote. If that ever strains, the strain will be in
  ONE field of ONE file, not across the tree.
- *What is deliberately not planned?* Cloud serving, multi-user, any
  UI beyond the opening plugin. The modules make them possible; nothing
  here depends on them.
- *Biggest real risk:* the view builder is today entangled with the
  publisher (one package does both pens). The conversion already drew
  the line on disk; drawing it in the code is the cleanup chapter's
  job, and the acceptance gates make it safe to do late.

## The example, when it is time

A separate project, `zmart-viewer/`, roughly:

    zmart-viewer/
    ├── viewer/        the canvas component (frontend build, embeddable)
    ├── doors/         the serving backend
    ├── builder/       the view builder as a library + CLI
    └── open-plugin/   the standalone app: pick data → choose precompute
                       → progress → "your view is at …" → view opens

built by moving the modules named above, not by rewriting them — the
suites come along and must stay green through the move. That project
starts after the GPU pass closes this chapter; nothing in it blocks, or
is blocked by, the work in flight.
