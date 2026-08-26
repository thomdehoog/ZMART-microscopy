# The workflows: one folder each, and the folder's name is its name

Every folder in here that contains a `flow.js` is a workflow the operator can
choose. The folder's name is what the chooser at the top left of the window
shows — underscores read as spaces, first letter capitalised, so
`target_acquisition` appears as **Target acquisition**. Adding a workflow means
adding a folder with a `flow.js` in it; nothing else in the application has to
change, because the frame finds these folders by looking
(`../frame/rules/finding-workflows.js` says how).

## What is inside a workflow's folder

```
target_acquisition/
  flow.js        the front door: the steps, in order, plus a sentence for the
                 chooser. Open this first — it is the whole workflow in one
                 screenful.
  steps/         one numbered folder per step, 1_connect/ to 8_acquire_targets/,
                 so the folder listing reads the way the rail down the left of
                 the window does. Each holds the step's declaration (step.js)
                 and, where the step brings controls of its own, the widget
                 beside it (widget.js).
  shared/        what several steps of this workflow use: the carrier geometry,
                 the scan-field arithmetic, and the canvas that draws the run.
  microscope/    the seam where the instrument goes. mock.js is the pretend
                 microscope the page rehearses with; a real driver lands beside
                 it with the same functions. Every API call lives behind this
                 seam — a step only calls it and awaits. The synthetic specimen
                 the mock images lives in pretend-sample/.
```

The rule that decides where a file goes: **put it beside the things that use
it, at the lowest folder that covers them all.** Used by one step → in that
step's folder. Used by several steps of one workflow → that workflow's
`shared/`. The microscope sits inside `target_acquisition/` rather than in the
frame because the frame is only an engine — it could just as well run an
analysis workflow that never touches an instrument.

## Borrowing steps instead of retyping them

A step belongs to the workflow that owns it, and other workflows import it;
`target_acquisition/flow.js` is little more than the list in `the-run.js`.
A workflow that wants a borrowed step to say something different wraps it in
`reworded()` (from `../frame/rules/steps.js`), which changes the wording and
nothing else. That keeps what a step *does* written down once, so a fix
reaches every workflow at the same moment.

## What a step is made of

A step is data, not code: a short description the frame reads. These are its
fields, all optional except the first two.

- `id` — the short name the page files this step's result under.
- `title` — what the step is called in the rail down the left.
- `why` — one sentence saying what the step is for.
- `panels` — which modules the step wants on screen, named. An empty list means
  "nothing of my own"; see `../frame/rules/steps.js`, which decides what that
  comes to once the canvas is in play.
- `btn` — the words on the button that carries the step out. A step with no
  `btn` has nothing to press: some steps are completed by doing the thing they
  are about — the carrier is settled by being configured, the scan fields by
  being drawn — and asking for a press afterwards would only ask the operator
  to confirm what they have already done.
- `ownButton` — the step's own panel builds its button, so the frame should not
  add a second one underneath.
- `ms` — how long this rehearsal pretends the work takes, in milliseconds. The
  page is a mock of a microscope for now; when a real instrument is wired in,
  this is what the wait becomes.
- `mode` — which piece of behaviour the page runs for this step: measuring
  focus, scanning, detecting, and so on.
- `ready` — what the step still needs before it may be carried out. It is
  handed the run so far and answers either `null`, meaning go ahead, or a short
  phrase saying what is missing, which the page shows beside the greyed-out
  button. A step with no rule is always ready. Readiness belongs to the step
  rather than the page around it: only the focus step knows what a focus map
  needs, and putting the rule on the step is what lets a new workflow be a list
  of steps instead of another rule added to the shell.
- `note` — what the step writes beside itself in the rail once it has finished,
  for steps whose result is always the same sentence.
- `nothingWaitsOnThis` — the steps after this one do not wait for it. A run is
  walked in order because each step usually produces something the next one
  needs; a step that only shows the operator something produces nothing to wait
  for, and saying so here lets them walk straight past it. See
  `../frame/rules/steps.js`, which is where the rule lives.
