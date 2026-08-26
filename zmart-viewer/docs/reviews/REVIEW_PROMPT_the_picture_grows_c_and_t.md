# Review prompt: the picture grows channels and time

You are asked to review a **plan**, before anything is built. Nothing in it
is implemented; your findings are cheapest right now. Please attack the
design, its premises, and its test matrix — in that order of value — and
report findings numbered, most severe first, each saying plainly whether it
is something you can show (with the file and line, or the arithmetic) or
something you suspect. A finding that names a failure the plan would ship
is worth ten wording notes.

## What to read, in order

All on branch `claude/thy1-linked-spiral`, in `zmart-viewer/`:

1. `building/PLAN_the_picture_grows_c_and_t.md` — the plan under review.
2. `building/CONTRACT_the_files_the_viewer_needs.md` — the file contract
   the plan stands on, especially the per-(t, c) chunk rules and the
   collection declaration.
3. `tests/test_a_survey_grows_in_a_spiral.py` — the record-level colours-
   and-moments gates the plan claims already carry most of the truth.
4. `zmart_live/tests/test_a_replacement_advances_every_moment.py` — the
   O(moments) replacement spike the plan leans on as "already pinned".
5. `building/PLAN_close_the_neuroglancer_chapter.md` — the flat picture's
   measured numbers and the (t, c) checklist it already carried.
6. `building/PLAN_the_picture_grows_a_z_axis.md` — the sibling depth plan,
   revised after two reviews; the c-and-t plan inherits decisions from it
   and must not contradict it.

Chase claims into the code: `app/picture/declare.py` (the multi-channel
refusal and what the description declares), `app/picture/governed.py` (the
per-commit patch the bake rules extend), `app/picture/composer.py` (what a
compose actually reads), `zmart_live/coordinator.py` and `profiles.py`
(what the writer commits and refuses), `app/server/server.py` (the frames
counting and time slider the plan says already exist).

## The claims to attack

1. **"Most of the truth already exists."** The plan says the (t, c) file
   contract, the record, the arrival signal, and the viewer controls are
   all in place, and only serving is missing. Find what that list forgets.
2. **The derive "is address plumbing, not new truth."** A piece request
   carries (t, c) and the composer reads one frame per tile. Is that true
   of the shipped composer and its caches — the slabs, the pins, the
   inheritance keys — or does (t, c) multiply state somewhere the plan
   calls bookkeeping?
3. **The bake follows the moment being written.** Old moments bake on
   first visit; nothing per-landing scales with timelapse length. Attack
   both halves: what does "first visit" cost on a long timelapse, who
   pays it, and is the no-O(t)-per-landing claim honest against the
   shipped patcher loops?
4. **The declared room for time.** The plan leans to a generous ceiling
   with absence expressing the tail, and defers the decision to the
   reviews. Force it: what does the ceiling cost in the shipped code
   (description size, patcher walks, slider UI), what does an open-ended
   run do the day the ceiling is reached, and is the writer's refusal
   message actually a remedy?
5. **The channel axis specifically.** Channels are few but always viewed
   together. Does anything in the plan's per-(t, c) posture make the
   common case — both channels of the current moment on screen — pay
   twice (two derives, two bakes, two refetches per landing), and is the
   storm-rate bar realistic with two channels live?
6. **The test matrix.** The four-square grid (held/scrolling ×
   before/after F5) and the station walk: name the (t, c) fault that
   passes all of it. Symmetric faults, faults that only appear at a
   moment boundary, faults masked by the z/t-navigation refresh the
   depth test plan records as a bench observation.

## The rules

Ground findings in code or measured numbers. Independence is the value:
do NOT read any other review file (`REVIEW_*.md`) in this folder — the
depth reviews included — beyond what the plan itself quotes; your worth
is what you find without them. Write your findings to
`building/REVIEW_the_picture_grows_c_and_t.md`, one-line verdict first,
then numbered findings most severe first, each with its evidence and its
cheapest deciding instrument. House style: plain, complete sentences a
biologist can follow. Touch no other file.
