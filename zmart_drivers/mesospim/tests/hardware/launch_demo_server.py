"""
Bring up a headless mesoSPIM ``-D`` demo with the Remote Scripting server started.
============================================================================
A bench/CI helper that boots the real **mesoSPIM-control** app (all Demo backends,
no hardware) offscreen and starts the Remote Scripting server (the upstream PR
under ``../../pull_request/``) with a token, so the ``-m integration`` suites
(``test_live_roundtrip`` + ``test_live_adapter``) can drive a real Core unattended.

This is the "server default-ON with a known token, for testing" hook: production
mesoSPIM stays OFF-by-default (the operator starts it from the Tools menu); this
script only exists on the test side and calls the server's start slot directly.

Requires a mesoSPIM-control checkout WITH the Remote Scripting PR applied
(``git am pull_request/0001-*.patch``). Configure via env vars:

    MESOSPIM_CONTROL_ROOT   path to that checkout (required)
    MESOSPIM_HOST           bind host   (default 127.0.0.1)
    MESOSPIM_PORT           bind port   (default 42000)
    MESOSPIM_TOKEN          shared token (default: a generated one, printed below)

Run it, wait for the ``LISTENING`` line, then run the integration suite in another
shell with the SAME MESOSPIM_HOST/PORT/TOKEN. Ctrl-C (or kill) to stop.

Author: Thom de Hoog (ZMB, University of Zurich). License: MIT (it drives, but
does not import, the GPL mesoSPIM-control).
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import sys
import types


def _fail(msg: str) -> "NoReturn":  # noqa: F821
    print(f"launch_demo_server: {msg}", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    root = os.environ.get("MESOSPIM_CONTROL_ROOT")
    if not root or not os.path.isdir(root):
        _fail("set MESOSPIM_CONTROL_ROOT to a mesoSPIM-control checkout with the "
              "Remote Scripting PR applied (git am pull_request/0001-*.patch)")
    host = os.environ.get("MESOSPIM_HOST", "127.0.0.1")
    port = int(os.environ.get("MESOSPIM_PORT", "42000"))
    token = os.environ.get("MESOSPIM_TOKEN") or secrets.token_urlsafe(16)

    pkg_dir = os.path.join(root, "mesoSPIM")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.makedirs(os.path.join(pkg_dir, "log"), exist_ok=True)
    os.chdir(pkg_dir)  # the app resolves gui/*.ui and ./config relative to here
    sys.path.insert(0, root)

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    from PyQt5 import QtCore, QtWidgets

    # Stub the USB webcam window (QtMultimedia + a real camera; irrelevant to control).
    stub = types.ModuleType("mesoSPIM.src.WebcamWindow")
    stub.WebcamWindow = type("WebcamWindow", (QtWidgets.QWidget,), {
        "__init__": lambda self, webcam_id=None: QtWidgets.QWidget.__init__(self)
    })
    sys.modules["mesoSPIM.src.WebcamWindow"] = stub

    spec = importlib.util.spec_from_file_location(
        "democfg", os.path.join(pkg_dir, "config", "demo_config.py")
    )
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    try:
        cfg.ui_options["usb_webcam_ID"] = None
    except Exception:  # noqa: BLE001 - older/newer configs may lack this key
        pass

    app = QtWidgets.QApplication(sys.argv)
    # PluginRegistry must exist before MainWindow (Acquisition resolves a writer at
    # class-definition time).
    from mesoSPIM.src.plugins.manager import PluginRegistry
    PluginRegistry(cfg)
    from mesoSPIM.src.mesoSPIM_MainWindow import mesoSPIM_MainWindow

    # Neutralise the startup modals (they QMessageBox on the GUI thread and would
    # segfault offscreen); each is a plain method we can no-op.
    mesoSPIM_MainWindow.open_webcam_window = lambda self, *a, **k: None
    mesoSPIM_MainWindow.choose_etl_config = lambda self, *a, **k: None
    mesoSPIM_MainWindow.display_warning = lambda self, s=None, *a, **k: None

    ex = mesoSPIM_MainWindow(pkg_dir, cfg, "mesoSPIM demo (headless)")
    ex.show()

    def on_started(ok, message):
        if ok:
            print(f"LISTENING {host}:{port} token={token}", flush=True)
        else:
            print(f"FAILED to start: {message}", file=sys.stderr, flush=True)
            app.quit()

    ex.core.sig_remote_scripting_started.connect(on_started)
    # Start the server via the real queued GUI signal path, exactly as the button.
    QtCore.QTimer.singleShot(
        1500, lambda: ex.sig_start_remote_scripting.emit(host, port, token)
    )
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
