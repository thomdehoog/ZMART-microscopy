"""
Injected-script templates -- the mesoSPIM command vocabulary (MIT).
===================================================================
The Remote Scripting bridge in mesoSPIM is deliberately generic: "run this
Python, return the console." All the *vocabulary* -- what "move to x" or "read
the state" means in terms of the live ``mesoSPIM_Core`` API -- lives here, on the
**MIT client side**, as small Python snippets the driver injects. mesoSPIM itself
learns no ZMART concepts; it just runs the snippet with ``self`` == Core.

Two shapes, both as minimal as they can be:

- **Writes** (move / set_state / zero / stop): one inlined Core call plus a bare
  ``print('__ZMART_OK__{}')`` ack -- three lines, no import, no result to build
  (the driver confirms by reading state back). Built by :func:`_write_line`.
- **Reads** (state / config / acquire / ...): a small body that assigns
  ``_result`` (a JSON dict), wrapped by :func:`mesospim.protocol.wrap_script` into
  ``import json`` + body + ``print('__ZMART_OK__' + json.dumps(_result))``. Args,
  when needed, are embedded as a literal ``_a = {...}``.

These snippets touch the real mesoSPIM Core surface (``self.move_absolute``,
``self.state['position']['x_pos']``, ``self.cfg.laserdict``,
``self.sig_state_request_and_wait_until_done``, ``self.start``), verified
against mesoSPIM-control v1.20.0. The acquisition entry point
(``self.start(row=0)`` + the image-writer's folder/filename path) is the one
**site-specific** hook to confirm on the bench (documented in ``TODO.md``).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from ..protocol import wrap_script

# Each entry is Python that reads its args from ``_a`` and sets ``_result``.
_TEMPLATES: dict[str, str] = {
    # -- handshake / health --------------------------------------------------
    "hello": """
_cfg = getattr(self, 'cfg', None)
_result = {'app': 'mesoSPIM-control', 'version': getattr(_cfg, 'version', None),
           'protocol': 1, 'state': (self.state or {}).get('state')}
""",
    "ping": """
_result = {'pong': True, 'state': (self.state or {}).get('state')}
""",
    # -- reads ---------------------------------------------------------------
    "get_state": """
_st = self.state or {}
_pos = _st.get('position', {}) or {}
_axis = lambda a: _pos.get(a, _pos.get(a + '_pos'))
_result = {
    'state': _st.get('state'),
    'position': {a: _axis(a) for a in ('x', 'y', 'z', 'f', 'theta')},
    'laser': _st.get('laser'),
    'intensity': _st.get('intensity'),
    'filter': _st.get('filter'),
    'zoom': _st.get('zoom'),
    'shutterconfig': _st.get('shutterconfig'),
    'etl_l_amplitude': _st.get('etl_l_amplitude'),
    'etl_l_offset': _st.get('etl_l_offset'),
    'etl_r_amplitude': _st.get('etl_r_amplitude'),
    'etl_r_offset': _st.get('etl_r_offset'),
}
""",
    "get_position": """
_pos = (self.state or {}).get('position', {}) or {}
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
_st = self.state or {}
_result = {'state': _st.get('state'),
           'current_plane': _st.get('current_framenumber'),
           'total_planes': _st.get('snap_count'),
           'current_acquisition': _st.get('current_acquisition'),
           'total_acquisitions': _st.get('total_acquisitions')}
""",
    # Movement and state settings are pure WRITES -- see ``_write_line`` below;
    # they inject one Core call + a bare ``__ZMART_OK__{}`` ack (no data to
    # return; the driver confirms by reading state back separately).
    # -- acquisition ---------------------------------------------------------
    # A capture is three scripts, so no script ever sleeps inside mesoSPIM's
    # event loop waiting for its own acquisition:
    #
    #   acquire_start   swap in a one-item acq_list and fire ``self.start(row=0)``
    #                   (the real Core entry point; the default Tiff writer makes
    #                   ONE multi-page stack at the Acquisition's folder/filename),
    #                   then return immediately.
    #   stat_files      cheap idempotent poll helper: which files exist, how big.
    #                   The client polls this + ``get_progress`` until the run is
    #                   idle and the stack exists (see ``acquisition.capture``).
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
_result = {'state': (self.state or {}).get('state')}
""",
    # -- named procedures ----------------------------------------------------
    # No generic server-side procedure exists. Fail (the harness turns this into
    # a NAK) so a caller cannot mistake "advertised" for "implemented". Real
    # procedures are injected as their own scripts per site (TODO §5).
    "procedure": """
raise RuntimeError('procedure ' + repr(_a.get('name')) + ' is not implemented server-side')
""",
}


# Pure writes: one Core call, no data returned. The args are computed here and
# inlined as a literal, so the injected script is just the call + a bare ack.
_WRITE_CMDS: tuple[str, ...] = ("move_absolute", "move_relative", "zero", "stop", "set_state")


def _write_line(cmd: str, args: dict) -> str:
    if cmd == "set_state":
        return f"self.sig_state_request_and_wait_until_done.emit({dict(args['settings'])!r})"
    if cmd == "move_absolute":
        sdict = {a + "_abs": float(v) for a, v in args["targets"].items()}
        return f"self.move_absolute({sdict!r}, wait_until_done=True)"
    if cmd == "move_relative":
        ddict = {a + "_rel": float(v) for a, v in args["deltas"].items()}
        return f"self.move_relative({ddict!r}, wait_until_done=True)"
    if cmd == "zero":
        return f"self.zero_axes({list(args.get('axes') or ['x', 'y', 'z', 'f', 'theta'])!r})"
    if cmd == "stop":
        return "self.sig_stop_movement.emit()"
    raise KeyError(cmd)


def known_commands() -> tuple[str, ...]:
    """Every command name that can be injected."""
    return tuple(_TEMPLATES) + _WRITE_CMDS


def build_script(cmd: str, args: dict) -> str:
    """Build the full injected script for ``cmd`` with ``args``.

    Writes inject one Core call + ``print('__ZMART_OK__{}')``; reads embed their
    args as a literal (``_a = {...}``) and print the JSON result. The leading
    ``# zmart-cmd`` comment is inert Python that lets a filter/log see which
    command a script implements without parsing it. Raises ``KeyError`` for an
    unknown command.
    """
    args = dict(args)
    if cmd in _WRITE_CMDS:
        return f"# zmart-cmd: {cmd}\n{_write_line(cmd, args)}\nprint('__ZMART_OK__{{}}')\n"
    if cmd not in _TEMPLATES:
        raise KeyError(f"no injected-script template for command {cmd!r}")
    prefix = f"_a = {args!r}\n" if args else ""  # only reads that take args need it
    body = prefix + _TEMPLATES[cmd].strip("\n")
    return f"# zmart-cmd: {cmd}\n" + wrap_script(body)
