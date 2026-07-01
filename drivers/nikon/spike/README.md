# Round-trip spike — external orchestrator ↔ NIS-Elements 6.2

**Goal:** prove the Leica-symmetric loop end to end — an external Python process drives NIS over a
TCP socket and reads real state back — **before** the device-motion verb vocabulary is pinned. If
`?Get_Calibration` returns the objective + µm/px from a running NIS, the driver shape generalizes.

## Files

| File | Role |
|---|---|
| `nis_socket_server_roundtrip.mac` | Resident NIS macro. Loopback-bound TCP server; runs `!command` lines and answers `?query` lines. A focused fork of Nikon's `NkSocketServerDemo.mac`. |
| `nis_roundtrip_client.py` | ~120-line external Python client + `parse_reply()` and a `NisRoundTripClient` class. |
| `test_nis_roundtrip_client.py` | Offline pytest for the pure logic (framing + reply parsing). |

## Protocol

ASCII lines terminated by `\r`. Requests:

- `!<command>` — run the rest of the line as a NIS macro command (fire-and-forget, no reply). E.g. `!Capture();` once that verb is confirmed.
- `?<query>` — server computes a value and writes **one** pipe-delimited reply line:
  - `?ping` → `OK|pong`
  - `?Get_Calibration` → `OK|query=Get_Calibration|cal_um_per_px=0.323|aspect=1.0|unit=0|objective=Plan Apo 20x`
  - on failure → `ERROR|<reason>` (e.g. `ERROR|no image open - cannot read calibration`)

Reply fields are `key=value` separated by `|` (not whitespace) so the objective name may contain spaces.

## Run it on the bench (NIS 6.2)

1. **Install the macro libraries** if not already present: run `NkMacroLibs_6.20.00.exe` (it deploys
   `NkSocket.dll`/`NkWindow.dll` beside `nis_ar.exe` and the `*.mac` interfaces into
   `C:\Program Files\NIS-Elements\macros`).
2. Copy `nis_socket_server_roundtrip.mac` onto the NIS box and **run it** (Macro ▸ Run, or add to the
   macro browser). A small "SmartMicroscopy Round-Trip Server" dialog appears.
3. Confirm the port is `54468` and click **Listen**. Status shows `listening on 127.0.0.1:54468`.
4. **Open an image** (or start Live) so `Get_Calibration` has a document to report — otherwise the
   server replies `ERROR|no image open`.
5. From the same box (loopback), run the client:
   ```
   python nis_roundtrip_client.py
   ```
   Expected:
   ```
   ping  -> OK|pong
   calib -> OK|query=Get_Calibration|cal_um_per_px=0.32300|aspect=1.0000|unit=0|objective=...
     objective    : ...
     um per pixel : 0.32300
   ```
   Fire a command instead: `python nis_roundtrip_client.py --command "Capture();"`.

## Offline test (no bench needed)

```
pytest test_nis_roundtrip_client.py
```
Covers reply parsing (incl. spaced objective names), error replies, and the `\r` terminator contract.

## Security

`!` executes arbitrary macro text off the socket. This spike binds **127.0.0.1 only**. Before any
non-bench use, replace the blanket `!` branch in `NRT_OnTimer` with a command **allow-list**.

## Status & next step

- **Client pure logic:** covered by offline tests.
- **Server macro:** written against the proven `NkSocketServerDemo.mac` API usage but **not yet run
  on hardware** — it needs the NIS 6.2 bench. Treat the first bench run as the validation.
- **Next:** once the real `Stg*` / `Capture` / Z / objective verbs are confirmed from the NIS macro
  command reference, add them as `?query` getters / `!command` setters and grow this into
  `drivers/nikon/{connection,commands,readers}`.
