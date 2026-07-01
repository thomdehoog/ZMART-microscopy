# FV4000 RDK round-trip spike

**Goal:** prove the plumbing for an Evident **FLUOVIEW FV4000** driver on the **RDK route** — an
external Python client driving the scope over TCP with the Olympus/Evident RDK text protocol — using
a **mock RDK server**, so the whole loop runs offline with **no Evident software, license, or
microscope**. This is Track A of the [Evident findings doc](../README.md); Track B (obtaining the
real FV RDK from Evident) is the blocker for the real vocabulary.

## What this proves (and what it doesn't)

- ✅ **Transport + framing + client plumbing:** connect → login → command/query → `+`/values/`-`
  reply parsing, error handling, timeouts. Exercised end-to-end over a real localhost TCP socket.
- ❌ **NOT the FV4000's real behaviour.** The device verbs here (`MVSTG`, `CHOB`, …) are
  **placeholders** derived from the public [OLS5000 RDK sample](https://github.com/ospqul/OLS50C_RDK_Demo)
  — the closest openly documented member of the RDK family. Only the **framing** (`VERB= args` →
  `VERB= +`) is expected to match the real FV RDK. The verbs are quarantined to one method group in
  each of `rdk_client.py` / `mock_rdk_server.py`, so swapping in the real FV4000 vocabulary (once the
  Evident RDK reference is obtained) is a one-file change.

## Protocol (shape)

ASCII lines, CRLF-terminated. Request `VERB= arg1,arg2`; reply `VERB= +` (ack), `VERB= v1,v2`
(query values), or `VERB= -` (nak). Stage in **micrometers** (per OLS5000 `MVSTG`), objective by
**turret index**.

## Files

| File | Role |
|---|---|
| `rdk_protocol.py` | pure encode/parse of the `VERB= args` protocol (`Message`, `encode`, `parse`). |
| `mock_rdk_server.py` | fake RDK **TCP server**: holds stage/focus/objective state, speaks the protocol, supports error-injection + a login gate. |
| `rdk_client.py` | the **`RdkClient`** — connect/login/command/query + placeholder device convenience methods. Seed of the eventual `zmart_drivers/evident/fv4000/rdk/connection`. |
| `test_rdk_roundtrip.py` | offline tests: pure protocol + full client↔mock-server round-trip. |

## Run

```powershell
python -m pytest -q zmart_drivers/evident/spike/test_rdk_roundtrip.py
```

No Evident software required. (Try it live against your own server: `MockRdkServer(port=50100)` in one
process, `RdkClient("127.0.0.1", 50100)` in another.)

## Next steps

1. **Get the real FV4000 RDK** from Evident (developer program) — confirm FV4000 support, licensing,
   and the command reference. *This is the blocker.*
2. **Replace the placeholder verbs** in `rdk_client.py` / `mock_rdk_server.py` with the real FV RDK
   vocabulary (acquire/scan, laser, detector, Z, objective, queries).
3. **Point the client at a real target** — an Evident RDK simulator/offline mode (confirm it exists)
   or the FV4000 bench — and re-run.
4. **Grow into `zmart_drivers/evident/fv4000/rdk/`** — lift this client into a `connection` layer and add the
   Leica-style dispatch/commands/readers skeleton.

---

Author: Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com ·
License: MIT
