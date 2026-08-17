# Working in this repo

## Audience: write for biologists, not software engineers

ZMART-viewer is used mostly by **microscopists and biologists who are learning**,
not by professional software engineers. Every docstring, comment, notebook-markdown
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
- **Operator-facing surfaces get the most care**: the top-level `README.md`, the
  viewer's own `viz_studio/README.md`, the controls in `viz_studio/frontend/src`,
  and the writer's public methods in `zmart_storage`. These are the front door.
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

## Look at the pictures (a standing habit for browser tests)

This is a viewer; its bugs are pictures. Whenever you build, debug, or
falsify a browser test, save the oracle screenshots and **actually look at
them with your vision capability** — do not settle for the numbers alone.
Look at the red run to confirm the picture is wrong in the way the sabotage
intended, and at the green run to confirm the picture is right rather than
merely passing. Put warm and fresh side by side; render a difference image
when the numbers disagree with your expectations. This repository has been
saved more than once by a look where arithmetic had stalled — the
blurry-corner investigation of 2026-08-15 ended the moment the two band
photographs were placed side by side. A metric can be satisfied by the
wrong picture; an inspected screenshot cannot.

## Build simply; let tests catch the mistakes (a standing rule for code)

Write the simplest, most readable thing that does the job — the least
amount of code that a colleague can follow. Do not be defensive by
default: guards, fallbacks, retries, and special-case handling earn their
place only when a **proven** failure demands them — a bug we actually hit,
a measurement that showed the danger, a review finding with evidence.
Speculative armor ("what if someone someday…") is over-engineering; it
grows the code, hides the real path, and defends against ghosts.

The safety net is the tests, not scattered guards. When something breaks,
we would rather see it break loudly in a test, understand it, and then
address it cleanly at its cause — that is cheaper and more honest than
code that quietly tolerates states it was never designed for. So: the
main path does exactly what it is supposed to do, plainly; every defense
that does exist can point at the incident or measurement that justified
it; and everything else is a test's job.
