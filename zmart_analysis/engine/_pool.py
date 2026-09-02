"""
WorkerPool -- Per-environment worker pools with dynamic scaling.

Manages worker subprocesses organized by conda environment. Workers are
created on demand and scale up to the per-step max_workers limit. Idle
workers are reaped after a configurable timeout.

Architecture
------------
Each environment gets an _EnvPool that tracks idle and busy workers.
The WorkerPool routes execute() calls to the right _EnvPool and enforces
per-step concurrency via semaphores.

Per-step concurrency
--------------------
max_workers is a per-step limit, not per-environment. A semaphore per
step path ensures no more than max_workers instances of the same step
run concurrently, even across different pipelines.

Thread safety
-------------
- _pool_lock protects _env_pools dict during creation.
- _sem_lock protects _step_semaphores dict during creation.
- Each _EnvPool has its own lock for idle/busy tracking.
- Reaper thread runs every 30s to shut down idle workers.
"""

import logging
import threading

from ._worker import Worker

logger = logging.getLogger(__name__)


class _EnvPool:
    """Worker pool for one conda environment.

    Tracks idle and busy workers. Creates new workers on demand.
    The pool grows as needed and shrinks via idle timeout reaping.
    """

    def __init__(self, environment, idle_timeout, connect_timeout):
        self.environment = environment
        self.idle_timeout = idle_timeout
        self.connect_timeout = connect_timeout
        self._idle = []
        self._busy = []
        self._lock = threading.Lock()
        self._closed = False

    def acquire(self):
        """Get an idle worker or create a new one. Marks it busy."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Worker pool has been shut down")
            # Try to reuse an idle worker
            while self._idle:
                worker = self._idle.pop()
                if worker.is_alive():
                    self._busy.append(worker)
                    return worker
                # Dead worker, discard silently
                worker.shutdown()

            # No idle worker available, create a new one
            worker = Worker(
                environment=self.environment,
                idle_timeout=self.idle_timeout,
                connect_timeout=self.connect_timeout,
            )
            self._busy.append(worker)
            return worker

    def release(self, worker):
        """Return a worker to the idle pool."""
        with self._lock:
            try:
                self._busy.remove(worker)
            except ValueError:
                pass
            if worker.is_alive() and not self._closed:
                self._idle.append(worker)

    def reap_idle(self):
        """Shut down workers that have been idle too long."""
        to_shutdown = []
        with self._lock:
            active = []
            for worker in self._idle:
                if worker.is_idle():
                    to_shutdown.append(worker)
                else:
                    active.append(worker)
            self._idle = active

        for worker in to_shutdown:
            worker.shutdown()

        if to_shutdown:
            env_label = self.environment or "orchestrator"
            logger.info("EnvPool(%s): reaped %d idle worker(s)",
                        env_label, len(to_shutdown))

    def shutdown_all(self, now=False):
        """Shut down all workers in this pool; with ``now``, at once."""
        with self._lock:
            self._closed = True
            all_workers = self._idle + self._busy
            self._idle.clear()
            self._busy.clear()

        for worker in all_workers:
            worker.shutdown(now=now)

    @property
    def status(self):
        """Current pool state."""
        workers = []
        with self._lock:
            for worker in self._busy + self._idle:
                if worker.is_alive():
                    workers.append(worker.status)
        return workers


class WorkerPool:
    """
    Pool of per-environment worker pools with per-step concurrency.

    Parameters
    ----------
    idle_timeout : float
        Seconds before idle workers are shut down (default: 300).
    connect_timeout : float
        Seconds to wait for a new worker to connect (default: 60).
    """

    def __init__(self, idle_timeout=300.0, connect_timeout=60.0):
        self.idle_timeout = idle_timeout
        self.connect_timeout = connect_timeout

        self._env_pools = {}
        self._pool_lock = threading.Lock()

        self._step_semaphores = {}
        self._sem_lock = threading.Lock()

        self._shutdown_event = threading.Event()
        self._reaper = None
        self._closed = False

    def execute(self, environment, step_path, pipeline_data, params,
                max_workers=1, timeout=300.0):
        """
        Execute a step in a worker subprocess.

        Blocks until a worker is available (respecting per-step concurrency)
        and the step completes.

        Parameters
        ----------
        environment : str or None
            Conda environment. None = orchestrator's environment.
        step_path : str
            Path to the step .py file.
        pipeline_data : dict
            Data to pass to the step.
        params : dict
            Step parameters from YAML.
        max_workers : int
            Maximum concurrent instances of this step.
        timeout : float
            Seconds to wait for step completion.
        """
        sem = self._get_semaphore(step_path, max_workers)
        sem.acquire()
        try:
            pool = self._get_env_pool(environment)
            worker = pool.acquire()
            try:
                return worker.execute(step_path, pipeline_data, params,
                                      timeout=timeout)
            finally:
                pool.release(worker)
        finally:
            sem.release()

    def _get_env_pool(self, environment):
        """Get or create the pool for an environment."""
        with self._pool_lock:
            if self._closed:
                raise RuntimeError("WorkerPool has been shut down")
            if environment not in self._env_pools:
                env_label = environment or "orchestrator"
                logger.info("Pool: creating env pool for %s", env_label)
                self._env_pools[environment] = _EnvPool(
                    environment, self.idle_timeout, self.connect_timeout,
                )
                self._ensure_reaper()
            return self._env_pools[environment]

    def _get_semaphore(self, step_path, max_workers):
        """Get or create a concurrency semaphore for a step."""
        with self._sem_lock:
            if step_path not in self._step_semaphores:
                self._step_semaphores[step_path] = threading.Semaphore(
                    max_workers)
            return self._step_semaphores[step_path]

    # -- Reaper --------------------------------------------------------

    def _ensure_reaper(self):
        """Start the reaper thread on first pool creation."""
        if self._reaper is None:
            logger.debug("Pool: starting reaper (idle_timeout=%.0fs)",
                         self.idle_timeout)
            self._reaper = threading.Thread(
                target=self._reaper_loop, daemon=True,
            )
            self._reaper.start()

    def _reaper_loop(self):
        """Background thread: reap idle workers every 30s."""
        while not self._shutdown_event.wait(timeout=30.0):
            with self._pool_lock:
                pools = list(self._env_pools.values())
            for pool in pools:
                pool.reap_idle()

    # -- Status & shutdown ---------------------------------------------

    @property
    def status(self):
        """Current pool state for observability."""
        workers = []
        with self._pool_lock:
            for pool in self._env_pools.values():
                workers.extend(pool.status)
        return {"workers": workers}

    def shutdown_all(self, now=False):
        """Shut down all workers and stop background threads.

        With ``now`` every worker is put down at once, busy or not: the
        operator's Interrupt, which must reach a step in flight.
        """
        self._shutdown_event.set()

        with self._pool_lock:
            self._closed = True
            pools = list(self._env_pools.values())
            n = len(pools)

        if n:
            logger.info("Pool: shutting down %d env pool(s) (now=%s)", n, now)
        for pool in pools:
            pool.shutdown_all(now=now)

        logger.debug("Pool: shutdown complete")

    def __repr__(self):
        with self._pool_lock:
            n_envs = len(self._env_pools)
        return f"WorkerPool(envs={n_envs})"
