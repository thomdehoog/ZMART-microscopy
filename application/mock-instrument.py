"""The mock instrument's own window: what LAS X is to the Leica.

On the microscope the operator sets the instrument up in its own software
-- picks the job, and with it the objective and the frame -- and then, on
the operator page, presses Import. The page reads the instrument as it
stands and never chooses for it. The mock has no software of its own, so
this window is it: the jobs the mock driver offers, one press apiece, and
the frame each one images.

It is also where the pretend rig lives, for the ZMART driver configuration
workflow. A real microscope simply *is* mounted a certain way and *has* the
lenses it has; here those are chosen in this window -- turn the camera,
change the lens, drop a marker where the stage stands -- and the setup
workflow on the operator page has to measure them, the way it would on a
rig it cannot change. Underneath, the window shows what that workflow has
published so far, as the driver will read it at the next connect.

    python mock-instrument.py

It needs no bridge and no session. The mock keeps its settings in one file
(see ``where_the_instrument_stands`` in the driver); a press here writes
it, and the driver reads it back on every readout and capture, whether the
operator window is open or not. Choose Target here, close everything, and
tomorrow's session still stands on Target -- as a real instrument would.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zmart_drivers.mock import mock_driver, mock_setup  # noqa: E402

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

<h1 style="margin-top:22px">Mock instrument · the rig</h1>
<div class="note" style="margin:0 0 10px">What a real microscope simply <em>is</em>, and what an operator does in the
vendor's own software. The setup workflow measures these from the operator page; nothing there can change them.</div>
<div class="row"><span>Stage</span><span class="frame" id="stage"></span></div>
<div class="row"><span>Objective</span><span id="lenses"></span></div>
<div class="row"><span>Camera mounted</span><span id="camera"></span></div>
<div class="row"><span>Markers at the safe corners</span>
  <span><span class="frame" id="markers"></span>
  <button class="small" id="drop" type="button" title="Drop a marker where the stage stands now">Drop here</button>
  <button class="small" id="clear" type="button">Clear</button></span></div>

<h1 style="margin-top:22px">What the setup workflow published</h1>
<div class="note" style="margin:0 0 10px">The newest snapshot of each, as the driver will read it at the next connect.</div>
<div id="published"></div>
<style>
  .row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 0; border-bottom: 1px solid #e5e7eb; }
  .small { font: inherit; font-size: 12px; padding: 3px 8px; border: 1px solid #d1d5db; border-radius: 5px; background: #fff; cursor: pointer; margin-left: 6px; }
  .small[aria-pressed="true"] { border-color: #2563eb; background: #eff6ff; }
  .pub { display: grid; grid-template-columns: 9em 1fr; gap: 4px 10px; font-size: 12px; }
  .pub .k { color: #6b7280; } .pub .v { font-family: ui-monospace, monospace; word-break: break-all; }
</style>
<script>
  const jobs = document.getElementById("jobs");
  const byId = (id) => document.getElementById(id);
  function pressable(label, pressed, onPress) {
    const b = document.createElement("button");
    b.className = "small"; b.type = "button"; b.textContent = label;
    b.setAttribute("aria-pressed", String(pressed));
    b.addEventListener("click", async () => { await onPress(); show(); });
    return b;
  }
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
    byId("where").textContent = state.where;

    const rig = state.rig;
    byId("stage").textContent = rig.stage;
    const lenses = byId("lenses"); lenses.textContent = "";
    for (const lens of rig.objectives) {
      lenses.append(pressable(`${lens.slot} · ${lens.name} · ${lens.pixel_um} µm/px`,
        lens.slot === rig.objective_slot, () => window.pywebview.api.change_lens(lens.slot)));
    }
    const camera = byId("camera"); camera.textContent = "";
    for (const turn of [0, 90, 180, 270]) {
      camera.append(pressable(`${turn}°`, rig.camera.rotation_deg === turn && !rig.camera.reflection,
        () => window.pywebview.api.turn_camera(turn, false)));
    }
    camera.append(pressable("mirrored", rig.camera.reflection,
      () => window.pywebview.api.turn_camera(rig.camera.rotation_deg, !rig.camera.reflection)));
    byId("markers").textContent = rig.markers.length ? rig.markers.join("  ") : "none placed";
    byId("drop").onclick = async () => { await window.pywebview.api.drop_marker(); show(); };
    byId("clear").onclick = async () => { await window.pywebview.api.clear_markers(); show(); };

    const published = byId("published"); published.textContent = "";
    const grid = document.createElement("div"); grid.className = "pub";
    for (const [name, said] of Object.entries(state.published)) {
      const k = document.createElement("span"); k.className = "k"; k.textContent = name;
      const v = document.createElement("span"); v.className = "v"; v.textContent = said;
      grid.append(k, v);
    }
    published.append(grid);
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
            "rig": self.rig(),
            "published": self.published(),
        }

    # -- the rig: what the setup workflow measures, and cannot change ------

    @staticmethod
    def _root():
        return mock_setup.where_the_machine_is()

    def rig(self) -> dict:
        """The rig as it stands, in words the window shows."""
        rig = mock_setup.read_rig(self._root())
        stage = rig["stage"]
        return {
            "stage": f"x {stage['x_um']:.0f} · y {stage['y_um']:.0f} · z {stage['z_um']:.1f} µm",
            "objectives": [
                {"slot": o["slot"], "name": o["name"], "pixel_um": o["pixel_um"]}
                for o in rig["objectives"]
            ],
            "objective_slot": rig["objective_slot"],
            "camera": dict(rig["camera"]),
            "markers": [f"({p['x_um']:.0f}, {p['y_um']:.0f})" for p in rig.get("markers") or []],
        }

    def published(self) -> dict:
        """The newest snapshot of each subsystem, in one line apiece."""
        root = self._root()
        said = {}
        for subsystem in mock_setup.SUBSYSTEM_FILES:
            document = mock_setup.newest(mock_setup.configuration_root(root), subsystem)
            said[subsystem] = self._say(subsystem, document)
        return said

    @staticmethod
    def _say(subsystem: str, document: dict | None) -> str:
        if document is None:
            return "nothing published — the driver stands on its defaults"
        if subsystem == "limits":
            axes = ", ".join(
                f"{axis[0]} {document[axis]['range'][0]:g}…{document[axis]['range'][1]:g}"
                for axis in ("x_um", "y_um", "z_um") if axis in document
            )
            return f"{axes} µm"
        if subsystem == "orientation":
            return (f"{document.get('rotation_deg', 0)}°"
                    + (", mirrored" if document.get("reflection") else "")
                    + (" (measured)" if document.get("measured") else " (unmeasured)"))
        if subsystem == "calibration":
            lenses = document.get("objectives") or {}
            return f"{len(lenses)} objective(s): " + ", ".join(
                f"slot {slot} {o.get('name', '')} {o.get('pixel_um', '?')} µm/px"
                for slot, o in lenses.items()) if lenses else "no objectives measured"
        if subsystem == "origin":
            return f"({document.get('x_um', 0):g}, {document.get('y_um', 0):g}, {document.get('z_um', 0):g}) µm"
        return json.dumps(document)

    def change_lens(self, slot: int) -> dict:
        """The operator turns the turret: what a lens change is on a real rig."""
        rig = mock_setup.read_rig(self._root())
        if slot not in {o["slot"] for o in rig["objectives"]}:
            raise ValueError(f"no objective in slot {slot}")
        rig["objective_slot"] = int(slot)
        mock_setup.write_rig(self._root(), rig)
        return {"objective_slot": rig["objective_slot"]}

    def turn_camera(self, rotation_deg: int, reflection: bool) -> dict:
        """Remount the pretend camera: the rig property the orientation step measures."""
        if int(rotation_deg) not in (0, 90, 180, 270):
            raise ValueError("a camera is mounted by whole quarter-turns")
        rig = mock_setup.read_rig(self._root())
        rig["camera"] = {"rotation_deg": int(rotation_deg), "reflection": bool(reflection)}
        mock_setup.write_rig(self._root(), rig)
        return dict(rig["camera"])

    def drop_marker(self) -> dict:
        """Place a corner marker where the stage stands, the way an operator
        drops a Point marker in LAS X. Four of them are what the limits step
        reads; a fifth replaces the oldest."""
        rig = mock_setup.read_rig(self._root())
        stage = rig["stage"]
        markers = list(rig.get("markers") or [])
        markers.append({"x_um": float(stage["x_um"]), "y_um": float(stage["y_um"])})
        rig["markers"] = markers[-4:]
        mock_setup.write_rig(self._root(), rig)
        return {"markers": rig["markers"]}

    def clear_markers(self) -> dict:
        rig = mock_setup.read_rig(self._root())
        rig["markers"] = []
        mock_setup.write_rig(self._root(), rig)
        return {"markers": []}

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
    webview.create_window("Mock instrument", html=PAGE, js_api=Api(), width=520, height=640)
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
