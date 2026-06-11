# Real-Scope Reader Matrix: API / LOG / HYBRID

Date/time: 2026-06-11 22:38-22:41 Europe/Berlin.

Operator context: LAS X was stated to be connected to the physical Leica STELLARIS microscope, not the simulator, and the run was explicitly authorized for XY, Z, objective, and acquisition tests. The validator banner reports only `LasxApi (LAS X simulator or microscope)`, so the real-scope designation depends on the LAS X session state and operator confirmation.

Repository: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy`

Branch preflight:

- Branch: `fable5_tryout`
- Recent commits:
  - `0149be9 Harden hybrid select-job confirmation`
  - `ad89332 Default selected-job confirmation to hybrid`
  - `4a0722b Make the tools and docs express the three-family reader design`
  - `d6d8f30 Add selected-job hybrid confirmation with transition admissibility`
  - `e98f241 Route every command confirmation through one race wrapper`

The Git path in the prompt, `C:\ProgramData\MinicondaZMB\Library\bin\git.exe`, was not present on this machine. Preflight used the available Git at `C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\Library\mingw64\bin\git.exe`.

No code was changed and nothing was committed.

## Commands Run

```powershell
$repo = "Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy"
$py = "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe"
Set-Location $repo

& $py driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --allow-xy `
  --allow-z `
  --allow-objective `
  --allow-acquire `
  --state-reader-mode api `
  --show-driver-log `
  --output driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware_20260611_real_scope_api.jsonl

& $py driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --allow-xy `
  --allow-z `
  --allow-objective `
  --allow-acquire `
  --state-reader-mode log `
  --show-driver-log `
  --output driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware_20260611_real_scope_log.jsonl

& $py driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --allow-xy `
  --allow-z `
  --allow-objective `
  --allow-acquire `
  --state-reader-mode hybrid `
  --show-driver-log `
  --output driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware_20260611_real_scope_hybrid.jsonl
```

## JSONL Outputs

- API: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_real_scope_api.jsonl`
- LOG: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_real_scope_log.jsonl`
- HYBRID: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_real_scope_hybrid.jsonl`

## Summary Table

All three validator commands returned exit code 1 because each run had at least one FAIL record. The HYBRID run's FAIL records are post-command selected-job readback comparisons against stale API state, not command-confirmation failures.

| Mode | Confirmation Source Implied | PASS | WARN | FAIL | SKIP | Accepted For This LAS X Version |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `api` | API | 80 | 1 | 4 | 1 | Rejected for selected-job confirmation; accepted for XY/Z/objective/acquire |
| `log` | LOG | 81 | 0 | 3 | 1 | Accepted for selected-job confirmation; rejected as a general default reader |
| `hybrid` | HYBRID | 84 | 0 | 2 | 0 | Accepted as default confirmation policy, with validator grading caveat |

## Failure Table

| Mode | Record | Message / Expected Actual | Confirmation Source / Diagnostics | Classification |
| --- | --- | --- | --- | --- |
| API | `job selection: select job` (`Overview`) | `SelectJob 'Overview' (readback unconfirmed); [total=15.221s, att=3, conf=3, m=async]` | API confirmation attempted; driver log has three `Job selection timeout after 5.0s for 'Overview'` messages and `last_confirmation={'source': 'api'}`. | Known API selected-job stale/readback limitation on real scope. |
| API | `job selection: confirmed Overview` | expected `Overview`, actual `AF Job` | Post-command selected-job readback still API-backed. | Known stale API readback / validator comparison failure. |
| API | `job selection: select job` (`HiRes`) | `SelectJob 'HiRes' (readback unconfirmed); [total=15.226s, att=3, conf=3, m=async]` | API confirmation attempted; driver log has three `Job selection timeout after 5.0s for 'HiRes'` messages and `last_confirmation={'source': 'api'}`. | Known API selected-job stale/readback limitation on real scope. |
| API | `job selection: confirmed HiRes` | expected `HiRes`, actual `AF Job` | Post-command selected-job readback still API-backed. | Known stale API readback / validator comparison failure. |
| LOG | `job: resolve` | `no jobs returned with --state-reader-mode log` | LOG passive job list was not available at startup; validator used API control jobs for the write experiment. | Known log job-list freshness/source limitation. |
| LOG | `job selection: confirmed Overview` | expected `Overview`, actual `AF Job` | The command itself log-confirmed. Extra log poll matched `Overview`; `CurrentBlock` diagnostics: `current_block_name=Overview`, `current_block_after_command=True`, `cluster_complete=True`. The failing comparison is immediate API readback. | Validator grading artifact caused by stale API readback after successful log confirmation. |
| LOG | `job selection: confirmed HiRes` | expected `HiRes`, actual `AF Job` | The command itself log-confirmed. Extra log poll matched `HiRes`; `CurrentBlock` diagnostics: `current_block_name=HiRes`, `current_block_after_command=True`, `cluster_complete=True`. The failing comparison is immediate API readback. | Validator grading artifact caused by stale API readback after successful log confirmation. |
| HYBRID | `job selection: confirmed Overview` | expected `Overview`, actual `AF Job` | Command confirmed by log leg: `SelectJob 'Overview' | confirmed by log leg (2.187s)`; API leg was still pending and abandoned. The failing comparison is immediate API readback. | Validator grading artifact; HYBRID command behavior is correct. |
| HYBRID | `job selection: confirmed HiRes` | expected `HiRes`, actual `AF Job` | Command confirmed by log leg: `SelectJob 'HiRes' | confirmed by log leg (0.578s)`; API leg had not confirmed. The failing comparison is immediate API readback. | Validator grading artifact; HYBRID command behavior is correct. |

Warnings and skips:

- API WARN: `sequential_mode: write alternate` to `Line` was unconfirmed after about `15.199 s`; `sequential_mode: readback` was then skipped. This did not recur in LOG or HYBRID, where sequential mode write/readback/restore passed.
- LOG SKIP: `xy: round-trip -- get_xy returned None`. No XY move was performed in LOG mode.
- HYBRID had no WARN or SKIP records.

## Selected-Job Confirmation Analysis

| Mode | Target | Command Status | Winning Leg | Timing / Diagnostics | Follow-up Readback |
| --- | --- | --- | --- | --- | --- |
| API | `Overview` | FAIL | Neither; API attempted and timed out | `15.221 s`, 3 confirmation attempts | API readback `AF Job` |
| API | `HiRes` | FAIL | Neither; API attempted and timed out | `15.226 s`, 3 confirmation attempts | API readback `AF Job` |
| API | `AF Job` | PASS | API/precheck no-op | Already selected, `0.012 s` driver total | `AF Job` |
| LOG | `Overview` | PASS | LOG `CurrentBlock` | Driver log-confirmed in `531 ms`, attempts 2; extra log poll matched in `0.219 s` | API readback still `AF Job` |
| LOG | `HiRes` | PASS | LOG `CurrentBlock` | Driver log-confirmed in `531 ms`, attempts 2; extra log poll matched in `0.203 s` | API readback still `AF Job` |
| LOG | `AF Job` | PASS | LOG `CurrentBlock` | One 2.0 s log-backed timeout, then log-confirmed in `1141 ms`, attempts 4; extra poll matched in `0.203 s` | `AF Job` |
| HYBRID | `Overview` | PASS | LOG leg | `confirmed by log leg (2.187s)`; API leg still pending and abandoned | API readback still `AF Job` |
| HYBRID | `HiRes` | PASS | LOG leg | `confirmed by log leg (0.578s)`; API confirmation leg skipped/in flight and had not confirmed | API readback still `AF Job` |
| HYBRID | `AF Job` | PASS | LOG leg | First attempt had no confirming leg after `2.203 s`; second attempt log-confirmed in `1.234 s`; API had not confirmed | `AF Job` |

Answers to the required checks:

- Did HYBRID confirm real job switches? Yes. HYBRID confirmed `Overview`, `HiRes`, and `AF Job` through the log leg.
- Did HYBRID avoid stale-API false confirmation? Yes. For `Overview`, the API leg was still pending and was abandoned when the log leg won. For `HiRes` and `AF Job`, the API leg had not confirmed when the log leg confirmed. No selected-job switch was accepted from stale API evidence.
- Did restore/no-op early-exit correctly? Yes. Final restore reported `'AF Job' already selected` with the selected job already confirmed from the LAS X log. The earlier `AF Job` step after `HiRes` was a real transition, not a no-op, and it eventually log-confirmed.
- Did objective switching show any dialog/blocking issue? No blocking dialog or failure was recorded. HYBRID objective switch and restore both passed, but were slow: switch `7.108 s`, restore `8.457 s`. API objective switch/restore were also PASS and much faster (`0.030 s` / `0.025 s`). LOG mode read objective hardware/start but did not perform an objective switch.
- Did acquire pass? Yes. API, LOG, and HYBRID all passed acquisition of `AF Job`.

## Motion And Acquire Outcomes

| Mode | XY | Z | Objective | Acquire |
| --- | --- | --- | --- | --- |
| API | PASS. Moved to `(32125.1806640625, 28452.36328125) um`, readback passed, restored to `(32100.1806640625, 28427.36328125) um`. | PASS. Moved to `2.0 um`, readback passed, restored to `0.0 um`. | PASS. Switched to 40x water and restored 10x dry. | PASS, `18.591 s`. |
| LOG | SKIP. `get_xy` returned None, so no XY move was performed. | PASS. Moved to `2.0 um`, readback passed, restored to `0.0 um`. | Read hardware/start only; no switch record emitted. | PASS, `14.181 s`. |
| HYBRID | PASS. Moved to `(32125.1806640625, 28452.36328125) um`, readback passed, restored to `(32100.1806640625, 28427.36328125) um`. | PASS. Moved to `2.0 um`, readback passed, restored to `0.0 um`. | PASS. Switched to 40x water and restored 10x dry. | PASS, `0.204 s`. |

## Comparison With Simulator Expectation

Simulator expectation from the prompt:

- API wins selected-job.
- LOG is often insufficient.
- HYBRID has one known fail-closed no-op edge.

Real-scope result:

- API did not win selected-job transitions. It timed out for `Overview` and `HiRes` and kept reading `AF Job`.
- LOG won real selected-job transitions quickly enough to be usable for command confirmation, but it is still incomplete as a general passive reader because startup job resolution failed and XY start state was unavailable in LOG mode.
- HYBRID behaved as intended for command confirmation on the real scope: it accepted the first admissible source, which was the log `CurrentBlock` leg for selected-job transitions, and it did not accept stale API evidence. The remaining HYBRID FAIL records are validator post-command comparisons against stale API readback, not failed HYBRID command confirmations.

## Conclusion

For LAS X `1.0.108.0` on this real microscope:

- `api`: rejected for selected-job confirmation. API remains acceptable for general passive reads and for XY/Z/objective/acquire workflows where API readback is the relevant source.
- `log`: accepted for selected-job confirmation. Rejected as the sole general default reader because LOG mode still failed startup job resolution and skipped XY.
- `hybrid`: accepted as the default reader/confirmation policy for real-scope workflows, with a validator grading caveat. HYBRID selected-job command confirmation is safe in this run because the log leg won and stale API was not accepted.

Recommended default policy:

- Use `hybrid` as the default reader/confirmation profile for this LAS X version.
- For selected-job command confirmation, allow the log `CurrentBlock` leg to win over stale/pending API.
- Keep API-backed paths available for XY, Z, objective, hardware info, and general readback where LOG has gaps.
- Update the validator grading logic so the post-command `job selection: confirmed <job>` check uses the same selected-job truth source as the command confirmation, or records API disagreement as diagnostic WARN rather than FAIL after a log/hybrid-confirmed switch.
