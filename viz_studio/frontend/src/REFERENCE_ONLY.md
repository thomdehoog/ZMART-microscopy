# Reference-only front end

These React and engine sources belong to the copied standalone Viewer prototype.
They are not built into or loaded by the Smart Operator.

The maintained operator integration lives in `viz_studio/options/`, principally
`neuroglancer-under/viewer.js`, and talks to the separately installed
`zmart-viewer` 0.2.0 server at commit
`9ff10b04e803fbe2a71a1735a8065a845ea803dd`. Keep this directory only as design
history and as narrowly scoped contract-test reference.
