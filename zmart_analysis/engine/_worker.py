"""
Worker -- Manages a subprocess for one conda environment.

Spawns worker_script.py in the target conda environment and communicates
via multiprocessing.connection (TCP sockets with pickle serialization).

Workers are per-environment, not per-step. A single worker can execute any
step file sent to it, with modules and state dicts cached inside the
subprocess for warm-start performance.

Lifecycle
---------
1. ensure_running(): Allocate random port, spawn subprocess, wait for
   it to connect back. Uses authkey for secure handshake.
2. execute(step_path, data, params): Send work, wait for response.
3. shutdown(): Send None sentinel, wait 5s for a graceful exit, then kill
   the process tree. shutdown(now=True) kills the tree at once: the
   operator's Interrupt reaching a step in flight.

Connection protocol
-------------------
- Parent creates Listener on localhost:0 (random port)
- Subprocess receives port + authkey via CLI args
- Subprocess connects back as Client
- Messages: (step_path, pipeline_data, params) via pickle
- Shutdown sentinel: None (pickled)
"""

import collections
import logging
import os
import pickle
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Listener
from pathlib import Path

from .conda_utils import CONDA_CMD
from ._errors import (
    WorkerSpawnError,
    WorkerCrashedError,
    WorkerTimeoutError,
    StepExecutionError,
)

logger = logging.getLogger(__name__)

ENGINE_DIR = Path(__file__).resolve().parent
WORKER_SCRIPT = ENGINE_DIR / "worker_script.py"

# Maximum bytes of stderr to retain for crash diagnostics.
_STDERR_BUFFER = 8192

#: One spawn at a time, for the whole process. `conda run` on Windows writes
#: its activation through a temp file whose name is NOT unique across
#: concurrent invocations from one parent -- two spawns racing corrupt each
#: other's activation ("The process cannot access the file because it is
#: being used by another process"), the worker never connects, and conda's
#: dying words name an environment that exists. Any submission fan-out that
#: needs more than one worker spawns several at once and lost all but the
#: first; one at a time costs a few serial seconds at warm-up, once, against
#: a run that died at its fan-out. Reproduced directly: four concurrent
#: ``conda run -n <env> python -c ...`` from one parent, three failed on the
#: same ``__conda_tmp_<n>.txt``.
_spawn_turn = threading.Lock()


def _the_python_of(environment):
    """How the interpreter of a step's conda environment is reached.

    `conda run` activates the environment and starts the interpreter as its
    own child, so the worker is a grandchild of the engine. A test stands a
    wrapper of its own here to prove the whole tree is put down.
    """
    return [CONDA_CMD, "run", "-n", environment, "python"]


class _StderrDrainer:
    """Background thread that reads stderr so the pipe never fills.

    Without draining, a worker that logs errors to stderr can fill the
    OS pipe buffer (~4KB on Windows) and block permanently. This thread
    reads continuously and keeps the last _STDERR_BUFFER bytes for crash
    diagnostics.
    """

    def __init__(self, stream):
        self._stream = stream
        self._buf = collections.deque(maxlen=_STDERR_BUFFER)
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self):
        try:
            while True:
                chunk = self._stream.read(1024)
                if not chunk:
                    break
                self._buf.extend(chunk)
        except (ValueError, OSError):
            pass

    def get_output(self):
        """Return retained stderr as a string."""
        return bytes(self._buf).decode("utf-8", errors="replace")

    def close(self):
        """Close the stream (unblocks the drain thread)."""
        try:
            self._stream.close()
        except Exception:
            pass


class Worker:
    """
    Manages a subprocess for one conda environment.

    Parameters
    ----------
    environment : str or None
        Conda environment name. None means the orchestrator's own
        environment (uses sys.executable directly).
    idle_timeout : float
        Seconds of inactivity before eligible for reaper shutdown.
    connect_timeout : float
        Seconds to wait for the subprocess to connect back.
    """

    def __init__(self, environment=None, idle_timeout=300.0,
                 connect_timeout=60.0):
        self.environment = environment
        self.idle_timeout = idle_timeout
        self.connect_timeout = connect_timeout

        self._process = None
        self._conn = None
        self._listener = None
        self._stderr_drainer = None
        self._last_active = time.monotonic()
        self._current_step = None
        #: Set by :meth:`shutdown` with ``now``. A worker put down stays
        #: down: a press that landed before the spawn was forgotten, and the
        #: whole tree came up afterwards and stayed.
        self._closed = False

    def ensure_running(self):
        """Spawn the subprocess if not already running."""
        if self._process is not None and self._process.poll() is None:
            return
        self._refuse_if_put_down()

        self._cleanup()

        authkey = os.urandom(32)
        self._listener = Listener(("localhost", 0), authkey=authkey)
        port = self._listener.address[1]
        self._listener._listener._socket.settimeout(self.connect_timeout)

        python = ([sys.executable] if self.environment is None
                  else _the_python_of(self.environment))
        cmd = python + [str(WORKER_SCRIPT)]

        # Pass the engine's own PID for orphan detection. The worker cannot
        # rely on os.getppid(): under `conda run` its direct parent is the
        # wrapper process, which outlives a crashed engine.
        cmd.extend(["--port", str(port), "--authkey", authkey.hex(),
                    "--parent-pid", str(os.getpid())])

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        # The worker is put down as a tree (see _kill_tree): under `conda run`
        # the process started here is a wrapper, and the interpreter doing
        # the work is its child. Windows kills by tree from the wrapper's
        # pid; POSIX needs the wrapper to lead a session of its own.
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        env_label = self.environment or "orchestrator"
        logger.debug("Worker spawning: env=%s, port=%d", env_label, port)

        # Spawn-to-connect under the one turn: the conda activation is what
        # races, and it runs in the child between Popen and the connect back,
        # so the turn is held until the worker is on the line.
        with _spawn_turn:
            try:
                self._process = subprocess.Popen(
                    cmd, env=env, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE, **kwargs,
                )
            except Exception as e:
                logger.error("Worker spawn failed for env=%s: %s", env_label, e)
                self._cleanup()
                raise WorkerSpawnError(
                    f"Failed to start worker for '{env_label}': {e}"
                ) from e

            logger.debug("Worker process started: pid=%d, env=%s",
                         self._process.pid, env_label)
            self._refuse_if_put_down()

            # Drain stderr in background so the pipe buffer never fills.
            # Without this, a worker logging errors to stderr can block
            # permanently after ~4KB of output (Windows pipe buffer size).
            self._stderr_drainer = _StderrDrainer(self._process.stderr)

            try:
                self._conn = self._listener.accept()
            except Exception as e:
                # A press that landed while the worker was on its way closes
                # the door it was to come through; that is the press, not a
                # worker that could not connect.
                self._refuse_if_put_down()
                stderr = self._stderr_drainer.get_output() if self._stderr_drainer else ""
                logger.error("Worker connect failed: pid=%d, env=%s, stderr=%s",
                             self._process.pid, env_label, stderr[:500])
                self._cleanup()
                raise WorkerSpawnError(
                    f"Worker for '{env_label}' failed to connect "
                    f"within {self.connect_timeout}s. stderr: {stderr}"
                ) from e

        self._refuse_if_put_down()
        self._last_active = time.monotonic()
        logger.info("Worker ready: pid=%d, env=%s",
                     self._process.pid, env_label)

    def _refuse_if_put_down(self):
        """A shutdown that landed at any point of the spawn wins.

        Checked before the spawn, right after it, and once the worker is on
        the line: whatever came up in between is put down again, and the
        caller is told the worker is gone rather than handed a job on a
        worker nobody wanted.
        """
        if not self._closed:
            return
        self._cleanup()
        env_label = self.environment or "orchestrator"
        raise WorkerCrashedError(f"Worker for '{env_label}' was put down")

    def execute(self, step_path, pipeline_data, params, timeout=300.0):
        """
        Send work to the worker and block until result.

        Parameters
        ----------
        step_path : str
            Path to the step .py file.
        pipeline_data : dict
            Data dict to pass to the step's run() function.
        params : dict
            Keyword arguments from the YAML config.
        timeout : float
            Seconds to wait for the step to complete.

        Raises
        ------
        StepExecutionError
            If the step's run() raised an exception.
        WorkerTimeoutError
            If the step exceeded `timeout` and the worker was killed.
        WorkerCrashedError
            If the worker process died during execution.
        """
        self.ensure_running()
        pid = self._process.pid
        step_name = Path(step_path).stem
        self._current_step = step_name
        t0 = time.monotonic()

        message = (str(step_path), pipeline_data, params)
        try:
            data = pickle.dumps(message, protocol=2)
            logger.debug("Worker execute: sending %d bytes to pid=%d "
                         "(step=%s)", len(data), pid, step_name)
            self._conn.send_bytes(data)
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.error("Worker send failed: pid=%d, step=%s: %s",
                         pid, step_name, e)
            self._cleanup()
            env_label = self.environment or "orchestrator"
            raise WorkerCrashedError(
                f"Worker for '{env_label}' lost connection: {e}"
            ) from e

        try:
            if not self._conn.poll(timeout=timeout):
                logger.error("Worker timed out: pid=%d, step=%s, "
                             "timeout=%.0fs", pid, step_name, timeout)
                self._cleanup()
                env_label = self.environment or "orchestrator"
                raise WorkerTimeoutError(
                    f"Worker for '{env_label}' timed out after {timeout}s"
                )
            raw = self._conn.recv_bytes()
        except (EOFError, ConnectionResetError, OSError) as e:
            stderr = (self._stderr_drainer.get_output()
                      if self._stderr_drainer else "")
            logger.error("Worker crashed: pid=%d, step=%s, stderr=%s",
                         pid, step_name, stderr[:500])
            self._cleanup()
            env_label = self.environment or "orchestrator"
            raise WorkerCrashedError(
                f"Worker for '{env_label}' crashed. stderr: {stderr}"
            ) from e

        elapsed = time.monotonic() - t0
        response = pickle.loads(raw)
        self._last_active = time.monotonic()
        self._current_step = None

        if not isinstance(response, tuple) or len(response) != 2:
            env_label = self.environment or "orchestrator"
            raise WorkerCrashedError(
                f"Worker for '{env_label}' sent invalid response"
            )

        status, payload = response
        if status == "error":
            logger.warning("Step error: pid=%d, step=%s, elapsed=%.2fs",
                           pid, step_name, elapsed)
            raise StepExecutionError(
                payload.get("message", "Unknown error"),
                remote_traceback=payload.get("traceback"),
            )
        if status != "ok":
            raise WorkerCrashedError(
                f"Worker sent unknown status: {status!r}"
            )

        logger.debug("Worker execute done: pid=%d, step=%s, elapsed=%.2fs",
                     pid, step_name, elapsed)
        return payload

    def is_idle(self, now=None):
        """True if worker has been idle longer than idle_timeout."""
        if now is None:
            now = time.monotonic()
        return (now - self._last_active) > self.idle_timeout

    def is_alive(self):
        """Check if the worker process is still running."""
        return self._process is not None and self._process.poll() is None

    @property
    def status(self):
        """Current worker state for observability."""
        if not self.is_alive():
            state = "stopped"
        elif self._current_step:
            state = "busy"
        else:
            state = "idle"
        env_label = self.environment or "orchestrator"
        return {
            "env": env_label,
            "state": state,
            "current_step": self._current_step,
            "pid": self._process.pid if self._process else None,
        }

    def shutdown(self, now=False):
        """Shut the worker subprocess down.

        Politely by default: the sentinel is sent, and an idle worker exits
        on it within a moment. With ``now`` the worker is put down at once,
        tree and all, without the sentinel or the wait -- this is the
        operator's Interrupt reaching a step in flight, and a step in flight
        never reads the sentinel, so waiting for it only delayed the kill by
        five seconds. A caller blocked in :meth:`execute` on that worker is
        released with :class:`WorkerCrashedError`, because the pipe breaks
        when the process does.
        """
        # Put down now means put down for good; a polite shutdown leaves the
        # object able to spawn again, as the protocol tests hold it to.
        self._closed = self._closed or now
        pid = self._process.pid if self._process else None
        if pid:
            env_label = self.environment or "orchestrator"
            logger.debug("Worker shutdown: pid=%d, env=%s, now=%s", pid, env_label, now)

        if self._conn is not None and not now:
            try:
                self._conn.send_bytes(pickle.dumps(None, protocol=2))
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        if self._process is not None:
            try:
                self._process.wait(timeout=0.0 if now else 5.0)
            except subprocess.TimeoutExpired:
                logger.warning("Worker put down: pid=%d", pid)
                self._kill_tree()

        self._cleanup()

    def _kill_tree(self):
        """Kill the worker process and everything under it.

        Under `conda run` the process this object holds is the wrapper, and
        the interpreter doing the work is its child: terminating the wrapper
        alone left that child segmenting on, and the operator's Interrupt
        stopped nothing (ten such orphans were found on one machine).
        """
        process = self._process
        if process is None or process.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            logger.error("Worker would not die: pid=%d", process.pid)

    def _cleanup(self):
        """Close connection, listener, drainer, and process handles."""
        self._current_step = None

        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

        if self._listener is not None:
            try:
                self._listener.close()
            except Exception:
                pass
            self._listener = None

        if self._stderr_drainer is not None:
            self._stderr_drainer.close()
            self._stderr_drainer = None

        if self._process is not None:
            self._kill_tree()
            self._process = None

    def __repr__(self):
        env_label = self.environment or "orchestrator"
        return f"Worker(env={env_label!r}, alive={self.is_alive()})"
