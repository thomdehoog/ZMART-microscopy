"""The browser test that watches a commit decide what reaches the screen.

Everything else in :mod:`zmart_live` can be checked by reading the record back
and asking whether it says the right thing. That is worth doing and it is not
enough on its own, because the promise the record makes is about a *picture*: a
position that has not been committed must not appear on the operator's screen.
A record can be perfectly correct while the viewer draws whatever it finds on
disk, and nothing in a record-shaped test would notice.

So the test in this folder drives a real Neuroglancer in a real browser against a
real OME-Zarr served over HTTP, and photographs the screen. See
:mod:`zmart_live.tests.browser.growing_run` for the run and the server, and
``commit-gates-the-picture.spec.js`` for the sequence it drives.
"""
