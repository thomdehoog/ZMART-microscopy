"""The same browser test, driven by the code an acquisition actually runs.

The test in the folder above proves that a commit decides what reaches the
screen, but it writes its two positions with a small purpose-built writer. That
left one honest gap, recorded as finding 4 of
``docs/design/codex-review-findings.md``: the browser was watching a stand-in
rather than :class:`zmart_live.coordinator.LivePublisher`, the class a real run
publishes through.

This folder closes that gap. The sequence is the same and the measurement is the
same; what changed is that every position on screen was written, checked and
committed by :meth:`LivePublisher.write_and_publish`. See
:mod:`zmart_live.tests.browser.production.production_run` for the run and the
server, ``commit-gates-the-picture-in-production.spec.mjs`` for the sequence, and
``README.md`` for how to run either of them.
"""
