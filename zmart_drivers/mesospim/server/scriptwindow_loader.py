"""
mesoSPIM Script-Window loader for the ZMART command server (GPL edge).
=====================================================================
Open THIS file in mesoSPIM-control (Core menu -> Script Window -> open -> Run).
It starts the resident command server the ZMART driver connects to; you should
then see ``[mesospim-cmd-server] listening on 127.0.0.1:42000``.

Why a separate loader, and not ``mesospim_command_server.py`` directly?
mesoSPIM runs a loaded script with ``exec(script)`` inside
``mesoSPIM_Core.execute_script`` -- a method, so ``globals()`` (the mesoSPIM
module) and ``locals()`` (the method frame, which holds ``self``) are different
dicts. A *module*-shaped script (the command server, with module-level constants
and classes that reference each other) fails there: its top-level names land in
locals but are resolved as globals, raising ``NameError``. This loader is
deliberately FLAT -- only top-level statements, using ``self`` directly, exactly
like mesoSPIM's own example scripts in ``mesoSPIM/scripts/`` -- so it survives
that scope. It merely imports the real server module and calls ``start(self)``;
no server logic changes.

If the ZMART driver is not already importable in the mesoSPIM Python environment
(e.g. not pip-installed), set ``SERVER_DIR`` to the folder that contains
``mesospim_command_server.py`` on the acquisition PC.

License: GPL-3.0 (it loads the GPL server, which uses mesoSPIM's Core API).
Author: Thom de Hoog (ZMB, University of Zurich).
"""
import sys

# Folder holding ``mesospim_command_server.py``. Leave "" if the ZMART driver is
# already on ``sys.path`` in the mesoSPIM environment (e.g. pip-installed).
SERVER_DIR = r""

# Where the server listens. "127.0.0.1" = same PC only. Use "0.0.0.0" (or the
# mesoSPIM PC's LAN IP) to allow control from another machine on the network.
HOST = "127.0.0.1"
PORT = 42000
# Shared token gating access. Leave "" for an open server (localhost use only!).
# Set a value whenever HOST is on the network, so a random machine on the LAN
# can't drive the scope. The driver must pass the same token:
#     drv.connect({..., "token": "..."})
TOKEN = ""

if "self" not in dir():
    raise RuntimeError(
        "Run this from mesoSPIM's Script Window (Core menu): it needs the live "
        "mesoSPIM_Core bound as `self`."
    )

if SERVER_DIR and SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import mesospim_command_server as _zmart_server  # noqa: E402

_zmart_server.start(self, HOST, PORT, TOKEN or None)  # noqa: F821 - `self` is the live mesoSPIM_Core
print("[mesospim] ZMART command server started via the Script-Window loader")
