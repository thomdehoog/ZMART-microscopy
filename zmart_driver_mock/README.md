# The mock driver

The mock driver lets you try every ZMART command without a microscope. It is
also the template for a new driver: it is built from the same parts as every
ZMART driver, so you can read it to learn how a driver works inside, and copy
its layout when you start your own.

Underneath it runs **MockScope Control**, pretend vendor software with a
pretend microscope behind it (see [`testing/mock_api/`](testing/mock_api/README.md)).
MockScope behaves like real vendor software: it speaks its own language,
takes time to move, refuses commands while busy, writes its own file format,
and can be made to fail on purpose. Everything in this driver above it is
the same code a real driver would need.

## Try it

```python
import zmart_controller

zmart_controller.register_driver("zmart_driver_mock", remember=False)
instrument = next(i for i in zmart_controller.get_instruments() if i["vendor"] == "mock")
zmart_controller.set_instrument(instrument)

zmart_controller.set_xyz(100, 50, 0)
answer = zmart_controller.acquire(acquisition_type="overview", position_label="A1")
answer["report"]["files"]   # real OME-TIFF files you can open in Fiji or napari
```

The pictures show a slide of small bright spots, like fluorescent beads.
Move the stage and the spots move; change the focus and they blur.

Images are saved under the system's temporary folder unless the connection
names an `output_root`. Two more connection entries are useful while
experimenting: `"mock_timing": "instant"` makes every move and acquisition
finish at once, and `"token"` is the pretend login (`"mock-token"`).

## The parts

The driver follows the anatomy of a ZMART driver, described in full in
`docs/design/driver-anatomy.md` in the ZMART-microscopy repository. Each
part is a folder, and each part only uses the parts below it.

| Folder | Part | What it does here |
|---|---|---|
| [`vendor_interface/`](vendor_interface/) | 1. Vendor interface | Starts MockScope, logs in, and offers one plain function (a *primitive*) per vendor command. The only part that knows MockScope. |
| [`error_handling/`](error_handling/) | 2. Error handling | Sorts every problem into a kind (temporary, bad request, permanent, connection lost, ...) and holds the table of what to do for each kind. |
| [`get_commands/`](get_commands/) | 3. Get commands | Ask the microscope things through the get dispatcher: one read at a time, a few tries after a temporary problem, a time limit, and "unknown" rather than a guess. |
| [`set_commands/`](set_commands/) | 4. Set commands | Change the microscope through the set dispatcher: the limits gate, sending, retries, reading back to confirm, sending again, and giving up softly when it cannot confirm. |
| [`procedures/`](procedures/) | 5. Procedures | Recipes built only from get and set commands: autofocus, backlash takeup, parking the piezo, and recording the origin. |
| [`data_handling/`](data_handling/) | 6. Data handling | Waits for the vendor's file, turns the picture to line up with the stage, writes OME-TIFF or OME-Zarr, and saves the log of the commands behind it. |
| [`configuration/`](configuration/) | 7. Configuration | The machine description, image-to-stage registration, origin, limits and optical calibration, each with shipped defaults and a check. Also the arithmetic between stage and user coordinates. |
| [`zmart_controller/`](zmart_controller/) | 8. ZMART controller plugin | The 11 functions the controller calls. They only map commands onto the parts above. |
| [`testing/`](testing/) | 9. Testing | The mock API. The tests themselves are in the repository's `tests/` folder. |

## How a move travels through the driver

`zmart_controller.set_xyz(100, 50, 0)` goes through these steps:

1. **The plugin** picks the motor for each axis and hands the request to the
   set commands.
2. **The set command** reads the current position through the get
   dispatcher, and turns the user position (micrometers from the origin)
   into a stage position, using the configuration.
3. **The set dispatcher** asks the limits gate. A position outside the
   limits is refused here, before anything is sent.
4. It waits until the microscope is not busy, then **sends** the move
   through the vendor interface.
5. If MockScope answers "busy", **error handling** calls that temporary, and
   the dispatcher sends again after a short pause.
6. The dispatcher **reads back** the position until it matches the target.
   If it never does, the plugin raises `RuntimeError`, because carrying on
   at an unknown position is never safe.

Every step writes a line to the command log, which is saved next to the
images of each acquisition.

## Setting the microscope up

On a real microscope, the operator runs a setup step once, and the driver
saves the result in the computer's configuration folder. The mock works the
same way, through `zmart_driver_mock.configuration.save` and
`zmart_driver_mock.procedures.record_origin`. Until something is saved, the
shipped defaults in [`configuration/defaults/`](configuration/defaults/) are
used, and `get_info()` says so.

The defaults are deliberately the defaults of an *uncalibrated* microscope.
The registration assumes the camera is mounted straight, and the
calibration assumes the objectives line up perfectly. MockScope's real
camera is mirrored and its objectives are slightly offset, just as a real
microscope would be, so there is something real to measure.
`scope.truth()` holds the right answers for checking.
