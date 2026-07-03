"""
Injected-script templates -- the mesoSPIM command vocabulary (MIT).
===================================================================
The Remote Scripting bridge in mesoSPIM is deliberately generic: "run this
Python, return the console." All the *vocabulary* -- what "move to x" or "read
the state" means in terms of the live ``mesoSPIM_Core`` API -- lives here, on the
**MIT client side**, as small Python snippets the driver injects. mesoSPIM itself
learns no ZMART concepts; it just runs the snippet with ``self`` == Core.

Each template is Python that runs in the Core context and assigns its result to a
name ``_result`` (a JSON-serialisable dict). :func:`build_script` embeds the
call's arguments as a Python literal ``_a``, prepends a small ``_sget`` prelude
(a singleton-safe state reader -- see below), then wraps the body in the
emit/try-except harness (:func:`mesospim.protocol.wrap_script`) so the result
comes back as a nonce-delimited base64(JSON) block.

Two mesoSPIM realities the snippets must respect (both verified against
mesoSPIM-control v1.20.0, and both invisible to a naive dict-based mock):

* ``self.state`` is a ``mesoSPIM_StateSingleton``, **not** a ``dict``. It supports
  ``self.state[key]`` (raising ``KeyError`` on a missing key) but has **no**
  ``.get``, ``.keys`` or iteration. So state is read through ``_sget(key, default)``
  which wraps the mutexed item access. (``position`` itself is a plain dict, so
  ``.get`` on *it* is fine.)
* mesoSPIM runs the script via ``exec(script)`` inside a *method*, so nested
  scopes need the single-namespace exec that :func:`wrap_script` provides.

These snippets touch the real Core surface (``self.move_absolute``,
``self.state['position']['x_pos']``, ``self.cfg.laserdict``,
``self.sig_state_request_and_wait_until_done``, ``self.start``), verified against
mesoSPIM-control v1.20.0. The acquisition entry point (``self.start(row=0)`` + the
image-writer's folder/filename path) is the one **site-specific** hook to confirm
on the bench (documented in ``TODO.md``).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from ..protocol import wrap_script

# Prepended to every body: a singleton-safe state reader. ``self.state`` is a
# mesoSPIM_StateSingleton (item access + KeyError, no ``.get``), so this is how a
# snippet reads an optional state key without assuming a dict.
_PRELUDE = (
    "def _sget(_k, _d=None):\n"
    "    try:\n"
    "        return self.state[_k]\n"
    "    except (KeyError, TypeError):\n"
    "        return _d\n"
)

# Each entry is Python that reads its args from ``_a`` and sets ``_result``.
_TEMPLATES: dict[str, str] = {
    # -- handshake / health --------------------------------------------------
    "hello": """
_cfg = getattr(self, 'cfg', None)
_result = {'app': 'mesoSPIM-control', 'version': getattr(_cfg, 'version', None),
           'protocol': 1, 'state': _sget('state')}
""",
    "ping": """
_result = {'pong': True, 'state': _sget('state')}
""",
    # -- reads ---------------------------------------------------------------
    "get_state": """
_pos = _sget('position', {}) or {}
_axis = lambda a: _pos.get(a, _pos.get(a + '_pos'))
_result = {
    'state': _sget('state'),
    'position': {a: _axis(a) for a in ('x', 'y', 'z', 'f', 'theta')},
    'laser': _sget('laser'),
    'intensity': _sget('intensity'),
    'filter': _sget('filter'),
    'zoom': _sget('zoom'),
    'shutterconfig': _sget('shutterconfig'),
    'etl_l_amplitude': _sget('etl_l_amplitude'),
    'etl_l_offset': _sget('etl_l_offset'),
    'etl_r_amplitude': _sget('etl_r_amplitude'),
    'etl_r_offset': _sget('etl_r_offset'),
}
""",
    "get_position": """
_pos = _sget('position', {}) or {}
_result = {a: _pos.get(a, _pos.get(a + '_pos')) for a in ('x', 'y', 'z', 'f', 'theta')}
""",
    "get_config": """
_cfg = getattr(self, 'cfg', None)
_get = lambda n: (getattr(_cfg, n, None) or {})
_ld = _get('laserdict') or _get('laser_designation')
_lasers = []
for _n in _ld:
    _dig = ''.join(_c for _c in str(_n) if _c.isdigit())
    _lasers.append({'name': _n, 'wavelength_nm': int(_dig) if _dig else None})
_zd = _get('zoomdict') or _get('zoom')
_zooms = []
for _z in _zd:
    _v = _zd[_z] if isinstance(_zd, dict) else None
    _zooms.append({'name': _z, 'pixel_size_um': _v if isinstance(_v, (int, float)) else None})
_fd = _get('filterdict')
_filters = list(_fd.keys()) if isinstance(_fd, dict) else list(_fd)
_result = {
    'app': 'mesoSPIM-control',
    'version': getattr(_cfg, 'version', None),
    'lasers': _lasers,
    'filters': _filters,
    'zooms': _zooms,
    'shutter_configs': list(getattr(_cfg, 'shutteroptions', ['Left', 'Right', 'Both'])),
    'axes': ['x', 'y', 'z', 'f', 'theta'],
    'camera': {'pixels_x': int(getattr(_cfg, 'camera_x_pixels', 2048) or 2048),
               'pixels_y': int(getattr(_cfg, 'camera_y_pixels', 2048) or 2048)},
}
""",
    "get_progress": """
_result = {'state': _sget('state'),
           'current_plane': _sget('current_framenumber'),
           'total_planes': _sget('snap_count'),
           'current_acquisition': _sget('current_acquisition'),
           'total_acquisitions': _sget('total_acquisitions')}
""",
    # -- movement ------------------------------------------------------------
    "move_absolute": """
_sdict = {a + '_abs': float(v) for a, v in _a['targets'].items()}
self.move_absolute(_sdict, wait_until_done=True)
_pos = _sget('position', {}) or {}
_result = {'position': {a: _pos.get(a, _pos.get(a + '_pos')) for a in ('x', 'y', 'z', 'f', 'theta')}}
""",
    "move_relative": """
_ddict = {a + '_rel': float(v) for a, v in _a['deltas'].items()}
self.move_relative(_ddict, wait_until_done=True)
_pos = _sget('position', {}) or {}
_result = {'position': {a: _pos.get(a, _pos.get(a + '_pos')) for a in ('x', 'y', 'z', 'f', 'theta')}}
""",
    "zero": """
self.zero_axes(list(_a.get('axes') or ['x', 'y', 'z', 'f', 'theta']))
_result = {}
""",
    "stop": """
self.sig_stop_movement.emit()
_result = {}
""",
    # -- state settings ------------------------------------------------------
    "set_state": """
_settings = dict(_a['settings'])
self.sig_state_request_and_wait_until_done.emit(_settings)
_result = {'applied': _settings}
""",
    # -- acquisition ---------------------------------------------------------
    # A capture is three scripts, so no script ever sleeps inside mesoSPIM's
    # event loop waiting for its own acquisition:
    #
    #   acquire_start   swap in a one-item acq_list and fire ``self.start(row=0)``
    #                   (the real Core entry point; the default Tiff writer makes
    #                   ONE multi-page stack at the Acquisition's folder/filename),
    #                   then return immediately.
    #   stat_files      cheap idempotent poll helper: which files exist, how big.
    #                   The client polls this until the stack exists and its size
    #                   stops growing (see ``acquisition.capture``). NOTE: it does
    #                   NOT poll state=='idle' -- reading state through the bridge
    #                   always sees 'running_script' (mesoSPIM_Core.execute_script
    #                   sets it around every exec), so file growth is the honest
    #                   completion signal.
    #   acquire_finish  restore the operator's acq_list and report the outcome.
    #
    # The operator's acq_list is stashed on the Core OBJECT between the start and
    # finish scripts (attributes persist across injected scripts; script locals
    # do not).
    #
    # BENCH ITEM (TODO.md): confirm ``start(row=...)`` is the right entry point on
    # your version and that the writer's path is folder/filename.
    "acquire_start": """
_acq = dict(_a['acquisition'])
try:
    from mesoSPIM.src.utils.acquisitions import Acquisition, AcquisitionList
except ImportError:
    from utils.acquisitions import Acquisition, AcquisitionList
import os as _os
_obj = Acquisition()
_obj.update({k: v for k, v in _acq.items() if v is not None})
_st = self.state
try:
    self._zmart_prev_acq_list = (True, _st['acq_list'])
except (KeyError, TypeError):
    self._zmart_prev_acq_list = (False, None)
_st['acq_list'] = AcquisitionList([_obj])
self.start(row=0)
_folder = _acq.get('folder') or ''
_fname = _acq.get('filename') or ''
_cfg = getattr(self, 'cfg', None)
_result = {'started': True,
           'files': [_os.path.join(_folder, _fname)] if _fname else [],
           'planes': int(_acq.get('planes', 1) or 1),
           'pixels': [int(getattr(_cfg, 'camera_x_pixels', 2048) or 2048),
                      int(getattr(_cfg, 'camera_y_pixels', 2048) or 2048)]}
""",
    "stat_files": """
import os as _os
_files = [str(_f) for _f in (_a.get('files') or [])]
_result = {'missing': [_f for _f in _files if not _os.path.isfile(_f)],
           'sizes': {_f: _os.path.getsize(_f) for _f in _files if _os.path.isfile(_f)}}
""",
    "acquire_finish": """
_st = self.state
_had, _prev = getattr(self, '_zmart_prev_acq_list', (False, None))
if _had:
    _st['acq_list'] = _prev
else:
    try:
        del _st['acq_list']
    except Exception:
        _st['acq_list'] = _prev
try:
    del self._zmart_prev_acq_list
except AttributeError:
    pass
_result = {'state': _sget('state')}
""",
    # -- named procedures ----------------------------------------------------
    # No generic server-side procedure exists. Fail (the harness turns this into
    # a NAK) so a caller cannot mistake "advertised" for "implemented". Real
    # procedures are injected as their own scripts per site (TODO §5).
    "procedure": """
raise RuntimeError('procedure ' + repr(_a.get('name')) + ' is not implemented server-side')
""",
}


def known_commands() -> tuple[str, ...]:
    """The command names for which an injected-script template exists."""
    return tuple(_TEMPLATES)


def build_script(cmd: str, args: dict, nonce: str) -> str:
    """Build the full injected script for ``cmd`` with ``args`` and ``nonce``.

    Raises ``KeyError`` for an unknown command. Arguments are embedded as a Python
    literal (``_a``) rather than parsed from JSON in-script, so the body needs no
    imports of its own. The leading ``# zmart-cmd`` comment is inert Python that
    lets a server log (or a test double) see which command a script implements
    without parsing it.
    """
    if cmd not in _TEMPLATES:
        raise KeyError(f"no injected-script template for command {cmd!r}")
    body = f"_a = {args!r}\n" + _PRELUDE + _TEMPLATES[cmd].strip("\n")
    return f"# zmart-cmd: {cmd}\n" + wrap_script(body, nonce)
