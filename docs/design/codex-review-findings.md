# Adversarial review of the live-publication reference implementation

**Review basis:** `agent/live-position-timepoint-publication` compared with
`claude/omezarr-neuroglancer-structure-srnwu6`, August 2026.

This review treats the review prompt as a floor, not a boundary. It distinguishes
what was exercised from what was only established by reading because a live
microscopy safety claim is not earned by a plausible API or a green test alone.

## Outcome

The reference implementation is substantially safer after review, but it is not
yet a production live-publication pipeline. The storage policy, ownership rules,
manifest, shard-index resolver and scene adapter are useful, tested building
blocks. The production coordinator, backing view writers, shard resolver route
and viewer refresh integration are still missing. In particular, a caller can
construct an event whose readiness flags are all true without this package
having validated the artifacts those flags describe.

## Findings fixed in this branch

Ranked by their ability to produce a silently wrong picture or count:

1. **Two writers could lose a committed position and move the revision
   backwards.** Two `RunManifest` instances could both read revision zero, then
   replace one another's truth file. A deterministic barrier run produced a
   history ordered as revision 2 then revision 1 and left only the latter
   position visible. Publication is now guarded by a cross-process, per-run
   advisory lock on POSIX and Windows, and a writer rereads strict state while it
   owns that lock.

2. **A complete history line left by a crash could become visible later without
   being committed.** The history append precedes the atomic truth-file replace.
   Previously, a crash in between left a valid line that a later truth revision
   could accidentally include. Publishing now refuses any unannounced or partial
   tail. `recover()` preserves the evidence in `interrupted.json`, truncates the
   unpublished tail and reuses the same next revision.

3. **Manifest identity and corruption boundaries were too permissive.** A run
   could accept another run's event, and `start()` could reopen an existing
   folder under a new identity. A writer could also interpret a corrupt truth
   file using the reader's safe empty-screen fallback and overwrite history.
   Writers now fail closed on all three cases; readers retain the intentional
   empty-screen fallback.

4. **A damaged shard index could return plausible bytes from the wrong chunk.**
   The resolver did not validate the CRC32C trailer and trusted in-bounds ranges
   that could overlap the index or one another. It now validates the spec's
   little-endian CRC32C, absent-entry pairs, non-empty bounds, index separation,
   pairwise range separation, coordinate integers and safe chunk-key paths. It
   refuses unsupported index codec chains rather than guessing. See the
   [sharding-indexed specification](https://zarr-specs.readthedocs.io/en/latest/v3/codecs/sharding-indexed/index.html)
   and [CRC32C codec](https://zarr-specs.readthedocs.io/en/main/v3/codecs/crc32c/index.html).

5. **Coarse-pyramid routing silently assumed `2**level`.** Profiles permit
   anisotropic and non-power-of-two downsampling, so this could name and rebuild
   the wrong global chunks. `coarse.py` now uses each level's declared factor per
   axis and refuses incomplete geometry.

6. **Malformed or mutable records crossed trust boundaries.** Profiles accepted
   zero sizes, skipped levels, impossible linkable flags, non-finite voxel sizes
   and caller-owned mutable voxel maps. Commit records accepted several empty or
   invalid identifiers and dimensions. Scene construction accepted profile/layout
   mismatches, another run's committed state and store paths that could escape
   the run root. These boundaries now validate and freeze their inputs. A stored
   layout also refuses to choose the first answer if two positions claim the same
   point.

7. **The history reader was not actually incremental.** It reparsed the entire
   append-only file on every call and treated a newline-terminated malformed last
   line as an interrupted append. It now caches complete binary lines, reads only
   the new tail, distinguishes a missing newline from corruption, fingerprints
   with nanosecond modification and change times plus size and inode, and returns
   only truth-file-covered events by default.

8. **The installed wheel omitted all of `zmart_live`.** Source-tree imports hid
   an explicit setuptools package list containing only `zmart_storage`. The
   package list and regression test now include both; a built wheel was installed
   outside the checkout and imported from `site-packages` during this review.

9. **The mutation harness could call infrastructure errors successful catches.**
   Missing pytest, an already-red baseline, collection errors and browser launch
   failures all produced non-zero statuses. Each harness now requires a green
   baseline first and accepts only the test runner's ordinary assertion-failure
   status as a caught fault.

## Verified by running

- The complete Python suite and Ruff checks.
- A production build of the real-Neuroglancer browser-test page (1,177 modules).
- Every Python mutation campaign, including manifest, ownership, coarse levels,
  shard byte ranges and scene compilation. One offset-beyond-EOF mutation
  initially survived and received an independent regression test.
- Exact ownership for every pixel across small rectangular mosaics, odd and even
  overlaps, both edge policies and frame/overlap combinations beyond the
  parameterized suite.
- A deterministic two-writer interleaving before and after the lock fix.
- Crash tails with both a partial JSON line and a complete but unannounced line.
- Real Zarr v3 shards with compression, absent chunks, index at either end and
  CRC32C corruption; extracted encoded chunks decode identically to Zarr reads.
- The current unsharded `link_the_tiles` geometry. The planned sharded profile is
  explicitly rejected by that same linker because it aligns in whole bundles.
- A wheel build and isolated installed import of `zmart_live`.

The real-browser assertion was **not** run in this review environment. Node
packages installed and the page built successfully, but Playwright's Chromium
download endpoint returned an empty/non-ZIP response and no compatible browser
was preinstalled. The sabotage harness exited 2 after its baseline launch failed,
correctly classifying this as an environment blocker rather than a caught fault.

## Established by reading, not yet verified end to end

These are the next engineering gates, not minor polish:

1. **No coordinator earns readiness.** `RunManifest.publish()` enforces false
   readiness flags and atomic metadata visibility, but it does not verify pixel
   arrays, pyramids, virtual mappings, affected coarse chunks or layout itself.
   The microscope path that performs those checks and creates the event does not
   exist in this branch.

2. **The shard resolver is not connected to a view.** `plan_the_writing()` emits
   a sharded level 0 and `shardlink.py` can resolve one inner chunk correctly,
   but `zmart_storage.linked.link_the_tiles()` still forwards whole files and
   rejects the plan. `TileCanvases.create()` also accepts one scalar y/x shard,
   not the profile's per-axis z-slab. Until both adapters exist, sharding and
   zero-copy linking do not work together in production.

3. **The raw and seamless stores are descriptions, not implementations.** The
   scene model declares a raw view with a local `tile` selector and a seamless
   view, but no code here constructs either backing store or the strict global
   coarse levels. The coarse module plans work; it does not write pixels.

4. **The browser harness bypasses the production path.** It uses a synthetic
   server and real Neuroglancer to test the publication sequence. That is useful
   renderer evidence, but it does not prove production scene discovery,
   per-source invalidation, shard range serving or the coordinator.

5. **Windows and target-filesystem behavior is unmeasured.** POSIX directory
   entries are flushed after replacement. Python exposes no equivalent directory
   flush in this Windows implementation, and the semantics of advisory locking,
   replacement and power-loss recovery on the microscope's actual local/SMB
   storage still need fault and throughput tests. The proposed shard sizes also
   need the planned Windows copy/write benchmark.

6. **OME-Zarr scenes remain semantic only.** The internal scene model is a good
   translation target, but there is no native 0.6 serialization and Neuroglancer
   still requires the ZMART adapter. This is consistent with the decision record;
   it should not be described as native scene support.

## Recommended next slice

Build one narrow production vertical path for a two-position, one-timepoint run:
write canonical sharded positions; validate their complete pyramids; expose inner
chunks through the resolver-backed view route; build and validate both view
stores and affected coarse chunks; persist the exact layout; then let the
coordinator create the one commit event and make the real application refresh
only those sources. Run the existing browser sequence and both sabotages through
that path. That turns the present set of well-tested contracts into one tested
guarantee before adding broader acquisition formats.
