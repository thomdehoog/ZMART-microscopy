# Plan: the workflows live in ZMART Microscopy

*Status: a draft for review, 31 October 2026. Nothing has been changed yet.*

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

- **ZMART analysis** keeps the `alignment` pipelines (focus, orientation,
  registration) and the `object_analysis` pipelines (Cellpose, watershed,
  reduce dimensions) in its `workflows/` folder.
- **ZMART interface** ships the *Target acquisition* workflow inside its
  package, in `zmart_interface/workflows/target_acquisition/`.

This plan keeps both where they are as clearly marked **examples**, so that
each block still shows how to use it and still has something to test with,
and puts the copies we actually use in this repository's `workflows/` folder.

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
- `zmart_interface/parts/analysis/workflows.py` no longer assumes the
  pipelines are in a checkout of ZMART analysis. Today it reads
  `ZMART_ANALYSIS_WORKFLOWS` and, when that is missing, tells the operator to
  point it at ZMART analysis. Instead, **the workflow says where its
  pipelines are**, so the Target acquisition in ZMART Microscopy can bring its
  own.

### 3. ZMART Microscopy: the workflows we use

- `workflows/target_acquisition/` starts as a copy of the interface's Target
  acquisition, built into a small installable package the way the
  interface's `docs/writing-a-workflow.md` describes.
- `workflows/analysis/alignment/` and `workflows/analysis/object_analysis/`
  start as copies of the analysis pipelines.
- `install.py` installs the Target acquisition package from here and makes the
  analysis environments from the pipelines here. It no longer clones ZMART
  analysis only to reach its pipelines.
- The coder's path, today kept in the archive branch as notebooks, is
  rewritten on the installed blocks and uses **the same pipelines** as the
  operator window. Someone who clicks through the operator window and someone
  who writes Python then get the same analysis.

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
3. ZMART interface: mark Target acquisition as an example.
4. ZMART Microscopy: copy the pipelines into `workflows/analysis/`.
5. ZMART Microscopy: copy Target acquisition into
   `workflows/target_acquisition/` as an installable package.
6. ZMART Microscopy: change `install.py` and the checks in `tests/` to use the
   copies here, and run the walk on them.
7. ZMART Microscopy: rewrite the coder notebooks on the installed blocks.

## Questions to decide

1. In ZMART analysis, should the folder be renamed to `examples/`, or keep
   the name `workflows/` with a clear note? Renaming is clearer but changes
   paths that other people may use.
2. Should the interface's example remain the full Target acquisition, or
   later shrink to a smaller example of two or three steps that is easier to
   learn from?
