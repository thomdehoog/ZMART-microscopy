# Workflows

A workflow is one experiment built from the ZMART blocks: what to image, and
what to do with the pictures. It drives the microscope through the
[ZMART Controller](https://github.com/ZMB-UZH/ZMART-controller), so it runs on
any microscope with a [driver](https://github.com/ZMB-UZH/ZMART-drivers); it
hands pictures to [ZMART analysis](https://github.com/ZMB-UZH/ZMART-analysis),
and shows them with the [ZMART viewer](https://github.com/ZMB-UZH/ZMART-viewer).

The blocks are general and are installed; the workflows are ours, and they
live here. The blocks keep examples of their own, to test themselves with and
to learn from, but those examples are not installed with them. The workflows
in this folder started as copies of those examples and are free to change with
our experiments.

There are two ways in, one for people who do not write code and one for
people who do, and **each has its own analysis**:

```
workflows/
  non-coders/
    interface/                    the folder of interface workflows
      target_acquisition/         the steps of the operator window
      built-page/                 the operator page, built from them
      package.json                marks the folder's code as JavaScript modules
    analysis/                     the analysis pipelines the operator window runs
      focus/
      object_analysis/
  coders/
    notebooks/                    Python that drives the microscope directly
    analysis/                     the analysis pipelines the notebooks run
      focus/
      object_analysis/
```

## For people who do not write code: the operator window

`non-coders/interface/` is a folder of workflows for the
[ZMART interface](https://github.com/ZMB-UZH/ZMART-interface). The interface
brings no workflow of its own: it runs the ones in the folder that the setting
`ZMART_INTERFACE_WORKFLOWS` names, and serves the page built from them. On a
microscope PC that is this folder:

```bash
ZMART_INTERFACE_WORKFLOWS=<this repository>/workflows/non-coders/interface zmart-interface
```

*Target acquisition* is the workflow in it today: scan an overview, find the
cells or structures of interest, and image each of them again at higher
magnification. It started as a copy of the interface's example. It finds its
analysis pipelines in `non-coders/analysis/`, beside it
(`target_acquisition/analysis/workflows.py` says how).

The page in `built-page/` is built from these workflows with the interface's
checkout, on a computer with Node.js, and committed here, because a microscope
PC cannot build it. After any change to a workflow, build it again:

```bash
cd work/ZMART-interface          # the interface checkout install.py makes
ZMART_INTERFACE_WORKFLOWS=<this repository>/workflows/non-coders/interface npm run build
```

`tests/test_our_page_is_built.py` checks that the committed page is the one
the build makes.

**To build a new workflow with Claude Code**, open it in this folder and say:
*"Use the zmart-workflow-builder agent: I want to build a new workflow."* It
starts with a conversation about your experiment (the steps in the rail, what
is on screen, the analysis), writes it back to you as a plan, and builds the
workflow here once you agree, by the ZMART interface's rules. The workflow's own tests run from the interface's checkout
too, with the same setting: `npx vitest run` for the page's unit tests, and
`python run_walk.py` here for the walk through all ten steps.

## For people who write code: notebooks

`coders/notebooks/` is where Python notebooks drive the microscope through the
controller and run the analysis themselves. They use their own copy of the
pipelines, in `coders/analysis/`. The target-acquisition notebooks that lived
in this repository before the blocks had repositories of their own are kept in
its git history and in the archive branch, until they are rewritten here on
the installed blocks.

## Why each path has its own analysis

The two copies of the pipelines start the same and **may drift apart, on
purpose**. A change made for the notebooks then does not quietly change what
the operator window does, and the other way round. The cost is that the same
experiment done both ways may no longer give exactly the same numbers. So when
a pipeline changes on one path, say so in its README, and decide on purpose
whether the other path should follow.

Both copies' pipelines run in the same conda environments
(`ZMART--focus--main`, `ZMART--object_analysis--classical`, ...) for as long as
their environment files are the same. When one path's environment needs to
differ, give it a name of its own in its `environments/` file, so the two
paths never overwrite each other's environment.

Each copy's own tests run from its folder:

```bash
cd workflows/non-coders/analysis     # or workflows/coders/analysis
python -m pytest
```
