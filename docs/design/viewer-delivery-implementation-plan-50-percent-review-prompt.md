# Review brief: 50% Viewer delivery implementation

Date: 2026-09-01

Please review the implementation and its remaining plan; do not extend or fix
it in this review.

## Read

1. `docs/design/viewer-delivery-implementation-plan-50-percent.md` completely.
2. `docs/design/lazy-jpeg-pyramids-for-the-viewer.md` completely.
3. The prior reviews at commits `48f72d64` and `e73aa7f1`.
4. ZMART-microscopy branch `claude/viewer-port-remaining-steps-ofm5qp` at the
   commit containing this prompt.
5. ZMART Viewer branch `codex/viewer-delivery-50-percent` at commit `d243736`,
   compared with its base `9ff10b0`.

## Review stance

This checkpoint implements V1, the ordinary position-collection path of V2,
and M1, with part of I1. M2/M3 are intentionally absent: the embedded panel has
not adopted the waiting state, no capability gate exists, and the writer still
keeps its old per-position fallback. Do not penalise it for preserving that
compatibility boundary or for not authorising compact `uint8`. Do identify code
that makes the boundary unsafe or the two schema implementations diverge.

## Questions

1. Do both implementations of `zmart-acquisition-display/1` accept and reject
   the same documents, including non-finite values, optional unresolved
   windows, channel ordering, and provenance?
2. Is the microscopy writer's temporary-file/`fsync`/`os.replace` publication
   sufficient, and is its immutable-republication check safe under concurrent
   attempts?
3. Is `positions/<type>/zmart-acquisition.json` the right authority boundary,
   or does either real run layout put it somewhere the Viewer cannot find?
4. Does Viewer legacy reconciliation correctly refuse identity/range mismatch,
   preserve consensus, and omit disagreeing `start`/`end` without making the
   first filename authoritative? Identify foreign OME metadata it rejects too
   aggressively or accepts too loosely.
5. Does every ordinary composed-source door—unbaked, declared, baked, ledger
   reopen, config, and live refresh—retain byte-equivalent OME and ZMART display
   metadata? Name any missed governed/linked path that this microscopy workflow
   actually uses.
6. Is `window: null` safe through Python, JSON, `scene.js`, and `LayerPanel.jsx`?
   Review the real-browser waiting test and look for remaining numeric camera-
   range fallbacks outside the deliberately untouched embedded panel.
7. Does M1 preserve old-reader behavior exactly when no sidecar exists and for
   an unresolved sidecar, while making a resolved acquisition window identical
   across bright and dim fields?
8. In the real Leica/controller path, where should channel key, label, colour,
   numeric range, and optional display window originate? The implementation
   accepts `channels` but deliberately does not derive or supply them from
   `activeRecording`; name only fields the real API actually provides.
9. Should M2 use package version pinning or explicit capabilities, and what
   exact check must land before the embedded panel changes and M3 removes
   `_a_window_onto`?
10. Are the implemented tests sufficient for this halfway boundary? Name the
    smallest additional cross-repository or browser test needed before 80%.
11. Reassess the still-unimplemented scratch, real-run measurement, benchmark,
    and Z work only far enough to decide their order for 80%.
12. Confirm that JPEG remains absent and compact `uint8` remains unauthorised.

## Requested output

Return:

1. blockers ordered by migration or data-loss risk;
2. corrections to the implemented files, interfaces, validation, tests, and
   commit order;
3. a final recommended acquisition descriptor schema, including whether the
   two local validators should be generated/shared differently;
4. a final compatibility/release mechanism and exact M2 boundary;
5. accepted benchmark definitions and thresholds, with replacements where
   needed;
6. a checklist of decisions required for the 80% plan;
7. verdict: accept this 50% checkpoint and proceed to 80%, revise this
   implementation first, or stop.

For factual claims, cite files/functions/tests from the inspected commits.
Label proposed design choices separately from verified behaviour.
