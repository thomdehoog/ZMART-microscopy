# Microscope-Agnostic Layer

This folder is reserved for code that should sit between microscope-specific
drivers/calibration and operator workflows.

Keep vendor-specific implementations in sibling folders such as `driver/`,
`calibration/`, and `limits/`. Move code here only when the same concept is
useful across microscope backends.
