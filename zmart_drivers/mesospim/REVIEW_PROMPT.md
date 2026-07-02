# Review prompt — mesoSPIM ZMART driver

Paste the block below to a reviewer (human or an AI code-review agent). It scopes
the review to the mesoSPIM driver as it sits **on the `driver-cleanup` branch**.

---

You are reviewing a new microscope driver, `zmart_drivers/mesospim/`, added on top
of the `driver-cleanup` branch of the ZMART-microscopy repo. Review **only** the
mesoSPIM diff against `driver-cleanup`; treat the rest of the repo as given.

**Get the diff and run the checks:**

```bash
git fetch origin driver-cleanup
# the driver is the delta between driver-cleanup and the mesoSPIM work:
git diff origin/driver-cleanup -- zmart_drivers/mesospim | less
# offline suite (no mesoSPIM, no hardware) — must be green:
cd zmart_drivers/mesospim && python -m pytest -q
ruff check zmart_drivers/mesospim
# resident-server Qt half, headless (needs PyQt5, no display):
QT_QPA_PLATFORM=offscreen python zmart_drivers/mesospim/server/validate_headless.py
```

**Context (what the driver is).** mesoSPIM-control is a GPL PyQt5 app with no
external API. The driver is an **MIT** socket client speaking a JSON-lines
protocol (`protocol.py`, `server/PROTOCOL.md`) to a **resident command-server
script** (`server/mesospim_command_server.py`, the only GPL file) loaded inside
mesoSPIM via its Script Window. `controller.py` registers the driver's ops with
`zmart_controller` (the vendor-neutral controller). The sibling drivers are
`zmart_drivers/zeiss/zenapi/` and `zmart_drivers/leica/.../navigator_expert/` —
match their conventions (synchronous public API, `{success, confirmed, message,
data, timing, logs}` command envelope, profile-driven tuning).

**Review these dimensions. For each finding, give: file:line, severity
(blocker/major/minor/nit), why it's wrong (a concrete failing input/state), and a
suggested fix. Rank findings most-severe first.**

1. **Controller contract** (`controller.py` vs `zmart_controller/registry.py` +
   `tests/mock_driver.py`): every op in `registry.OPS` implemented with the right
   signature? Is the frame-origin arithmetic correct (user = raw − origin on read
   *and* write)? Is the immutable/mutable `get_state`/`set_state` boundary sound,
   and does `set_state` actually reject a foreign instrument? Does `acquire`
   capture **and** save in one call? Is the `_settle` backlash nudge safe (could
   it drive into a limit or the sample)?

2. **Protocol + client** (`protocol.py`, `connection/`): framing/round-trip,
   request-id matching, NAK vs transport-error handling, the single-lock
   threading model (any deadlock if a `confirm_fn` reads while a command is in
   flight?), connect/close idempotency, timeouts. Does the client enforce a
   protocol version? (It currently doesn't — is that acceptable?)

3. **Dispatch backbone** (`commands/dispatch.py`): is the transient-vs-permanent
   split right (retry transport, never retry a NAK)? Confirm/re-fire loop and the
   `success_on_unconfirmed` policy. Is the freshness gate (`_reading_value_after`
   + `observed_after`) actually preventing a pre-command readback from confirming?

4. **Commands + limits** (`commands/commands.py`, `config/limits.py`): are limit
   checks applied **before** any fire (no stage motion on a rejected target)? Does
   `move_relative` correctly baseline + limit-check the expected absolute target?
   Units (µm for x/y/z/f, deg for theta). **Design call to scrutinise:** an
   unconfigured axis limit is silently *unchecked* — is "no limit set ⇒ allow
   anything" safe for a light-sheet with a mounted sample, or should it fail
   closed?

5. **Acquisition + save** (`acquisition/`): frame-file relocation correctness,
   multi-plane naming/order, metadata fidelity, and error paths (missing source
   file, zero frames returned). Any pixel corruption risk (it copies, doesn't
   re-encode — verify)?

6. **License boundary** (the crux of the design): does any **MIT** file import
   the **GPL** `server/mesospim_command_server.py`? (The offline tests use an
   independent mock server, `tests/helpers/mock_mesospim_server.py` — confirm the
   separation holds. `server/validate_headless.py` is GPL-area and may import it.)

7. **Resident server** (`server/mesospim_command_server.py`): are the Core
   bindings in `_CoreBridge` correct against mesoSPIM-control (v1.20.0 names are
   claimed)? The image-writer output-path resolution (`_written_files`) and the
   acquisition run sequence are the most site-specific — flag anything that would
   silently return wrong/empty paths. Does the reply `pixels` shape match
   `PROTOCOL.md` (`[x, y]`)?

8. **Tests** (`tests/`): do they assert real behaviour (not just "no exception")?
   Socket/thread flakiness? Does the mock server faithfully implement
   `PROTOCOL.md`? What's *not* covered (name the gaps)?

9. **Docs + consistency**: does `PROTOCOL.md` match the code? Is `README.md` /
   `TODO.md` accurate about what's done vs. pending? Does the package match the
   naming, envelope, and profile conventions of the `zenapi` / `navigator_expert`
   siblings?

**Known-and-accepted (don't re-report unless you find them actually wrong):**
`-D`-demo bench validation of the live Core is deliberately outstanding (see
`TODO.md`); the driver is offline/mock-tested only; procedures `autofocus` /
`find_sample` are forwarded to a server verb the resident script currently NAKs.

Finish with a short verdict: is the mesoSPIM diff safe to keep on
`driver-cleanup`, and what (if anything) must change before a live bench run.
