"""LAS X source-side file primitives.

This module stays deliberately small. Exporter-specific collection lives
in ``navigator_expert_export``; persistence and OME checks live in
``save`` / ``ome``.

Source naming (LAS X auto-export)::

    image--L0000--J08--E00--X00--Y00--T0000--Z00--C00.ome.tif
    metadata/image--L0000--J08--E00--T0000.ome.xml
"""

from __future__ import annotations

import logging
import re
import time

from .._file_utils import _wait_file_stable

log = logging.getLogger(__name__)


_RE_LASX_IMAGE = re.compile(
    r"^image"
    r"--L(?P<L>\d+)"
    r"--J(?P<J>\d+)"
    r"--E(?P<E>\d+)"
    r"--X(?P<X>\d+)"
    r"--Y(?P<Y>\d+)"
    r"--T(?P<T>\d+)"
    r"--Z(?P<Z>\d+)"
    r"--C(?P<C>\d+)"
    r"(?:--(?P<repeat>\d{3}))?"
    r"\.ome\.tif$"
)

_RE_LASX_XML = re.compile(
    r"^image"
    r"--L(?P<L>\d+)"
    r"--J(?P<J>\d+)"
    r"--E(?P<E>\d+)"
    r"--T(?P<T>\d+)"
    r"(?:--(?P<repeat>\d{3}))?"
    r"\.ome\.xml$"
)


def parse_lasx_filename(name):
    """Parse a LAS X export filename into integer segment values.

    Handles both image files and companion XML. Returns ``None`` for
    filenames outside the LAS X export convention. ``repeat`` is ``None``
    for the first acquisition in a reused export folder.
    """
    m = _RE_LASX_IMAGE.match(name)
    if m is None:
        m = _RE_LASX_XML.match(name)
    if m is None:
        return None
    d = m.groupdict()
    for k, v in d.items():
        if v is not None:
            d[k] = int(v)
    return d


def read_relative_path(client):
    """Read ``RelativePathName`` from the LAS X data model.

    Returns an empty string on failure or when LAS X has not published a
    path in the current session.
    """
    try:
        return str(client.PyApiImagePathItem.Model.RelativePathName)
    except Exception as e:
        log.warning("Could not read RelativePathName: %s", e)
        return ""


def wait_all_stable(files, *, timeout=60, poll_interval=0.5, stable_readings=3):
    """Block until every file in *files* is unlocked and size-stable."""
    t0 = time.perf_counter()
    unstable = []

    for f in files:
        remaining = timeout - (time.perf_counter() - t0)
        if remaining <= 0:
            unstable.append(f)
            continue
        if not _wait_file_stable(f, remaining, poll_interval, stable_readings):
            unstable.append(f)

    if unstable:
        elapsed = time.perf_counter() - t0
        log.warning(
            "%d/%d files not stable after %.1fs",
            len(unstable),
            len(files),
            elapsed,
        )
        return {
            "success": False,
            "error": f"{len(unstable)} file(s) not stable after {timeout}s",
            "unstable": [str(f) for f in unstable],
        }

    elapsed = time.perf_counter() - t0
    log.debug("All %d files stable in %.1fs", len(files), elapsed)
    return {"success": True, "stable_count": len(files), "elapsed_s": elapsed}
