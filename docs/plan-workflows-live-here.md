# Plan: the workflows live in ZMART Microscopy

*Status: steps 1 to 6 done on 1 November 2026, on the branch `examples-and-workflows` of ZMART analysis, ZMART interface and ZMART Microscopy in the `thomdehoog` account, and checked on Linux. Step 7 (the coders' notebooks) and the full check on a Windows workstation are still to do. What was done, and where it differs from the plan, is under "Done" at the end.*

## In short

ZMART is made of building blocks that you install: the drivers, the
controller, the interface, the analysis engine and the viewer. Each block is
general. It works for anyone, on any microscope, for any experiment.

A **workflow** is different. It is one particular experiment built from those
blocks, such as scanning a kidney overview, finding the cells of interest and
imaging each of them again. A workflow, and the analysis it relies on, is
specific to the work we do, so it belongs here in ZMART Microscopy and not
inside a block.

Today two blocks still carry real workflows inside them:

- **ZMART analysis** keeps the `focus` pipeline and the `object_analysis`
  pipelines (Cellpose, watershed, reduce dimensions) in its `workflows/`
  folder.
- **ZMART interface** ships the *Target acquisition* workflow inside its
  package, in `zmart_interface/workflows/target_acquisition/`.

This plan keeps both where they are as clearly marked **examples**, and puts
the copies we actually use in this repository's `workflows/` folder.

The examples stay in the blocks on purpose, for two reasons:

- **Each block can be tested on its own.** ZMART interface and ZMART analysis
  each run their own tests against their own example, without needing ZMART
  Microscopy or any other repository.
- **People have something to learn from.** Someone who wants to write a
  workflow for the interface, or a pipeline for the analysis engine, finds a
  complete, working example right next to the code that runs it.

## What is already in place

The blocks were built with this split in mind, so most of the groundwork is
done:

- The analysis engine is packaged on its own. `pip install zmart-analysis`
  installs only the engine (`zmart_analysis` and `engine`); the pipelines are
  not part of the package.
- The interface's general part, `zmart_interface/framework/`, knows no
  workflow in particular. A test checks this, and the work to get there
  finished on 11 October 2026.
- The interface already explains how to write a workflow in another
  repository and install it as a small package
  (`docs/writing-a-workflow.md` in ZMART interface). The page offers an
  installed workflow in its chooser without being rebuilt.

## The rule: an example is never installed with its block

An example lives in the block's repository, where its tests run on it and
where people can read it. It is **not** part of what `pip install` puts on a
computer. Installing a block gives you only the block. The workflows you
actually run come from ZMART Microscopy and are installed on their own.

Today one block already follows this rule and one does not:

| Block | Example | Installed with `pip install` today? |
|---|---|---|
| ZMART analysis | `workflows/focus`, `workflows/object_analysis` | **no**: the package holds only `zmart_analysis` and `engine` |
| ZMART interface | `target_acquisition` | **yes**: it sits inside the package, at `zmart_interface/workflows/target_acquisition/` |

So ZMART interface needs one more change than marking its example, described
in section 2 below.

## What changes

### 1. ZMART analysis: its pipelines become examples

- The `workflows/` folder is renamed `examples/`, or keeps its name and gets
  a clear note at the top of each README, saying that these are examples of
  how to write pipelines and steps for the engine.
- The README says plainly that the pipelines you run on a microscope live in
  ZMART Microscopy.
- The engine's own tests keep using the examples, so nothing about testing
  the engine is lost.

### 2. ZMART interface: Target acquisition becomes an example

- `target_acquisition` is marked as an example workflow: a full, working
  workflow to read and copy from, and the one the interface's own tests and
  browser walk run.
- **It moves out of the package**, from
  `zmart_interface/workflows/target_acquisition/` to a top-level
  `examples/target_acquisition/` in the repository, which is not packaged.
  After that, installing the interface no longer installs Target acquisition.
- **The framework's tests that use it are adjusted.** At least six test files
  in `zmart_interface/framework/` (for example `test_operator_bridge.py` and
  `test_stopping_a_focus_map.py`) import parts of Target acquisition
  directly. They load it from `examples/` instead, so the interface can still
  be tested on its own.
- **On a microscope, the workflow comes from ZMART Microscopy.** The
  interface already has a workflow library: a folder,
  `zmart-interface/workflows` in the computer's ZMART configuration folder,
  into which workflow packages are installed separately. ZMART Microscopy's
  Target acquisition is installed there as a small package, as the
  interface's `docs/writing-a-workflow.md` describes, and the page offers it
  in its chooser.
- `zmart_interface/parts/analysis/workflows.py` no longer assumes the
  pipelines are in a checkout of ZMART analysis. Today it reads
  `ZMART_ANALYSIS_WORKFLOWS` and, when that is missing, tells the operator to
  point it at ZMART analysis. Instead, **the workflow says where its
  pipelines are**, so the Target acquisition in ZMART Microscopy can bring its
  own.

### 3. ZMART Microscopy: the workflows we use

There are two ways in: one for people who do not write code, through the
operator window, and one for people who write Python. **Each path has its own
analysis**, so that one can change without the other:

```
workflows/
  non-coders/
    interface/target_acquisition/   the workflow that plugs into the operator window
    analysis/focus/                 the pipelines it calls
    analysis/object_analysis/
  coders/
    notebooks/                      Python that drives the microscope through the controller
    analysis/focus/                 the pipelines the notebooks call
    analysis/object_analysis/
```

- `non-coders/interface/target_acquisition/` starts as a copy of the
  interface's example Target acquisition, built into a small installable
  package the way the interface's `docs/writing-a-workflow.md` describes. It
  names `non-coders/analysis/` as the place of its pipelines.
- `non-coders/analysis/` and `coders/analysis/` both start as copies of ZMART
  analysis's example pipelines, `focus` and `object_analysis`.
- `install.py` installs the Target acquisition package from here and makes the
  analysis environments from the pipelines here. It no longer clones ZMART
  analysis only to reach its pipelines.
- The coder's path, today kept in the archive branch as notebooks, is
  rewritten on the installed blocks and uses `coders/analysis/`.

**The two analyses may drift apart.** That is the reason for keeping them
separate: a change made for the coders does not quietly change what the
operator window does, and the other way round. The cost is that the same
experiment done on the two paths may no longer give exactly the same numbers.
So when a pipeline is changed on one path, its README says so, and whether
the other path should follow is a decision someone makes, not an accident.
The analysis environments have the same names on both paths for as long as
the pipelines are copies; once a pipeline's environment differs, it gets a
name of its own, so the two paths never overwrite each other's environment.

## What you would notice

At the microscope: nothing. The same steps, the same buttons, the same files
on disk.

For whoever changes a workflow: the change is made here, in one place, and
does not need a new release of the interface or the analysis engine.

## On having two copies

After this plan, Target acquisition and the pipelines exist twice: as
examples in the blocks and as the real thing here. Over time they will drift
apart, and that is fine. The examples only have to keep teaching their block
and keep its tests meaningful. The copies here follow our experiments.

## What this means for this repository's own rules

This repository's `CLAUDE.md` says that a block's code is never copied in
here, and that the analysis workflows come from a clone of ZMART analysis in
`work/`. Both lines need updating with this plan. A workflow is not a block's
code: it is our experiment, built on the blocks, and this is its home. The
rule against copying still holds for the blocks themselves (the controller,
the drivers, the engine, the interface's framework and the viewer), and
`work/` would then supply only the controller's mock driver and the
interface's browser walk.

## Steps

Each step leaves everything working, with the tests passing.

1. ZMART analysis: mark the pipelines as examples (README and folder name).
2. ZMART interface: let a workflow name where its pipelines are, and keep the
   environment variable working for now so nothing breaks.
3. ZMART interface: mark Target acquisition as an example, move it out of
   the package to `examples/target_acquisition/`, and point the framework's
   tests at it there. Check that a fresh `pip install` of the interface no
   longer contains it.
4. ZMART Microscopy: copy the pipelines into `workflows/non-coders/analysis/`
   and `workflows/coders/analysis/`.
5. ZMART Microscopy: copy Target acquisition into
   `workflows/non-coders/interface/target_acquisition/` as an installable
   package.
6. ZMART Microscopy: change `install.py` and the checks in `tests/` to use the
   copies here, and run the walk on them.
7. ZMART Microscopy: rewrite the coder notebooks in
   `workflows/coders/notebooks/` on the installed blocks.

## Done (1 November 2026)

All three on the branch `examples-and-workflows`, in the `thomdehoog` account,
each started from that repository's `release-candidate`.

**ZMART analysis 0.6.0rc8.** `workflows/` is now `examples/`, and part 3 of the
docs is "The example workflows". The engine is unchanged. 431 tests pass.

**ZMART interface 0.2.0rc1.** On its release candidate, a workflow was no
longer installed beside the interface but built into the page, so step 2 and 3
became a change to the framework (option A, agreed with Thom):

- The interface brings no workflow. It runs a **folder of workflows**, named
  by `ZMART_INTERFACE_WORKFLOWS` (in a checkout, its `examples/`). The page is
  built from that folder into its `built-page/`, and the bridge loads the
  workflows' Python halves and serves that page.
- Target acquisition, **with its mock microscope**, moved to `examples/`. The
  mock travels with the workflow, because the workflow starts it; it is not
  moved back into the package as first thought.
- A workflow imports the API as `zmart-interface/api`, so it works from any
  folder. Its unit tests, browser tests and the walk run on a folder outside
  the interface too.
- The installed package is the framework alone (15 files); a test holds it so.
- All checks pass: 475 Python tests, 727 unit tests, type, import, unused-code
  and API checks, and the browser tests including the ten-step walk. Five
  browser tests that run the real focus scoring could not run on Linux
  without conda, and are left for the Windows workstation.

**ZMART Microscopy 0.1.0rc1.**

- `workflows/non-coders/interface/target_acquisition/` and its committed
  `built-page/`; `workflows/non-coders/analysis/` and
  `workflows/coders/analysis/`, each with its own tests (171 pass each).
- `install.py` no longer clones ZMART analysis, makes the analysis
  environments from our own pipelines, and has `--github` to take the blocks
  from another account.
- The checks and `run_walk.py` run our own workflow. A new check holds the
  committed page to what the build makes.
- Checked on Linux with the blocks installed from the `thomdehoog` branches:
  23 checks pass (the two that need conda could not run), the page check
  passes, and the walk passes on our own Target acquisition.

**Still to do:**

1. Step 7: rewrite the coders' notebooks in `workflows/coders/notebooks/`.
2. The full check on the Windows workstation, with CPU and GPU:

   ```bash
   python install.py --github thomdehoog --branch release-candidate \
       --branch zmart-analysis=examples-and-workflows --branch zmart-interface=examples-and-workflows
   python -m pytest tests
   python run_walk.py
   ```

3. The release, in the order under "Releases": tag ZMART analysis 0.6.0rc8 and
   ZMART interface 0.2.0rc1, point the interface's `pyproject.toml` and its
   automatic checks at analysis `v0.6.0rc8`, then ZMART Microscopy 0.1.0rc1, and
   bring all three to the ZMB's repositories.
4. ZMART Microscopy's `CLAUDE.md` (on `main`) still says the analysis
   workflows come from a clone in `work/`; it follows when this reaches `main`.

## Releases

When this plan is done, the three repositories it changes each get a new
release candidate. The controller, the viewer and the drivers are not touched
by this plan, so their versions stay as they are. (The drivers plan brings
its own versions for the drivers.)

| Repository | Now | After this plan | Why |
|---|---|---|---|
| ZMART interface | `0.1.0rc10` | `0.2.0rc1` | Installing it no longer brings Target acquisition, and it finds pipelines in a new way. Someone relying on the old behaviour will notice, so the middle number goes up. |
| ZMART analysis | `0.6.0rc7` | `0.6.0rc8` | The engine does not change; only its example folder is renamed, so this is a small step. |
| ZMART Microscopy | no version yet | `0.1.0rc1` | Once it holds the workflows we run, it needs a version of its own, so we can say which ZMART Microscopy the microscopes run. |

The order matters, because ZMART Microscopy installs the other two at exact
versions:

1. Release the new release candidates of **ZMART interface** and **ZMART
   analysis**.
2. Point ZMART Microscopy's `install.py` at exactly those versions, and give
   **ZMART Microscopy** its own release candidate.
3. Run the checks (`tests/` and the walk) on that combination, and write the
   result into the README's status table, the same way as the run of
   11 October 2026.

## Decided

- ZMART interface and ZMART analysis **keep their example workflows**: the
  full Target acquisition, and the `focus` and `object_analysis`
  pipelines. They are clearly marked as examples, and each block's own tests
  run on them, so the block can be tested by itself.
- ZMART analysis's `workflows/` folder is renamed `examples/`. This was done
  in ZMART analysis 0.6.0rc8, on the branch `examples-and-workflows`.
- In ZMART Microscopy, **each path has its own analysis**:
  `workflows/non-coders/analysis/` and `workflows/coders/analysis/`. They may
  drift apart, on purpose.
- Every block is built on from its `release-candidate` branch, the newest
  version of each.
