# Working in this repo

## Audience: write for biologists, not software engineers

ZMART is used mostly by **microscopists and biologists who are learning**, not by
professional software engineers. Every docstring, comment, notebook-markdown
cell, and README must be written for that reader. This is a **general rule** for
all code and docs in this repository.

Concretely:

- **Convey the information the reader needs, and give context.** Say *why*
  something is done and what it means for their experiment — not just *what* the
  code does. A line that only restates the code in English adds nothing; a line
  that explains the reason earns its place.
- **Be gentle and welcoming.** Assume curiosity, not expertise. The tone should
  help someone learn, never make them feel they should already know.
- **Avoid unexplained software-engineering jargon.** Terms like *dihedral
  group*, *Jacobian*, *atomic replace*, *idempotent*, *dataclass*, *closure* are
  fine only if you also explain them in plain language (or replace them with a
  plainer phrase). Prefer "a 90° turn" over "a D4 element" in operator-facing
  text; keep the precise term for internal code comments if it genuinely helps a
  maintainer, but still gloss it.
- **Operator-facing surfaces get the most care**: the `zmart_controller`
  `Session` methods, the mock microscope, the example notebook, and the
  README. These are the front door.
- **Docstrings state contracts plainly**: what goes in, what comes back, what
  can go wrong — in a sentence or two a non-programmer can follow.
- **Write in easy, complete sentences.** Read it back and make sure it flows.
  Avoid clipped "telegram style" — the terse, article-dropping shorthand that
  saves keystrokes but makes the reader work ("Fail-closed guard; abandoned-leg
  drain sizing" reads as noise). Full sentences cost a few more words and are
  far kinder to read.
- **Keep a calm, neutral voice.** Not chatty, not hype, and not the dense,
  sloppy shorthand of throwaway code comments. Steady and clear, the way you
  would explain something to a colleague at the microscope.

Good docs are not decoration here; they are how a biologist learns to drive
their microscope. Treat them with the same care as the code.

## What this repository is, and what it is not

ZMART Microscopy is the **assembly** of ZMART. It holds no block of its own:
the controller, the drivers, the viewer, the analysis engine and the interface
each live in their own repository and are installed from GitHub by
`install.py`. What lives here is what only makes sense with all of them
together:

- the install (`environment.yml`, `install.py`), conda-forge only;
- the checks that the blocks fit (`tests/`, and `run_walk.py`, which runs the
  interface's browser walk against the installed packages);
- the workflows composed from the blocks (`workflows/`).

Some rules follow from that:

- **Never copy a block's code in here.** When a check fails, the fix belongs in
  the block's own repository. A check turns green when the block is fixed, not
  when the check is loosened.
- **Test what a user installs.** The checks import the installed packages, never
  a clone's folder. The clones in `work/` supply only what is not packaged (the
  controller's mock driver, the analysis workflows, the walk).
- **Nothing above the controller cares which driver is underneath.** Checks and
  workflows pick an instrument by its whole name (vendor, microscope and api),
  and a capture is only ever taken on a mock here; real drivers are plugged in
  and listed, nothing more.

The code that used to live here (the in-repo controller, drivers, analysis,
viewer and interface, and the notebooks written against them) is in the git
history and in the archive branch.
