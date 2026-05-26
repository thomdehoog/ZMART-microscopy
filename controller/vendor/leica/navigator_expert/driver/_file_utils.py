"""Shared file-stability helpers.

Used by both template operations (scanning_templates) and acquisition
output handling (file_confirmation). Extracted here to break the
cross-dependency between those two modules.

Dependency direction:
    - Imports: stdlib only (pathlib, time).
    - Imported by: scanning_templates, file_confirmation.
"""

import time
from pathlib import Path


def _is_file_locked(path):
    """Return True if *path* is locked by another process (Windows).

    Opens the file in read+write mode; a ``PermissionError`` means
    another process (typically LAS X) holds an exclusive lock.
    """
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _wait_file_stable(path, timeout, poll_interval=0.5, stable_readings=3):
    """Block until *path* has stable size and is unlocked.

    Requires *stable_readings* consecutive checks where the file
    exists, has non-zero size, the size hasn't changed, and the file
    is not locked.

    Returns True if stable, False on timeout.
    """
    path = Path(path)
    t0 = time.perf_counter()
    consecutive = 0
    last_size = -1

    while (time.perf_counter() - t0) < timeout:
        try:
            if not path.is_file():
                consecutive = 0
                time.sleep(poll_interval)
                continue

            size = path.stat().st_size
            locked = _is_file_locked(path)

            if size == last_size and size > 0 and not locked:
                consecutive += 1
                if consecutive >= stable_readings:
                    return True
            else:
                consecutive = 0

            last_size = size
        except OSError:
            consecutive = 0

        time.sleep(poll_interval)

    return False
