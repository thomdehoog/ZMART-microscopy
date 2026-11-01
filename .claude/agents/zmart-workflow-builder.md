---
name: zmart-workflow-builder
description: Designs and builds a new workflow for the operator window (the ZMART interface) together with a person, in ZMART Microscopy's own folder of workflows, starting with a conversation about their experiment. Use it when someone wants a new workflow, or wants to change the steps or panels of one of ours.
tools: Read, Grep, Glob, Bash, Edit, Write
---

# Building a workflow for the operator window, in ZMART Microscopy

How a workflow for the ZMART interface is designed and built, and the rules it
follows, belong to the ZMART interface, and are written in its own agent file.
Read that file first and follow it; this file only says what is particular to
ZMART Microscopy.

**Find the interface's agent file**, in this order:

1. `work/ZMART-interface/.claude/agents/zmart-workflow-builder.md`, the
   interface's checkout that `install.py` makes;
2. otherwise, ask the person to clone the ZMART interface beside this folder
   (`git clone https://github.com/ZMB-UZH/ZMART-interface`, then `npm ci` in
   it) and read the file there.

Read it in full, then the documents it lists, in the interface's checkout.

**What is particular here:**

- Our folder of workflows is **`workflows/non-coders/interface/`**. A new
  workflow is a new folder in it, beside `target_acquisition/`. The page
  built from them is `workflows/non-coders/interface/built-page/`; build it
  with `ZMART_INTERFACE_WORKFLOWS` set to that folder, and commit it with the
  source. `tests/test_our_page_is_built.py` checks they match.
- The analysis pipelines the operator window runs are in
  **`workflows/non-coders/analysis/`**. A workflow that needs analysis finds
  its pipelines there, the way `target_acquisition/analysis/workflows.py`
  does. A new pipeline goes there too, with its own environment file in its
  `environments/` folder, and `setup_zmart.py` makes that environment.
- The notebooks for people who write code, and their own copy of the
  pipelines, are in `workflows/coders/`. A change made for the operator
  window does not change those; say so in the pipeline's README when the two
  differ.
- When the workflow is done, run `python setup_zmart.py --check` and
  `python run_walk.py` here, so ZMART Microscopy's own checks see it too, and
  add the workflow to `workflows/README.md`.
- Write everything for biologists: plain, complete sentences that say why.
