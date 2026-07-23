# ZMART Viz Studio

A visualization tool for large, three-dimensional, multi-channel microscopy
images — the kind the Stellaris and mesoSPIM produce — that runs as its own
desktop window and is built entirely from web technology, so **you** own how it
looks and behaves.

Under the hood it uses [neuroglancer](https://github.com/google/neuroglancer)
as the image engine (it streams only the pieces of a huge volume you are
looking at, so even very large data feels light, and it does true 3-D), wrapped
in a [React](https://react.dev) interface that is entirely ours to shape. The
analysis and the microscope control stay in Python; this tool is the *view* and
the *controls*, talking to Python over a small local connection.

> **Status: early spike.** The engine, the app shell, and the OME-Zarr data
> path are working; the last step — actually painting the image pixels — still
> needs validating on a real Windows machine with a graphics card. See
> `SPIKE_RESULTS.md` for the honest, detailed state, and `PLAN.md` for the
> design and the decisions behind it.

## Try the demo (no microscope needed)

The demo makes a small pretend 3-D, three-colour volume so you can try
everything with no hardware.

```bash
# 1. Set up the environment (Python + the build tools)
conda env create -f environment.yml
conda activate zmart-viz

# 2. Build the viewer page (once)
npm --prefix frontend install
npm --prefix frontend run build

# 3. Launch it
python run_demo.py
```

A native window opens on the demo volume. On Windows it uses the built-in
WebView2 engine (Chromium), so the 3-D rendering runs on your graphics card. If
a native window cannot open, the address is printed so you can open it in a
browser instead.

## What is here

| Path | What it is |
|---|---|
| `frontend/` | The React + neuroglancer app (built into `frontend/dist`). |
| `backend/demo_data.py` | Makes the demo OME-Zarr volume. |
| `backend/server.py` | The small local web server (built page + image data + a JSON command endpoint). |
| `backend/launcher.py` | Opens the studio in a native desktop window (pywebview). |
| `backend/browsercheck.py` | Automated rendering check in a real headless browser. |
| `run_demo.py` | One command: make the demo volume and open the window. |
| `PLAN.md` | The design and the reasoning behind every choice. |
| `SPIKE_RESULTS.md` | What the spike proved, and the one open question. |

## How the pieces talk

```
  Python (analysis, microscope control, writes OME-Zarr)
      │  serves image chunks over HTTP  +  small JSON commands
      ▼
  backend/server.py  ──►  one local address (http://127.0.0.1:8848)
      ▲
      │  reads image chunks, sends commands
  frontend (React UI + neuroglancer engine)  ──►  shown in a native window
```

Python stays the brain and the hands; the window is the eyes and the controls.
The image data travels as OME-Zarr files (only the visible pieces are fetched);
commands and results travel as small messages.
