# Leica Objective-Switch Cookbook

This folder contains protocol-shaped scripts for learning, testing, and
later scaling objective-switch targeting workflows.

The first split is by actuator:

- `motorized_stage/`: the physical XY stage moves the sample. Use it for
  objective-frame transport and coarse positioning. In these scripts the
  image center is the stage readback: `image_center_xy = get_xy()`.
- `galvo_pan/`: the stage stays fixed while the scan field is panned
  optically. Use it for precise final centering inside its limited range.
  In these scripts the image center is:
  `image_center_xy = get_xy() + pan * pan_scale_um`.

The second split is by scale:

- `single_target_*`: one target, readable protocol, best for debugging and
  optimizing the movement strategy.
- `batch_*`: repeat the same strategy over a manifest, with per-target
  output folders and failure handling.

The current scripts are intentionally self-contained. Shared helpers should
only be introduced after a protocol is stable enough that duplication is a
larger risk than hiding the control flow.

