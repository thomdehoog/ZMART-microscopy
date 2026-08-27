"""
Worker subprocess script -- runs inside the target conda environment.

Self-contained: imports nothing from the engine package. It may run in a
completely different conda environment with different packages and even a
different Python version than the orchestrator.

Protocol
--------
1. Parent spawns this script with --port, --authkey
2. Script connects to parent on localhost:port with authkey
3. Message loop:
   - Receive (step_path, pipeline_data, params)
   - Load module at step_path (cached)
   - Call module.run(pipeline_data, state, **params)
   - Send ("ok", result) or ("error", {"message": ..., "traceback": ...})
4. Receive None sentinel -> clean exit

State management
----------------
Each step gets its own persistent state dict, keyed by step path. The state
dict is passed to run() on every call. First call sees an empty dict. The
step populates it with whatever it needs (models, caches, etc.). State is
garbage collected when the worker shuts down.

Module caching
--------------
Modules are loaded on first use and cached by path. A persistent worker
executing the same step repeatedly pays the import cost only once. Different
steps in the same environment load fresh but share the process.

Orphan detection
----------------
Persistent workers periodically check if the engine process is alive.
If the engine dies, the worker exits cleanly rather than becoming an orphan.
The engine passes its own PID via --parent-pid: os.getppid() cannot be
used because conda-env workers are spawned through a `conda run` wrapper
process, so the worker's direct parent is the wrapper, not the engine.
The wrapper stays alive waiting on the worker even after the engine dies,
which would defeat the check.

Usage (called by Worker, not directly)
--------------------------------------
    python worker_script.py --port PORT --authkey HEX --parent-pid PID
"""

import argparse
import logging
import os
import pickle
import sys
import traceback
import types
from multiprocessing.connection import Client


def _load_module(step_path):
    """Load a step module via exec. Mirrors _loader pattern."""
    name = os.path.splitext(os.path.basename(step_path))[0]
    namespace = {"__name__": name, "__file__": step_path}
    with open(step_path) as f:
        exec(compile(f.read(), step_path, "exec"), namespace)
    module = types.ModuleType(name)
    module.__dict__.update(namespace)
    return module


def _parent_alive(parent_pid):
    """Check if the parent process is still running.

    On Unix, os.kill(pid, 0) tests existence without sending a signal.
    On Windows, signal 0 maps to CTRL_C_EVENT which would interrupt the
    parent, so we use kernel32.OpenProcess instead.
    """
    if sys.platform == "win32":
        return _windows_process_alive(parent_pid)
    try:
        os.kill(parent_pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _windows_process_alive(parent_pid, kernel32=None):
    """Return whether a Windows process exists and has not terminated.

    ``OpenProcess`` can succeed for a terminated process while another handle
    still keeps its kernel object alive. Query the process handle's signaled
    state as well: process handles become signaled when the process exits.
    ``kernel32`` is injectable so this behavior is testable on every CI OS.
    """
    if kernel32 is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
        )
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    handle = kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        kernel32.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description="Pipeline engine worker")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--authkey", required=True)
    parser.add_argument("--parent-pid", type=int, default=None,
                        help="Engine PID to watch; defaults to os.getppid()")
    args = parser.parse_args()

    log_level = os.environ.get("SMART_LOG_LEVEL", "WARNING")
    logging.basicConfig(
        level=getattr(logging, log_level, logging.WARNING),
        format="[worker %(process)d] %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("engine.worker")

    parent_pid = (args.parent_pid if args.parent_pid is not None
                  else os.getppid())
    logger.info("Worker starting: pid=%d, port=%d, parent=%d",
                os.getpid(), args.port, parent_pid)

    conn = Client(("localhost", args.port),
                  authkey=bytes.fromhex(args.authkey))
    logger.info("Connected to parent on port %d", args.port)

    module_cache = {}
    state_dicts = {}
    request_count = 0

    try:
        while True:
            if not _parent_alive(parent_pid):
                logger.warning("Parent %d died, shutting down", parent_pid)
                break

            if not conn.poll(timeout=5.0):
                continue

            raw = conn.recv_bytes()
            message = pickle.loads(raw)

            if message is None:
                logger.info("Received shutdown sentinel")
                break

            step_path, pipeline_data, params = message
            step_name = os.path.basename(step_path)
            request_count += 1
            logger.info("Request #%d: step=%s (%d bytes)",
                        request_count, step_name, len(raw))

            # Load or reuse cached module
            if step_path not in module_cache:
                logger.info("Loading module: %s", step_name)
                module_cache[step_path] = _load_module(step_path)
            module = module_cache[step_path]

            # Get or create per-step state dict
            if step_path not in state_dicts:
                state_dicts[step_path] = {}
            state = state_dicts[step_path]

            try:
                result = module.run(pipeline_data, state, **params)
                response = ("ok", result)
                logger.info("Request #%d completed", request_count)
            except Exception:
                tb = traceback.format_exc()
                logger.error("Request #%d failed:\n%s", request_count, tb)
                response = ("error", {
                    "message": traceback.format_exception_only(
                        *sys.exc_info()[:2])[0].strip(),
                    "traceback": tb,
                })

            conn.send_bytes(pickle.dumps(response, protocol=2))
    finally:
        conn.close()
        logger.info("Worker exiting: pid=%d, requests=%d",
                    os.getpid(), request_count)


if __name__ == "__main__":
    main()
