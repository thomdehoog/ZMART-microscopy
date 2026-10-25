# Test run: from scratch on a ZMB workstation with the LAS X simulator, 25 October 2026

ZMART was installed from scratch on a ZMB Windows workstation that runs LAS X 4.9 in its simulator
mode, exactly as the documentation says: both target acquisition routes, the assembly with its walk,
each block's own tests, and the checks against the simulator. This page keeps what was found, so that
the fixes can be made later. Each finding says whether it needs a change in a repository or only
concerns that computer.

## What was tested

| Part | Version | Commit |
|---|---|---|
| Routes (this repository) | example-workflows | 9ad9a04 |
| Assembly (this repository) | release-candidate | c0dff32 |
| ZMART Controller | 0.4.0rc7 | 9024bb0 |
| ZMART Drivers | 0.7.0b8 | 98dd6ec |
| ZMART Viewer | 0.5.0rc8 | ab0c760 |
| ZMART Analysis | 0.6.0rc7 | 5a02f11 |
| ZMART Interface | 0.1.0rc6 | 52b3782 |

The computer: Windows 11, conda 25.7.0 in `C:\ProgramData\MinicondaZMB`, AppLocker on, PowerShell in
Constrained Language mode, Windows' long paths off, an NVIDIA T400 (driver with CUDA 13.2), Kaspersky
Endpoint Security as the antivirus.

## Results

| Step | Result |
|---|---|
| Coders route, install steps 1 to 4 | passes |
| Non-coders route, install steps 1 to 4 (all four analysis environments) | passes |
| `run_ci.py --controller`, without a microscope | 4 of 1602 tests fail: file paths longer than Windows allows (finding 4) |
| The driver's setup wizard | opens, and Connect reaches the simulator |
| Assembly: `install.py --branch release-candidate` | passes once Playwright can download its browser (finding 8) |
| Assembly: the 26 plug-in checks | pass |
| Assembly: `run_walk.py` | passes (3.9 minutes) |
| Controller's tests | 312 pass |
| Analysis's tests | 424 pass; the shutdown test that was slow on the last computer passes in 0.5 s |
| Drivers' tests | the same 4 path failures as above |
| Interface's tests | page tests pass; 2 Python tests fail (finding 1, fixed); the browser tests pass (94), the walk included |
| Viewer's tests | stopped part of the way: the antivirus ended the first run (finding 9); 836 pass in the part that ran |
| `run_ci.py --hardware --controller` on the simulator | the moves, pictures, saving, the cache and the controller layer pass; the setup wizard check fails (findings 3 and the limits file below) |
| The coders' notebook on the simulator | runs to the end; it finds no targets, because the simulator's pictures are smooth gradients |
| The interface on the simulator | runs from Connect to gating; the canvas stays empty (finding 2) |
| Cellpose with the GPU | PyTorch 2.13.0, CUDA available |

## Findings that need a change in a repository

1. **Two interface tests read the computer's own protocols.** On a computer where a protocol has
   been saved, `test_a_finished_run_writes_its_protocol_where_the_next_session_lists_it` and
   `test_without_a_session_there_is_no_protocol_to_list_or_write` list it and fail. Fixed in
   [ZMART-interface pull request 2](https://github.com/thomdehoog/ZMART-interface/pull/2)
   (version 0.1.0rc7).

2. **The canvas does not show a STELLARIS's pictures.** The viewer says "Coarse baking requires
   mean-reduced position pyramids" and shows 0 of 3 overview stores. The viewer only accepts a store
   that says its smaller copies were made by averaging (`"type": "mean"`). The Leica driver writes
   stores with one resolution and no such label. With the Mock the interface writes the store itself,
   with the label, which is why the walk passes. A real STELLARIS would show the same empty canvas.
   *To decide:* the viewer accepts a store with one resolution (the simplest true answer: nothing was
   averaged), or the driver labels its stores, or the interface builds its own store from the driver's.

3. **The setup wizard cannot save its calibration pictures.** Image-to-stage and objective
   calibration save their pictures without saying where on the canvas they lie, and saving refuses
   that: "an OME-Zarr store is placed by its canvas position, and none was given". This has been so
   since the drivers saved OME-Zarr only; the new hardware check of the wizard is the first to show
   it. *To decide:* in which frame a calibration picture is placed.

4. **Some driver tests make file paths longer than 260 characters.** The wizard's tests build deep
   folders inside the temporary folder. With Windows' long paths off (its default) and a user name of
   ten letters or more, they fail. *Proposed:* `run_ci.py` gives pytest a short folder of its own.

5. **Analysis workers can collide when they start in the same second.** Once during the walk:
   "The process cannot access the file because it is being used by another process", then "The system
   cannot find the file …\__conda_tmp_27156.txt". conda names that file with a random number that
   Windows repeats within the same second. *Proposed:* start the workers a moment apart, or start
   each environment's Python directly instead of through `conda run`.

6. **The driver's check of a z-stack expects the end exactly as asked.** On a job with a stack, LAS X
   rounds the end to whole steps (asked 9.07 µm, read 9.57 µm with steps of 2.909 µm). *To confirm:*
   that the real STELLARIS rounds the same way; then the check should expect the rounded end.

7. **A clearer message when LAS X's window cannot be found.** The driver presses LAS X's buttons
   through Windows; it cannot see a window that is on another virtual desktop. *Proposed:* "LAS X's
   window was not found — is LAS X on this desktop, and not minimised?"

8. **A note for computers whose antivirus inspects secure connections.** Kaspersky signs some
   websites with its own certificate; Playwright's browser download then fails with
   "SELF_SIGNED_CERT_IN_CHAIN". Setting `NODE_OPTIONS=--use-system-ca` while installing lets Node.js
   use Windows' certificates. *Proposed:* one sentence in the README's AppLocker paragraph.

## Findings about that computer only

- **The antivirus removed Python.** Kaspersky's behaviour detection ended the viewer's tests (a test
  that writes many files quickly) and then deleted `python.exe` from every environment with the same
  Python build. It was restored from conda's package cache. The cure is an exclusion for
  `C:\ProgramData\MinicondaZMB\envs`, which ZMB IT sets; until then, test suites that write many
  files should not run on ZMB workstations. Normal use was not affected.
- **LAS X on another virtual desktop.** The driver could not press LAS X's buttons until LAS X was
  moved onto the desktop the tests ran on.
- **An old limits file.** The computer's saved stage limits are in an older format, so the wizard's
  limits step refused them. They should be saved again with the wizard.

## Open questions

1. Which part should change for the canvas (finding 2)?
2. In which frame is a calibration picture placed (finding 3)?
3. Does the real STELLARIS round a stack's end to whole steps (finding 6)?
4. Should findings 7 and 8 become pull requests?
