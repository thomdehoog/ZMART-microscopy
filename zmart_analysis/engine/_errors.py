"""
Exception hierarchy for the pipeline engine.

    WorkerError (base for all subprocess issues)
    +-- WorkerSpawnError      subprocess failed to start or connect
    +-- WorkerCrashedError    subprocess died during execution
    +-- WorkerTimeoutError    step exceeded its execution timeout and the
                              worker was killed by the engine
    +-- StepExecutionError    step's run() raised an exception
                              (includes .remote_traceback from subprocess)

    ScopeError                invalid scope configuration or completion

All step execution goes through worker subprocesses. StepExecutionError
covers step failures raised by user code. WorkerSpawnError,
WorkerCrashedError, and WorkerTimeoutError cover infrastructure issues
with the subprocess itself.
"""


class WorkerError(Exception):
    """Base exception for all worker subprocess errors."""


class WorkerSpawnError(WorkerError):
    """Worker subprocess failed to start or connect back."""


class WorkerCrashedError(WorkerError):
    """Worker process died unexpectedly during execution."""


class WorkerTimeoutError(WorkerError):
    """Step exceeded its execution timeout; the worker was killed."""


class StepExecutionError(WorkerError):
    """Step's run() raised an exception inside the worker subprocess."""

    def __init__(self, message, remote_traceback=None):
        super().__init__(message)
        self.remote_traceback = remote_traceback


class ScopeError(Exception):
    """Invalid scope configuration, missing results, or bad completion signal."""
