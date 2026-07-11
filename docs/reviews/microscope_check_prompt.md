# Microscope check handoff

Continue on branch `claude/forfable4-document-11mxsx` from commit `605c9cd` or
newer. The fresh macOS rehearsal passed: Leica mock 1030/1030, controller 35/35,
both v4 notebook gates 14/14, webapp 33/33, full workflow 303/303 excluding
three network-data skips, and Chromium 5/5 three times. No Leica-driver files
were changed; the driver is still incomplete user-owned work.

On the Leica PC, first confirm LAS X is running, the correct sample/job is
selected, the stage has safe travel clearance, and machine limits/orientation/
objective calibration are published. Build or update `zmart-microscopy` with
`build_env.py` and verify `import clr` succeeds. Then, with the operator present,
run `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/run_ci.py --hardware`
(this moves the stage, changes state, and acquires images). If it passes, run the
controller tests, both v4 notebook tests, and webapp tests, then launch
`workflows/target_acquisition/run_webapp.py` and perform one complete real run
through Disconnect. Report exact commands, pass/fail counts, artifacts, and any
failure before modifying driver code.
