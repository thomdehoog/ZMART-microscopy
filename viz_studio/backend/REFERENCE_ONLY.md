# Reference-only backend

The Python files in this directory are the copied backend of an earlier
standalone Viewer prototype. They are not a supported Microscopy runtime path and
must not be added to `sys.path`, imported by `viewer_service.py`, or used to prove
Smart Operator behavior.

The runtime authority is the separately installed `zmart-viewer` 0.2.0 package at
commit `9ff10b04e803fbe2a71a1735a8065a845ea803dd`. Historical tests may continue to
exercise this directory only where they protect a still-supported storage or wire
contract, and must label that boundary explicitly.
