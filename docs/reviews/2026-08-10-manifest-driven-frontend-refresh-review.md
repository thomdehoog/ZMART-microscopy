# Adversarial implementation review — manifest-driven live frontend refresh

**Subject:** PR #8, `agent/live-position-timepoint-publication` (`80089a64`, implementation
commit `2698de4f`) against `claude/omezarr-neuroglancer-structure-srnwu6` (`2027f911`).
**Brief followed:** `docs/design/manifest-driven-frontend-refresh-review-prompt.md`.
**Reviewer environment:** Linux container, 4 cores, Python 3.11.15 in a fresh `.venv`,
Playwright 1.62.0, Chromium 141 from `/opt/pw-browsers`.

---

## 1. Executive verdict

**REQUEST CHANGES.**

The publication boundary itself is the strongest part of this branch and it survived every
attack I made on it. I could not find any way to make a position, a timepoint or a
replacement generation visible before `committed.json` advanced, and I could not make a
damaged, foreign or regressing marker become a legitimate revision. Where I doubted a
claim I wrote a test to break it, and the implementation held.

Changes are requested for two reasons, neither of which is a data-visibility fault:

1. The load-bearing browser qualification **cannot run at all**. All four tests in
   `viz_studio/tests/test_manifest_refresh_browser.py` fail before reaching a single
   assertion, on three independent test-only defects. The suite would be red in CI as
   well. The handoff document's claim that these scenarios "are part of the suite" is
   therefore not currently true in any environment.
2. One stated non-negotiable invariant is **violated in production code**: filling a
   committed-time gap causes a *global* Neuroglancer decoded-cache flush across every open
   dataset, not a scoped one. I reproduced this in a real browser.

Both are small, well-localised fixes. When they are fixed, this is a merge.

---

## 2. Findings

### F1 — CRITICAL (to the evidence, not the data): the decisive browser tests cannot run

**Where:** `viz_studio/tests/test_manifest_refresh_browser.py`, three separate places.

**Mechanism.** Three independent defects, each of which alone kills the test:

- **`_wait_for_revision` (line 77–84)** passes `arg` positionally:
  ```python
  page.wait_for_function(EXPRESSION, [dataset, revision], timeout=60_000)
  ```
  In Playwright's Python API, `Page.wait_for_function`'s signature is
  `(self, expression, *, arg=None, timeout=None, polling=None)` — `arg` is
  **keyword-only**. The call raises
  `TypeError: Page.wait_for_function() takes 2 positional arguments but 3 were given`.
  Every one of the four tests calls `_open()`, which calls this, so all four die
  immediately. `Page.evaluate` *does* accept a positional `arg`, which is why the many
  other browser tests in this repo are unaffected — this is the only
  `wait_for_function` in the repository that passes one.

- **`_tune_and_mark` (line 140) and `_operator_state` (line 120–121)** query
  `[aria-label="opacity group overview"]`. The group control's label is
  ``` `opacity group ${group}` ``` (`viz_studio/frontend/src/LayerPanel.jsx:508`), and
  `group` is the *dataset* label, not the acquisition type:
  `server.py:1548` passes `group=groups_named[binding.dataset_number]` into
  `live_rows`. Dumping `/api/config` for exactly this fixture gives
  `groups: ['tmphodtp04x']` — the pytest temporary directory name. The element can
  never exist, `querySelector` returns `null`, and
  `HTMLInputElement.value.set.call(null, …)` raises `TypeError: Illegal invocation`.

- **`page.get_by_label("t position")` (lines 282, 312, 319, 320)** is a substring match
  and also resolves `<output aria-label="t position value">`, so `.wait_for()` raises
  `strict mode violation: … resolved to 2 elements`.

**Reproduction.**
```
npm --prefix viz_studio/frontend run build
ZMART_REQUIRE_BROWSER=1 .venv/bin/pytest -q viz_studio/tests/test_manifest_refresh_browser.py
→ 4 failed in 7.01s
```

**Why existing tests do not catch it.** Nothing runs these tests except a
Chromium-capable machine with `ZMART_REQUIRE_BROWSER` set; without it they *skip*, and a
skip is reported as "no picture was looked at" rather than as a failure. On a machine
where they do run they fail, and `.github/workflows/viewer.yml` installs `playwright`
unpinned (line 75) — so CI gets 1.62 and would be red.

**Does the product actually work?** Yes. I copied the file to a scratch name, made the
three minimal test-only corrections (`arg=`, resolve the group name from
`window.zmartConfig.groups[0]`, `exact=True`), and re-ran:

| Scenario | Result |
| --- | --- |
| A → B premature visibility + operator state | **passed** |
| t=0 → t=1 uncommitted time + cached-empty refresh | **passed** |
| unrelated live run makes no requests | **passed** (unmodified) |
| lost SSE hint recovered | **failed** — see F3 |

So this is a test defect, not an implementation defect. But until it is fixed, no visual
claim on this branch is supported by anything that has run.

**Fix.** `arg=[dataset, revision]`; read the group label from the config rather than
assuming `"overview"`; `get_by_label("t position", exact=True)`. Optionally pin
`playwright` in `requirements-dev.txt` and in `viewer.yml` so the API surface stops
moving underneath the suite.

**Blocks merge:** yes.

---

### F2 — MEDIUM: filling a committed-time gap causes a global decoded-cache flush

**Where:** `viz_studio/frontend/src/App.jsx:199` (`anyStoreGainedItsFirstImage`) →
`App.jsx:496` (`letGoOfDecodedPieces`), fed by
`viz_studio/backend/live_config.py:211–214` (`contiguous_frames`).

**Mechanism.** `live_rows` deliberately emits `frames: None` when committed publication is
not contiguous from zero, so that an old frontend cannot read a gap as a high-water mark.
That is correct on its own. But `anyStoreGainedItsFirstImage` treats
`histogram == null && frames == null` as "this row has no picture at all", and live rows
*always* carry `histogram: null` (`live_config.py:180`). So when the gap is later filled
and `frames` becomes a number again, the row looks to that function like an acquisition
that has just gained its first image, `catchUp()` returns `"gained-image"`, and the SSE
handler calls `letGoOfDecodedPieces(engine.current)` — which walks
`viewer.chunkManager.rpc.objects` and invalidates **every** decoded holder in the viewer,
including those of unrelated datasets (`engine.js:400–416`).

This violates the brief's invariants 32 ("Refresh must not globally clear every
Neuroglancer cache") and 33 ("Cache invalidation must be scoped to affected aggregate
source identities"), and the handoff's own instruction that
`letGoOfDecodedPieces` "must not become the default response to every live commit".

**Reproduction (verified in a real browser).** Publish t=0, then t=2 while t=1 is absent,
then t=1:

```
frames: gapped=None -> filled=3
global letGoOfDecodedPieces calls: 0 -> 1
sources asked to drop everything on the last flush: 4
```

The backend half is separately confirmed against the shipped server:

```
after t=0                  frames=1      ranges=[{start:0, stop:1}]
after t=2 (gap at t=1)     frames=None   ranges=[{start:0, stop:1}, {start:2, stop:3}]
after t=1 fills the gap    frames=3      ranges=[{start:0, stop:3}]
```

**Race dependence.** The flush only fires when the **SSE** path applies the config. The
slow conditional check calls `await catchUp()` and discards its return value
(`App.jsx:572`), so when the 500 ms fallback wins the race no flush happens. With the
fallback at its production 10 s interval the SSE path wins and the flush happens. My
first run of this test, with `zmartLiveCheckMs = 500`, passed for exactly that reason —
worth knowing, because it makes the bug intermittent rather than absent.

**Severity.** No uncommitted data becomes visible and nothing is shown wrongly; the cost
is that every decoded chunk in the viewer, across every open run, is dropped and refetched
because one run filled a timepoint gap.

**Why existing tests do not catch it.** The mutation campaign's global-invalidation fault
targets `forgetOneStableSource` in `engine.js`, which is the *narrow* path. Nothing
exercises the interaction between `frames: None` and `anyStoreGainedItsFirstImage`.

**Fix.** Exclude manifest-driven rows from `anyStoreGainedItsFirstImage` — they carry
`liveRunId`, so the guard is one clause — or make the "gained its first image" test look
at `committedTimeRanges` rather than the legacy `frames` field for those rows.

**Blocks merge:** recommended. It is a two-line fix and it contradicts a stated
non-negotiable invariant.

---

### F3 — MEDIUM: the lost-SSE test does not test a lost SSE hint (and fails)

**Where:**
`viz_studio/tests/test_manifest_refresh_browser.py:371–412`
(`test_lost_sse_hint_is_recovered_by_conditional_check_and_eventsource_reconnects`).

**Mechanism.** The test drops the connection with `page.context.set_offline(True)`,
publishes, blocks `**/api/events`, goes back online, and expects the conditional
`/api/live-state` check to be what recovers the revision. In this Chromium the established
SSE stream **survives** `set_offline`, so the hint is delivered over the still-open
connection and the fallback is never exercised. The final assertion
`len(events) >= 2` ("EventSource did not attempt to reconnect") then fails, because
nothing ever reconnected — there was nothing to reconnect.

**Evidence.** I wrapped `window.EventSource` in an init script to count delivered
messages, then repeated the test's exact sequence:

```
AssertionError: an SSE message delivered the change (0 -> 1);
the conditional check was not what recovered it
```

**The underlying invariant does hold.** I wrote the honest version of Scenario E —
suppress the announcement at its source (`Announcements.say_something_changed` → no-op)
while leaving SSE connected, so the only possible recovery is the conditional check:

```
test_review_suppressed_announcement_is_recovered_by_conditional_check … 1 passed
```

The page reached the new revision and drew a measurably non-black picture without any
hint. So invariant 36 is satisfied by the implementation; only the shipped test is
misleading.

**Fix.** Suppress the announcement rather than the transport, and test EventSource
reconnection as a separate assertion (or drop it — the browser's own retry is not this
project's behaviour to prove).

**Blocks merge:** no, but it should be fixed with F1 since it is the same file.

---

### F4 — MEDIUM: one damaged run freezes every other open run

**Where:** `viz_studio/frontend/src/live-refresh.js:33–35`, consumed at
`App.jsx:303–307`.

**Mechanism.** `liveStateProblem` iterates the runs in the state-set document and returns
on the *first* degraded run:

```js
if (run.freshness === "degraded") {
  return run.error || "the publication record cannot currently be read safely";
}
```

`applyConfig` treats any non-null answer as a reason to reject the **whole** configuration
and return `"rejected"`. So if a viewer has two live runs open and run B's marker is
temporarily unreadable, run A stops advancing — and, because the rejection discards the
entire `/api/config` answer, so does every ordinary non-live dataset on the page.

**Reproduction.**
```
node --input-type=module --eval '…liveStateProblem(prev, next)…'
healthy run A advanced 1->2, unrelated run B damaged => "marker unreadable"
both healthy => null
```

**Severity.** It fails in the safe direction — the last good image stays on screen and the
operator is told the state is stale — but a run that is publishing perfectly well stops
updating because of an unrelated folder. During an overnight acquisition that is the
difference between watching your experiment and not.

**Why existing tests do not catch it.** `test_damaged_marker_serves_last_good_state_as_degraded_until_restored`
uses a single run, where rejecting everything and rejecting that run are the same thing.

**Fix.** Reject per-run: keep the healthy runs' state, mark only the degraded run stale,
and let `applyConfig` apply the rest.

**Blocks merge:** no. Worth doing before this is used with two runs open.

---

### F5 — LOW: the time control merges committed ranges across unrelated runs

**Where:** `viz_studio/frontend/src/App.jsx:797–822` (`committedTimeRanges`).

**Mechanism.** The memo flattens `committed_time_ranges` from **every** open live run into
one list and merges overlapping ranges, producing a single global availability set for the
one time slider. With run A committed to t=0..1 and run B to t=0..5, the control exposes
t=0..5:

```
run A committed 0..1, run B committed 0..5
time control exposes: [{"start":0,"stop":6}]
```

Selecting t=4 then asks run A for a moment it has never published. Nothing leaks — the
gateway is fail-closed and refuses those chunks, so run A simply renders empty — but the
control overstates what is available for that run, which is precisely the class of claim
this branch exists to make honest.

**Fix.** Either scope the time control per dataset, or intersect rather than union, or say
plainly in the UI which run the exposed range belongs to. Gaps *within* one run are
handled correctly (`start <= last.stop` never bridges a real gap), so only the cross-run
case is affected.

**Blocks merge:** no.

---

### F6 — LOW: `ManifestWatcher._watch` has no exception guard, unlike its sibling

**Where:** `viz_studio/backend/announcements.py:342–345`.

```python
def _watch(self) -> None:
    while not self._stop.is_set():
        self.check_once()
        self._stop.wait(self._every)
```

`FolderWatcher._watch` (line 235–264) deliberately wraps its per-tick work in
`except Exception` with the comment "a folder that cannot be read this moment … is not a
reason to stop watching for the rest of the session". `ManifestWatcher` does not. Anything
escaping `check_once()` — most plausibly from `LiveRegistry.refresh()`, whose
`self._library.datasets()` call is unguarded — kills the daemon thread permanently and
silently. The viewer degrades to the 10 s conditional check for the rest of the session,
which is safe but slow, and nothing says so.

I did not manage to trigger this; `live_run_holding` swallows filesystem errors through
`Path.is_dir()`, so the reachable paths are narrow. It is reported because the asymmetry
with the sibling class is unexplained.

**Fix.** Mirror `FolderWatcher`'s guard.

**Blocks merge:** no.

---

### F7 — LOW: retained state and dead code

- `zmart_live/live_state.py:333–339` keeps `self._events` — every `CommitEvent` for the
  life of the run — solely so `_compile` can fall back to an event's `channels` when a
  sealed profile predates that field. For a profile that names its channels (the normal
  case) the list is written and never read. On a 10,000-position, 100-timepoint run that
  is a million retained objects for a fallback that never fires.
- `zmart_live/live_state.py:199` `version_token()` is never called anywhere; the server
  computes its own ETag over the multi-run document.
- `viz_studio/backend/live_config.py:25` `LiveBinding.group` is always `""`; `live_rows`
  is always called with an explicit `group=`.
- `viz_studio/backend/live_config.py:147–155` the `snapshots is None` branch of
  `live_state_document` duplicates `capture_live_state` and is unreachable in production.

**Blocks merge:** no.

---

### F8 — LOW: the conditional-check effect restarts on every commit

**Where:** `viz_studio/frontend/src/App.jsx:550–585`.

The effect depends on `config?.liveState`, so every accepted revision tears down the
interval and rebuilds it with `etag = null`. The first check after each commit is
therefore an unconditional `200` with a full body instead of a header-only `304`, and the
10 s cadence restarts from the commit rather than running steadily. Harmless while idle,
which is the case the `304` optimisation was written for, but it does mean the
"unchanged replies never reach Neuroglancer" property is one request weaker than it reads.

**Blocks merge:** no.

---

### F9 — MEDIUM (process): four of the brief's ten required mutations are missing

`zmart_live/tests/check_the_live_refresh_tests_can_fail.py` covers six of the ten faults
the brief asks for, and the harness itself is genuinely strict — I read
`_fault_check.py` and it requires a green baseline before each fault, accepts only
pytest's exit status `1` (so a collection or import error is explicitly *not* counted as a
catch), verifies byte-for-byte restoration, and discards `__pycache__` so a same-length
edit cannot leave the faulty version behind. It ran clean:

```
serve canonical pixels before their manifest commit                      yes
turn gapped committed time into a misleading high-water range            yes
report a damaged publication marker as current                           yes
ignore a stable source's higher committed revision                       yes
put the committed revision into the Neuroglancer source URL              yes
globally invalidate a decoded source during a narrow refresh             yes
```

Not covered:

7. make an SSE announcement itself authoritative instead of rereading the manifest;
8. make duplicate announcements trigger full refreshes;
9. make unrelated acquisition revisions refresh all sources;
10. remove the positive "A remains bright" assertion from the premature-visibility test.

Fault 10 is deferred by a comment to "the real-browser campaign", but that campaign
(`zmart_live/tests/browser/production/check-the-production-test-can-fail.mjs`) sabotages
the *standalone* harness in `zmart_live/tests/browser/`, not
`viz_studio/tests/test_manifest_refresh_browser.py`. So the production page's
positive-control assertion has no mutation proving it can fail. Given F1, it also has no
run proving it can pass.

**Blocks merge:** no, but 7–9 are the three mutations that would have found F2's
neighbourhood, and 10 is the one the brief calls mandatory.

---

## 3. Invariant audit

Categories are used strictly: **EXECUTION** means I ran something that would have failed
had the invariant been broken; **READING** means I traced the code and am confident but did
not run a discriminating test.

### Publication truth

| # | Invariant | Status |
| --- | --- | --- |
| 1 | `positions/` sole owner of pixel payloads | EXECUTION (`zmart_live/tests`, 512 passed) |
| 2 | raw/seamless remain metadata + routes, zero-copy | EXECUTION (same suite; `test_viewroute`, `test_shardlink`) |
| 3 | no completion inference from chunks/dirs/timestamps/shape/fs events | EXECUTION (`test_written_pixels_are_withheld…`, mutation 1, browser scenario A) |
| 4 | a notification only triggers rereading truth | EXECUTION (`test_manifest_watcher_still_nudges…`; browser scenario A) |
| 5 | damaged/foreign/truncated/regressing never becomes newer or lower | EXECUTION (`test_damage_regression_and_foreign_truth…`, mutation 3) |
| 6 | safe-empty fallback never confused with revision zero | EXECUTION (`committed_strict` + `test_a_transient_failed_read_retries…`) |
| 7 | revision jumps safe without observing intermediates | EXECUTION (`test_manifest_watcher_ignores_files_deduplicates_and_tolerates_a_jump`) |
| 8 | duplicate announcements harmless | EXECUTION (backend, same test) |
| 9 | replacement generations leak no old-generation pixels/metadata | EXECUTION (`test_replacement_generation_advances_both_stable_views_together`; browser scenario A replacement step) |

### Backend / live state

| # | Invariant | Status |
| --- | --- | --- |
| 10 | one tracker per run across viewers and requests | EXECUTION (`test_live_registry_follows_the_production_open_and_close_routes`) |
| 11 | no watcher/thread/fd/state leak on open/close | READING (registry prunes by root; manifest holds no persistent handles) |
| 12 | watcher observes only the small marker | EXECUTION (`test_idle_observation_stats_only_the_marker…`; 200 idle observes read 0 history events) |
| 13 | watcher failures degrade safely | **PARTIAL** — tracker-level yes (EXECUTION); thread-level guard missing, see F6 |
| 14 | live-state bounded by products/views, not positions | EXECUTION (80 positions → 2 sources, 513→516 bytes) |
| 15 | committed time explicit; no gap exposed from declared shape | EXECUTION (`test_gapped_commits_have_ranges…`, mutation 2) |
| 16 | ranges rather than a high-water mark | EXECUTION (same; `frames` emitted only when contiguous from 0) |
| 17 | ETag identifies an immutable snapshot | EXECUTION (`test_damaged_marker_serves_last_good_state…`; document and ETag computed from one pinned snapshot in `captured_live_state`) |
| 18 | an SSE hint never suppressed because another path read first | EXECUTION (`test_manifest_watcher_still_nudges_if_an_api_request_observed_first`) |

### Gateway / source identity

| # | Invariant | Status |
| --- | --- | --- |
| 19 | stable raw/seamless URLs across revisions | EXECUTION (browser scenario A asserts `stable_urls` unchanged across three revisions) |
| 20 | revision never in the URL | EXECUTION (mutation 4; `_the_address_of`) |
| 21 | revision travels as metadata | EXECUTION (`CompiledSource.revision`; browser) |
| 22 | production gateway fail-closed | EXECUTION (`test_live_publication_gateway.py`, mutation 1) |
| 23 | raw and seamless advance together | EXECUTION (browser scenario A: refreshed set is exactly the two overview sources) |
| 24 | affected source refreshes though its URL is unchanged | EXECUTION (browser scenario A and t=1) |
| 25 | unrelated acquisitions make no requests | EXECUTION (`test_one_run_commit_makes_no_requests_for_an_unrelated_live_run`, passed unmodified) |

### Neuroglancer / frontend

| # | Invariant | Status |
| --- | --- | --- |
| 26 | refresh inside the existing layer/source | EXECUTION (`zmartLayersReshaped == 0`) |
| 27 | camera and zoom unchanged | EXECUTION (scenario A) |
| 28 | valid z/time selection unchanged | EXECUTION (scenario A and t=0/t=1) |
| 29 | annotations unchanged | EXECUTION (scenario A) |
| 30 | contrast, LUT, opacity, visibility, order unchanged | EXECUTION (scenario A) |
| 31 | no source/layer per position | EXECUTION (80 positions → 2 compiled sources) |
| 32 | no global cache clear | **VIOLATED** — F2 |
| 33 | invalidation scoped to affected source identities | **VIOLATED** on the gap-fill path — F2; correct on the ordinary path (EXECUTION) |
| 34 | selective decoded invalidation safe with refcounting | EXECUTION (t=1 cached-empty refresh; `forgetOneStableSource` invalidates rather than deletes holders) |
| 35 | unchanged conditional check causes no work | EXECUTION (scenario A idle block: no `/data/` requests, refresh passes unchanged) |
| 36 | missed hint recovered by reconnection and/or the slow check | EXECUTION — by my Scenario E test, **not** by the shipped one (F3) |
| 37 | bursts coalesce | EXECUTION (backend dedup test; reviewer browser test: 3 commits in rapid succession → 3 config requests, converged to the newest revision, 0 layer reshapes) |
| 38 | duplicate announcement causes no redundant work | EXECUTION (reviewer browser test: 10 duplicate hints → 0 pixel requests, 0 sources refreshed, sync passes unchanged) |
| 39 | generic folder events do not drive recognised ZMART runs | EXECUTION (`FolderWatcher(excluding=live_registry.dataset_numbers)`; `test_initially_damaged_manifest_never_falls_back_to_folder_inference`) |
| 40 | existing static and generic live-folder behaviour intact | EXECUTION (full `viz_studio` suite: 582 passed; the only non-F1 failure is a pre-existing frame-rate floor that fails identically on the base branch — see §4) |

---

## 4. Test evidence

Setup, once: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` and
`npm --prefix viz_studio/frontend install && npm --prefix viz_studio/frontend run build`.

*(Installing into the container's system Python fails building `proxy_tools` against the
Debian setuptools patch. That is an environment artefact, not a defect of this branch; a
venv installs cleanly.)*

**Unit and integration**

```
.venv/bin/pytest -q zmart_live/tests viz_studio/tests/test_live_publication_gateway.py
→ 512 passed in 88.53s

.venv/bin/pytest -q viz_studio/tests/test_manifest_driven_refresh.py \
                    viz_studio/tests/test_frontend_live_refresh_contract.py
→ 13 passed

ZMART_REQUIRE_BROWSER=1 .venv/bin/pytest -q viz_studio/tests
→ 5 failed, 582 passed, 51 skipped, 2 xfailed in 1205.02s
```

The five failures are the four browser tests of F1, plus
`test_the_drawing_keeps_up.py::test_the_drawing_rate_has_not_slid_further`. That last one
is **not a regression from this branch**: I built the base branch in a separate worktree
and ran the same test there, and it fails the same way.

| Branch | 20 positions | 200 positions | ratio | threshold |
| --- | --- | --- | --- | --- |
| PR #8 | 76 frames / 3 s | 17 frames / 3 s | 22 % | ≥ 25 % |
| base `2027f911` | 74 frames / 3 s | 17 frames / 3 s | 23 % | ≥ 25 % |

The test's own docstring warns that a busy machine moves this ratio; this container renders
in software with no GPU, so I read it as an environment floor rather than a code change.
Everything else that failed on this branch is F1.

**Mutation / fault**

```
.venv/bin/python -m zmart_live.tests.check_the_live_refresh_tests_can_fail
→ 6 faults introduced, 6 caught, every subject restored
```

Harness inspected and challenged — see F9. It is strict in the two ways that matter
(green baseline required; exit status 2 is explicitly *not* a catch), and incomplete in
coverage.

**Frontend static / pure contract**

```
npm --prefix viz_studio/frontend run build     → built, 1.71 MB bundle
.venv/bin/ruff check <changed .py files>       → All checks passed
.venv/bin/ruff check zmart_live viz_studio     → 105 errors (base branch: 107 — pre-existing)
git diff --check <base>...HEAD                 → clean
```

**Browser**

```
ZMART_REQUIRE_BROWSER=1 pytest -q viz_studio/tests/test_manifest_refresh_browser.py
→ 4 failed in 7.01s          (F1 — none reached an assertion)
```

With the three test-only defects corrected in a scratch copy:

```
test_positions_and_replacement_appear_from_commits_and_keep_operator_state  passed
test_uncommitted_time_is_not_offered_and_cached_empty_time_refreshes        passed
test_one_run_commit_makes_no_requests_for_an_unrelated_live_run             passed
test_lost_sse_hint_is_recovered_by_conditional_check_and_eventsource_…      failed (F3)
```

Reviewer-authored browser tests:

```
test_review_suppressed_announcement_is_recovered_by_conditional_check   passed
test_review_lost_hint_is_really_recovered_without_any_sse_message       failed → proves F3
test_filling_a_committed_time_gap_flushes_every_decoded_source          failed → proves F2
test_duplicate_and_burst_hints_converge_without_proportional_work       passed
```

That last one is the brief's Scenario D, which the branch does not cover in a browser:

```
10 duplicate hints -> /api/config requests=6  pixel requests=0
                      refreshed sources=[]    sync passes 1->1
burst of 3 commits  -> /api/config requests=3
                      refreshed={seamless/overview, non_seamless/overview}
                      layers reshaped=0
```

Ten identical hints with no manifest change reached Neuroglancer as exactly nothing. Three
publications landing back-to-back converged on the newest revision and refreshed only the
two affected sources.

All reviewer test files were written outside the repository or deleted afterwards; the
working tree is unmodified (`git status` clean).

**Performance measurements**

| Measurement | Result |
| --- | --- |
| live-state payload, 1 → 80 positions | 513 → 516 bytes (the revision's digits) |
| compiled sources, 80 positions | 2 |
| history events read across 80 commits | 80 — exactly one per publication |
| 200 idle `observe()` calls | ~0 ms, 0 history events read, 0 marker parses |
| `observe()` after commit #2 → #80 | 5.47 ms → 6.53 ms |
| pixel requests during idle conditional checks (browser) | 0 |
| decoded holders dropped on a gap-fill commit | 4 — i.e. all of them (F2) |

`observe()` grows at roughly 13 µs per position because `build_the_scene` rebuilds one
`SceneImage` per position on every accepted revision. Extrapolated — and this *is* an
extrapolation, I did not run it — a 10,000-position run would spend on the order of
130 ms per commit inside the tracker. That is server-side and bounded by the commit rate,
and the frontend payload stays flat, so it is a note rather than a finding.

---

## 5. Browser qualification

**The A → B scenario and the t=0 → t=1 scenario did execute in a real browser**, and both
passed — but only after I corrected three defects in the test file, and only in a scratch
copy. As the branch stands, neither scenario executes anywhere.

Details: Chromium 141 (`/opt/pw-browsers/chromium-1194` and `-1234`, selected by the
repository's own `find_a_chromium` fallback because Playwright 1.62's headless-shell build
is absent from this image). Software rendering, 1200×900 viewport, `fraction_lit` pixel
measurement as the suite defines it. The positive control held throughout: position A
measured above the 0.04 lit-fraction floor before B was written, was within 0.04 of that
value while B sat uncommitted on disk, and rose by more than 0.05 when B was committed.
A black screen could not have produced that sequence.

Also executed in a real browser, by tests I wrote for this review: the brief's Scenario D
(duplicate and burst hints) and Scenario E (a genuinely suppressed hint).

Not executed: the standalone Node harnesses under `zmart_live/tests/browser/` and their
`check-the-*-can-fail.mjs` campaigns; Windows/SMB behaviour of any kind. In my first full
run, 42 further browser tests skipped because the drawing-options comparison page had not
been built — that was my setup gap, not the branch's; I built it afterwards. Those tests
exercise the options harness, which this diff does not touch.

---

## 6. Scope and design assessment

| Divergence from the handoff | Judgement |
| --- | --- |
| `zmart-live-frontend-state-set/1` wrapper around per-run documents | **improvement** — `viz_studio` genuinely opens several runs, and the per-run schema is preserved inside |
| One acquisition type per manifest run, rather than `overview:*` and `target:*` in one document as the handoff's example JSON shows | **neutral**, but undocumented. `_compile` derives a single committed-time range from `(layout.acquisition_type, layout.profile_id)` and applies it to every source of that run, which is only correct because one run carries one acquisition. The handoff's illustrative payload implies otherwise and should be corrected, or the assumption should be asserted in code. |
| Config rows and their live-state document pinned to one tracker snapshot | **improvement** — closes a real race between a commit and config construction |
| Decoded-holder invalidation by exact memo-key prefix instead of deleting memo entries | **improvement** — respects Neuroglancer's reference counting, and the reasoning is written down |
| `committed_strict()` alongside `committed()` | **improvement** — this is the distinction the whole watcher depends on |
| Legacy `frames` field retained beside `committedTimeRanges` | **risky** — it is the input to F2, and it is the one place where the old high-water vocabulary still reaches new code |

Nothing in the diff expands scope into microscope control, stitching, physical view chunks
or per-position sources. `git diff --check` is clean and the changed Python files pass the
repository's own Ruff configuration.

One documentation point: `docs/design/manifest-driven-frontend-refresh-handoff.md:3–5`
states the production browser scenarios "are part of the suite and must be run on a
Chromium-capable machine before making a visual qualification claim". Given F1, the first
half of that sentence is not currently true, and the document should not claim it until
the tests run.

---

## 7. Final recommendation

**Request changes.** The architecture is sound and the publication boundary is the real
thing — I attacked it from the manifest, the watcher, the API, the cache and the browser
and could not make it show data that had not been committed. Merge once the following are
done:

**Required before merge**

1. Fix the three defects in `viz_studio/tests/test_manifest_refresh_browser.py` (F1) and
   record an actual green run of all four tests with `ZMART_REQUIRE_BROWSER=1`.
2. Stop manifest-driven rows from reaching `anyStoreGainedItsFirstImage`, so filling a
   committed-time gap cannot cause a global cache flush (F2), and add a test that fails
   without the fix.
3. Rewrite the lost-hint test to suppress the announcement rather than the transport
   (F3), so it tests the invariant its name claims.

**Recommended, not blocking**

4. Reject degraded live state per-run instead of rejecting the whole document (F4).
5. Add the four missing mutations, especially the "A remains bright" sabotage aimed at
   the production page (F9).
6. Pin `playwright` in `requirements-dev.txt` and `.github/workflows/viewer.yml`.
7. Scope or explain the cross-run time control (F5); mirror `FolderWatcher`'s exception
   guard in `ManifestWatcher` (F6); clear the dead code in F7.
8. Correct the handoff's browser-qualification claim and its illustrative multi-acquisition
   payload.
