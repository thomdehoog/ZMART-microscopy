# Fast detection runs its fields at once; the last phase is "finalizing feature extraction"

Date: 2026-09-21. Branch `codex/operator-named-views-simulator`.

## What was there

Step 6's worker (`framework/bridge.py`, `_targets_worker`) was two phases already: every field through
the analysis (segment, measure) and then one statement about the whole population, the UMAP, folded back
into every field. The per-field phase was a strictly serial loop, each field blocking on
`warm.Analysis.run`. The analysis engine could fan out, but the step files declared a width of one, the
engine keyed a step's concurrency by its file, which the fast and robust pipelines share, and the warm
helper's `run` was not safe to call from several threads. Fast is single-threaded CPU work of about a
second a field; robust is Cellpose, one model on the card per worker.

## What changed

- **The engine** honours a `max_workers` on a step in the pipeline's YAML, over the step file's own
  METADATA, and keys a step's semaphore by file and width, so the two pipelines sharing `detect_objects.py`
  run at their own widths (`zmart_analysis/engine/_run.py`, `_pipeline.py`, `_pool.py`).
- **The fast pipeline** runs its three steps twelve wide (`object_analysis_fast.yaml`); the robust one is
  unchanged at one.
- **The warm helper** has `run_each`: every job submitted up to a width, answers taken as they land and
  told apart by a key the engine echoes in its result (and in its scope for a failure); a stop asked
  mid-run submits no more and drains what is in flight (`parts/analysis/warm.py`).
- **The finder** (`parts/microscope/detection.py`) offers `each` beside the one-field call, and
  `width_of` says how wide a way of finding runs: fast, half the machine's cores up to twelve; robust,
  one; `at_once` in the settings is the operator's own number.
- **The bridge worker** hands all fields to the finder at once, files each as it lands, keeps the fields
  in the sample's order for the page, and says "detecting and measuring objects in N positions at once,
  k of m done" while they are in flight. The last phase is named `finalizing` and reads "finalizing
  feature extraction: N objects"; the progress box sweeps on that name; the mock reports the phase too.
- **The page** no longer moves the lit frame to each field as it lands, since fields land in the
  engine's order.

Not done: pre-spawning the workers at Connect (cold cost is paid once per session, see below), a per-field
resume from the detection checkpoint (nothing reads it back), moving UMAP into the analysis environment.

## Measured

Nine overview fields of a finished mock walk, 9,211 objects, the real classical-environment workers on
this machine (12 physical cores, width 12), `scratchpad/measure_fast_detection.py`:

| pass | width | wall |
| --- | ---: | ---: |
| one at a time, workers cold | 1 | 22.4 s |
| one at a time, warm | 1 | 15.0 s |
| at once, spawning the extra workers | 12 | 12.1 s |
| at once, warm | 12 | 5.8 s |

Warm, the nine fields take 2.6 times less. Nine fields cannot use twelve workers, and each field's fixed
cost (reading the store, hashing it, writing the masks) is paid in every worker, so the gain on a
nine-field overview is bounded; it grows with the field count. The first press of a session pays the
spawns: about 7 s for one worker, about 6 s more for the rest.

## Verified

- `test_operator_bridge.py` 61 passed, including the fields landing out of order and kept in the sample's
  order, the robust width of one, the finalizing phase seen from inside the embedding, Interrupt between
  fields, one bad field filed, a worker put down by the hand.
- `test_warm.py` and `test_detection.py` 32 passed; engine phase and pool tests 22 passed.
- JS unit suite 528 passed; the nine-step walk with bake on.
