# The first session on the LAS X simulator

A checklist for the first time the ZMART driver configuration workflow meets
a Leica, with the LAS X simulator standing in for the microscope. Everything
below the page has been tested against a stand-in for the CAM socket and the
camera; this session is where those two joins are proven for real. Take it
slowly, and keep what you see: a screenshot of anything that looks wrong, and
the folder the session leaves behind, are worth more than a description of it.

The workflow itself is described in
[`application/workflows/zmart_driver_configuration/README.md`](../application/workflows/zmart_driver_configuration/README.md).
The bench prerequisites for the driver are in the driver's own
[`tests/hardware/README.md`](../zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware/README.md).

## Before you start

- [ ] LAS X is running with the Navigator Expert CAM add-in, and no dialog is
      open. A dialog blocks the whole CAM API, and every step of the workflow
      will fail with "no answer" until it is closed.
- [ ] A template is loaded with a job selected. The setup reads and acquires
      through the selected job, and refuses with "No Navigator Expert job is
      selected in LAS X" when there is none.
- [ ] LAS X native AutoSave is switched on in the StartUp configuration, with
      a base folder the driver can read. Every picture the workflows take is
      what LAS X saves there; the Connect card's *autosave* check reads
      "enabled" when it is, and target acquisition will not proceed while it
      says "failed — LAS X will not save what is captured".
- [ ] The page has been built on a developer machine (`npm run build` in
      `application/`), and the three files it leaves in
      `application/framework/window/static/` have come across together.
- [ ] Know where the configurations will land. On this machine that is:

      ```
      C:\ProgramData\zmart-microscopy\leica\stellaris5_y42h93\navigator_expert\
      ```

      If `ZMART_MICROSCOPY_ROOT` is set in the environment, that folder is used
      instead of `C:\ProgramData\zmart-microscopy`. Open the folder in Explorer
      and keep it open; you will watch it fill up.
- [ ] Note what is in that folder before you begin. Two shapes are possible:
      - **Nothing, or only loose `limits/`, `calibration/`, `orientation/`,
        `origin/` folders** left by an earlier release. The first connect
        copies those loose trees into one `configuration_<datetime>` folder.
        It copies and never moves, so the old trees stay exactly as they were.
      - **One or more `configuration_<datetime>` folders** already there. The
        page will list them newest first.

## Start the page

- [ ] From the repository root, on the microscope PC:

      ```
      python application/zmart-interface.py --built
      ```

      One window opens. The bridge behind it registers the mock driver always
      and the Leica driver when it can import it; the bridge's console says
      which it found. If the Leica is missing from the Microscope list, read
      that console first.
- [ ] **What the page opens on.** With no configuration that holds limits, the
      page moves itself to *ZMART driver configuration* and preselects *New
      configuration*. With a configuration that holds limits, it opens on
      *Target acquisition* with the newest configuration selected. Either is
      right; note which one you got and whether it matches the folder.

## Step 1: Connect

- [ ] Choose the Leica in *Microscope*, its API, the password, and in the
      fourth field either *New configuration* or the configuration to continue.
      Check the list order: newest at the top.
- [ ] Press Connect. The rail's steps 2 to 5 should light up. Behind the card
      the setup has opened the CAM client with limits loaded and calibration
      left unloaded, which is what lets a fresh machine be reached at all.
- [ ] Look in Explorer. If you chose *New configuration*, a new
      `configuration_<datetime>` folder is there, and it is a full copy of the
      newest one, or a seeded one on a bare machine.
- [ ] If Connect fails, the message on the card is the driver's own. "No
      answer" means the CAM socket; anything naming a file or folder means
      ProgramData. Screenshot it and stop here; nothing below can work yet.

## Step 2: Define limits

- [ ] In LAS X, drive the stage to each of the four corners of the safe area
      in turn. After each one, press *Import* on that corner's row. The page
      reads the drives through the driver; nothing is read from markers here.
- [ ] Check the four readings against what LAS X shows. They are in
      micrometres, and the X and Y ranges above the rows should update once
      all four are in.
- [ ] Fill in the objective slots automation may use and the permitted values
      for each setting, then *Save and adopt*.
- [ ] In Explorer, under the configuration: `limits/<datetime>/limits.json`
      appeared. The page stays connected but has reopened the setup on the
      same configuration, so from here on the driver's own gate fences every
      move. The card's checks should now say the limits are the published ones.
- [ ] Known simulator quirk: the simulator often homes at (0, 0), which is
      outside a real machine's envelope. If a later step refuses to move,
      first check that the stage is inside the limits you just adopted.

## Step 3: Define coordinate system origin

- [ ] Drive to the point the run should count from, and focus, in LAS X.
- [ ] Press *Read*. Every drive's reading appears; compare it with LAS X.
- [ ] *Save and adopt*. Nothing moves in this step. In Explorer:
      `origin/<datetime>/origin.json`.

## Step 4: Image-to-stage calibration

This is the first step that moves the stage and takes pictures through the
driver, so watch LAS X while it runs.

- [ ] Put a field with visible structure under the lens and focus. On the
      simulator the pictures may carry no structure at all. If so, the
      analysis will honestly report that it could not find the orientation.
      That is not a failure of the joins; what matters here is the rest of
      this list.
- [ ] Press *Start*. Expect three pictures and one known stage move between
      them, and the stage back where it started at the end. Read the stage
      position in LAS X before and after.
- [ ] If a result comes, check it against what you know of the machine, then
      *Save and adopt*. In Explorer: `orientation/<datetime>/` holds
      `orientation.json` and, beside it in `data/`, the figure
      `orientation.png`, the measurement's numbers, the raw frames, and
      `orientation.yaml`, the recipe the analysis ran by.
- [ ] Note the time each picture took to come back. Slowness here is the CAM
      round trip, and it is worth writing down.

## Step 5: Objective calibration

- [ ] Choose the reference objective. A preset at zero appears for every other
      lens; pick the pair you want to measure.
- [ ] *Measure reference*: one picture and a short focus stack under the
      reference lens. Watch the Z drive in LAS X step through the stack and
      return.
- [ ] Change the lens by hand in LAS X. The page reads which lens is in from
      the selected job; it never commands the turret. If it reports the wrong
      lens, that is the thing to note.
- [ ] *Measure target*, then *Measure X/Y*. As in step 4, featureless
      simulator pictures may leave no peak in the stack, and the page says so.
- [ ] *Save and adopt*. In Explorer: `calibration/<datetime>/calibration.json`
      with the measured pair, and the pair's figure beside it in `data/`.

## Afterwards

- [ ] Disconnect on the card, then connect again on the configuration you just
      made. Each step should show what the configuration holds: the published
      limits, the origin, the orientation with its figure, the measured pair.
- [ ] Switch the workflow to *Target acquisition*. The fourth field offers the
      same configuration, newest first, and Connect goes through the
      controller. The controller refuses a configuration without limits, so
      pick one from before step 2 if you want to see that refusal.
- [ ] Keep the whole `configuration_<datetime>` folder. Zip it as it is; it is
      the record of the session and the input for repeating any measurement.

## If something goes wrong

Collect three things and the rest can be worked out later:

1. A screenshot of the page with the message on it.
2. The bridge's console output from the moment the page was started.
3. The configuration folder, zipped, together with a note of what was in the
   ProgramData folder before the session began.

Nothing in this workflow rewrites an existing configuration folder, and the
migration of old loose trees copies rather than moves, so a session that goes
wrong can be repeated from the same starting point.
