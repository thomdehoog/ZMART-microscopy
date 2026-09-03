"""The mock instrument's own window: what LAS X is to the Leica.

On the microscope the operator sets the instrument up in its own software
-- picks the job, and with it the objective and the frame -- and then, on
the operator page, presses Import. The page reads the instrument as it
stands and never chooses for it. The mock has no software of its own, so
this window is it: the jobs the mock driver offers, one press apiece, and
the frame each one images.

    python mock-instrument.py

It needs no bridge and no session. The mock keeps its settings in one file
(see ``where_the_instrument_stands`` in the driver); a press here writes
it, and the driver reads it back on every readout and capture, whether the
operator window is open or not. Choose Target here, close everything, and
tomorrow's session still stands on Target -- as a real instrument would.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zmart_drivers.mock import mock_driver  # noqa: E402

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Mock instrument</title>
<style>
  body { margin: 0; padding: 18px 20px; font: 13px system-ui, sans-serif; color: #111827; background: #f8fafc; }
  h1 { font-size: 13px; letter-spacing: .08em; text-transform: uppercase; color: #6b7280; margin: 0 0 12px; }
  .job { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; margin: 4px 0;
         border: 1px solid #d1d5db; border-radius: 6px; background: #fff; cursor: pointer; font: inherit; text-align: left; }
  .job[aria-pressed="true"] { border-color: #2563eb; background: #eff6ff; }
  .job .lamp { width: 8px; height: 8px; border-radius: 50%; background: #d1d5db; flex: none; }
  .job[aria-pressed="true"] .lamp { background: #2563eb; }
  .job .frame { margin-left: auto; font-family: ui-monospace, monospace; font-size: 12px; color: #6b7280; }
  .note { margin-top: 12px; font-size: 12px; color: #6b7280; line-height: 1.4; }
  .where { font-family: ui-monospace, monospace; font-size: 11px; color: #9ca3af; word-break: break-all; margin-top: 8px; }
</style>
<h1>Mock instrument · job</h1>
<div id="jobs"></div>
<div class="note">The operator page imports the instrument as it stands: choose the job here, then press Import there.</div>
<div class="where" id="where"></div>
<script>
  const jobs = document.getElementById("jobs");
  async function show() {
    const state = await window.pywebview.api.state();
    jobs.textContent = "";
    for (const one of state.jobs) {
      const b = document.createElement("button");
      b.className = "job"; b.type = "button";
      b.setAttribute("aria-pressed", String(one.name === state.job));
      b.innerHTML = '<i class="lamp"></i>';
      b.append(one.name);
      const frame = document.createElement("span");
      frame.className = "frame";
      frame.textContent = one.frame;
      b.append(frame);
      b.addEventListener("click", async () => { await window.pywebview.api.choose(one.name); show(); });
      jobs.append(b);
    }
    document.getElementById("where").textContent = state.where;
  }
  window.addEventListener("pywebviewready", () => { show(); setInterval(show, 2000); });
</script>
"""


class Api:
    """The instrument's settings, read and written through the driver's own
    file so the format has one owner."""

    def state(self) -> dict:
        held = mock_driver.read_instrument_settings()
        job = held.get("job", mock_driver.MockHandle().job)
        return {
            "job": job,
            "jobs": [
                {"name": name, "frame": self._frame(name)} for name in mock_driver._JOBS
            ],
            "where": str(mock_driver.where_the_instrument_stands()),
        }

    @staticmethod
    def _frame(job: str) -> str:
        px, um = mock_driver._frame_of(job, "")
        return f"{px * um:g} × {px * um:g} µm · {um:g} µm/px"

    def choose(self, job: str) -> dict:
        mock_driver.write_instrument_settings({"job": job})
        return {"job": job}


def main() -> int:
    try:
        import webview
    except ImportError:
        print("pywebview is not installed in this environment")
        return 1
    webview.create_window("Mock instrument", html=PAGE, js_api=Api(), width=420, height=320)
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
