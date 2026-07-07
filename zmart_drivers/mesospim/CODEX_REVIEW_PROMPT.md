# Review prompt — mesoSPIM ZMART driver + Remote Scripting server

Paste this to Codex (or run it as a review task) from the repo root. It is a
review request, not an implementation task: **find problems, don't rewrite.**

---

You are reviewing a light-sheet-microscope control driver and the small upstream
patch it depends on. Be skeptical and concrete. Prioritise **correctness** and
**security**; call out over-engineering too, but only after the first two.

## What this is (context)

- `zmart_drivers/mesospim/` — an **MIT** Python driver that controls
  **mesoSPIM-control** (a GPL PyQt5 acquisition app) from another process.
- mesoSPIM has no external API, so the driver talks to a small server added *in
  mesoSPIM* by the patch under `zmart_drivers/mesospim/pull_request/` (GPL). The
  server accepts **named calls, not code**: the client sends a single-key JSON
  object `{"<method>": {args}}` (or MCP-over-HTTP), the server looks the method
  up in a fixed allowlist (`COMMANDS`) and runs the matching `mesoSPIM_Core`
  method — the same methods the GUI's own buttons call. **No client Python is
  ever executed.**
- Two lanes over one TCP port: **framed TCP** (scripts) and **MCP over HTTP**
  (LLMs), both landing on one dispatch. Off by default, binds 127.0.0.1, optional
  shared token, and an Origin guard on the HTTP lane.

## Read these first (highest-risk, in order)

1. `pull_request/0001-*.patch` → the new file `mesoSPIM_RemoteScripting.py`. This
   runs **inside** mesoSPIM. The security of the whole thing lives here:
   `_dispatch` / `COMMANDS` (the allowlist), `handle_message` (TCP lane),
   `_mcp_reply` (MCP), `_http_handle` / `_http_feed` (the hand-rolled HTTP), and
   `AuthGate` / `FrameDecoder`.
2. `connection/command_api.py` — the client-side mirror of the allowlist (used by
   the offline mock).
3. `protocol.py`, `connection/client.py` — the wire codec and the framed client.
4. `commands/`, `readers/`, `acquisition/`, `controller.py` — the driver layers.
5. Tests: `pull_request/test_remote_scripting.py` (the real server, incl. an
   end-to-end pass) and `tests/` (the driver vs a mock).

## Review these dimensions

**Security (scrutinise hardest — a call moves a real stage / fires lasers):**
- Can anything outside `COMMANDS` ever execute? Try to defeat the "method is only
  ever a dict key" claim (injection via the method name, args, MCP `tools/call`
  name, nested/oversized payloads).
- Token check: is `hmac.compare_digest` used correctly on both lanes (framed
  first-frame token AND HTTP `Authorization: Bearer`)? Any timing/bypass?
- HTTP Origin guard vs DNS-rebinding/CSRF: is the localhost-Origin allowlist
  actually sufficient? Any header-parsing bypass (case, whitespace, duplicate
  headers, missing `Content-Length`, chunked, request smuggling on keep-alive)?
- The hand-rolled HTTP parser in `_http_feed`/`_http_handle`: framing errors,
  unbounded buffering, integer parsing, partial reads.
- Is "off by default / 127.0.0.1 / plain-TCP not sniffer-proof" honestly stated?

**Correctness:**
- The `COMMANDS` handlers vs the real `mesoSPIM_Core` v1.20.0 API (move/state/
  config/acquire). The acquisition flow (`acquire_start` → `stat_files` →
  `acquire_finish`) and the `acq_list` stash/restore.
- Framing edge cases (`FrameDecoder`): split/joined frames, negative/huge length.
- Error paths: does every bad input become a clean error reply (never a crash,
  never a silent success)?
- Client transport: reconnect, timeouts, one-request-at-a-time locking.

**Design / over-engineering (last):**
- Dead code, speculative flexibility, needless abstraction, duplication that
  isn't justified by the MIT/GPL boundary.

## Output

Give a ranked list, worst first. For each: **file:line**, a one-line problem
statement, a concrete failure scenario (inputs → wrong/unsafe result), and a
suggested fix. Separate **must-fix** (correctness/security) from **nice-to-have**.
If a claim in the docs/comments is wrong, flag it. If you find nothing in a
dimension, say so explicitly rather than padding.

Note: the offline suite (`python zmart_drivers/mesospim/run_ci.py`) is green and a
live-hardware bench run is still pending (see `BENCH_RUN.md`) — so "untested
against a real Core" is known; focus on what the code itself guarantees.
