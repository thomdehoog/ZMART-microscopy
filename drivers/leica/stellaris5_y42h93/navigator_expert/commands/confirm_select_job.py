"""select_job confirmation source-policy engine (api / log / hybrid).

The self-contained subsystem that decides, builds, and runs the
confirmation evidence for the ``select_job`` command: the api poll leg,
the log ``CurrentBlock`` leg, their hybrid admissibility gate, and the
pre-fire no-op / api-baseline preparation. The trivial per-setting
readback confirmations stay in ``confirmations``; the dual-leg
``race_confirmations`` arbiter also lives there.

Import restrictions: only ``readers``, runtime utilities/profiles, the
shared ``confirmations._reading_value_after`` helper, and stdlib.
Nothing from command wrappers.
"""

import logging
import queue
import time
from functools import partial

from .. import readers as _readers
from ..readers import log_wait
from ..readers import router as _router
from ..utils import CONFIRM_TIMEOUT, _make_log_entry
from .confirmations import _reading_value_after

log = logging.getLogger(__name__)


def _state_reader_profile():
    """Return the current state-reader profile without importing at module load."""
    from ..config import profiles

    return profiles.STATE_READERS


def confirm_select_job(
    client,
    *,
    job_name,
    timeout=None,
    poll_interval=0.01,
    command_started_at=None,
    inadmissible_baseline=None,
    require_transition_witness=False,
):
    """API confirmation leg: poll until *job_name* is selected, or timeout.

    Args:
        client: The connected LAS X API client.
        job_name: Name of the job expected to become selected.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between get_jobs polls.
        command_started_at: Wall-clock timestamp captured before the select
            command was fired.
        inadmissible_baseline: The API's pre-command selected-job name, set
            by the hybrid race. The API readback can be persistently stale
            on this LAS X version, so when it already read the target BEFORE
            the command it cannot witness a transition - the leg is
            inadmissible and only log evidence may confirm (the A->B->A
            restore case). ``None`` (pure api mode) keeps today's exact
            semantics: the poll is the only evidence.
        require_transition_witness: Hybrid-only guard. When true, the API leg
            must have a valid non-target pre-command baseline before it may
            poll for the target.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    if require_transition_witness and inadmissible_baseline is None:
        msg = (
            f"SelectJob '{job_name}' | api leg inadmissible: no valid "
            "pre-command API baseline (no transition witness)"
        )
        log.info(msg)
        logs.append(_make_log_entry("info", msg))
        return {
            "success": False,
            "logs": logs,
            "source": "api",
            "reason": "inadmissible_no_baseline",
        }
    if require_transition_witness and inadmissible_baseline == job_name:
        msg = (
            f"SelectJob '{job_name}' | api leg inadmissible: API already "
            "read the target before the command (no transition witness)"
        )
        log.info(msg)
        logs.append(_make_log_entry("info", msg))
        return {
            "success": False,
            "logs": logs,
            "source": "api",
            "reason": "inadmissible_no_transition",
        }
    observed_after = command_started_at if command_started_at is not None else time.time()
    deadline = time.perf_counter() + timeout

    while time.perf_counter() < deadline:
        jobs = _reading_value_after(
            _readers.get_jobs(client, mode="api", diagnostics=True),
            observed_after,
        )
        if jobs:
            for j in jobs:
                if j.get("Name") == job_name and j.get("IsSelected"):
                    return {"success": True, "logs": logs}

        time.sleep(poll_interval)

    msg = f"Job selection timeout after {timeout:.1f}s for '{job_name}'"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs, "source": "api"}


def _confirm_select_job_log(job_name, command_started_at, *, timeout=None):
    """Log confirmation leg: a fresh post-command ``CurrentBlock`` event
    naming *job_name* (see ``log_wait``). Applied state, never intent."""
    profile = _state_reader_profile()
    logs = []
    if command_started_at is None:
        msg = "Log-backed job confirmation requires command_started_at"
        log.warning(msg)
        logs.append(_make_log_entry("warning", msg))
        return {"success": False, "logs": logs, "source": "log"}
    log_timeout = profile.selected_job_log_confirm_timeout_s
    if timeout is not None:
        log_timeout = min(log_timeout, max(0.0, timeout))
    log_result = log_wait.wait_for_selected_job_log(
        job_name,
        command_started_at=command_started_at,
        timeout_s=log_timeout,
        poll_interval_s=profile.selected_job_log_poll_interval_s,
        max_age_s=profile.selected_job_log_cluster_max_age_s,
    )
    if log_result.success:
        msg = (
            f"Job '{job_name}' confirmed from LAS X log "
            f"({log_result.elapsed_s * 1000:.0f}ms, "
            f"attempts={log_result.attempts})"
        )
        log.info(msg)
        logs.append(_make_log_entry("info", msg))
        return {
            "success": True,
            "logs": logs,
            "source": "log",
            "log_elapsed_s": log_result.elapsed_s,
            "log_diagnostics": log_result.diagnostics,
        }
    msg = f"Log-backed job selection timeout after {log_timeout:.1f}s for '{job_name}'"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {
        "success": False,
        "logs": logs,
        "source": "log",
        "log_reason": log_result.reason,
        "log_diagnostics": log_result.diagnostics,
    }


def select_job_confirm_legs(
    job_name, *, command_started_at, api_baseline_name=None, timeout=None, poll_interval=0.01
):
    """Build select_job's confirmation legs for the profile's source policy.

    The ONE place that knows what ``selected_job_confirm_source`` means:

    - ``api``: the API poll alone, exactly today's semantics.
    - ``log``: the post-command ``CurrentBlock`` wait alone.
    - ``hybrid``: both legs race (first admissible evidence wins); the api
      leg gets the transition-admissibility gate fed by
      *api_baseline_name*, and the race is bounded by
      ``selected_job_hybrid_budget_s``.

    Returns ``(api_confirm_fn, log_leg, budget_s)`` where ``api_confirm_fn``
    takes ``client`` (dispatch binds it), ``log_leg`` is zero-arg, and
    either may be None. Raises ``ValueError`` on an unknown source BEFORE
    anything fires.
    """
    profile = _state_reader_profile()
    source = profile.selected_job_confirm_source
    if source not in ("api", "log", "hybrid"):
        raise ValueError(
            f"unknown selected-job confirmation source {source!r}; expected api, log, or hybrid"
        )
    api_confirm = None
    log_leg = None
    budget_s = None
    if source in ("api", "hybrid"):
        api_confirm = partial(
            confirm_select_job,
            job_name=job_name,
            timeout=timeout,
            poll_interval=poll_interval,
            command_started_at=command_started_at,
            inadmissible_baseline=(api_baseline_name if source == "hybrid" else None),
            require_transition_witness=(source == "hybrid"),
        )
    if source in ("log", "hybrid"):
        log_leg = partial(_confirm_select_job_log, job_name, command_started_at, timeout=timeout)
    if api_confirm is not None and log_leg is not None:
        effective_timeout = CONFIRM_TIMEOUT if timeout is None else timeout
        budget_s = min(
            profile.selected_job_hybrid_budget_s,
            max(0.0, effective_timeout),
        )
    return api_confirm, log_leg, budget_s


def _bounded_api_read(client, fn, *, timeout_s):
    """Run a pre-command API read through the shared in-flight cap."""
    api_queue = _router._fire_api_read(fn, _router._client_api_key(client))
    if api_queue is None:
        return None, "api_in_flight"
    try:
        reading = api_queue.get(timeout=timeout_s)
    except queue.Empty:
        return None, "api_timeout"
    if reading.error is not None:
        return None, f"api_error:{type(reading.error).__name__}"
    return reading.value, "ok"


def _selected_job_api_jobs(client, profile):
    jobs, reason = _bounded_api_read(
        client,
        lambda: _router.api_reader.get_jobs(
            client,
            timeout=profile.jobs_timeout_s,
            max_retries=1,
        ),
        timeout_s=profile.jobs_timeout_s,
    )
    if not jobs:
        return None, reason if reason != "ok" else "api_no_jobs"
    return jobs, "ok"


def _selected_job_api_baseline(client, profile):
    jobs, reason = _selected_job_api_jobs(client, profile)
    if not jobs:
        return None, None, reason
    selected = None
    for job in jobs:
        if job.get("IsSelected"):
            selected = job.get("Name")
            break
    return selected, jobs, "ok" if selected else "api_no_selected_job"


def _prime_selected_job_log_cluster(client, jobs):
    """Best-effort ATL job-cluster priming for log-backed confirmation.

    LAS X writes complete ATL job blocks when each job's settings are queried.
    This is explicit API-assisted log priming: it generates log evidence, but
    the confirmation decision still gates only on post-command log content.
    """
    profile = _state_reader_profile()
    if (
        profile.selected_job_confirm_source not in ("log", "hybrid")
        or not profile.selected_job_log_prime_cluster
    ):
        return
    for job in jobs or []:
        name = job.get("Name") if isinstance(job, dict) else None
        if not name:
            continue
        try:
            _bounded_api_read(
                client,
                lambda n=name: _router.api_reader.get_job_settings(
                    client,
                    n,
                    timeout=profile.job_settings_timeout_s,
                    max_retries=1,
                ),
                timeout_s=profile.job_settings_timeout_s,
            )
        except Exception:
            log.debug("Could not prime log job cluster for %r", name, exc_info=True)


def _selected_job_name_from_log(profile):
    """Fresh selected-job name from LAS X logs, or None when unavailable."""
    try:
        from ..readers import log_reader as _log_reader

        max_age_s = profile.selected_job_log_cluster_max_age_s
        if max_age_s is None:
            max_age_s = profile.selected_job_log_max_age_s
        selected = _log_reader.get_selected_job(max_age_s=max_age_s)
    except Exception:
        log.debug("Could not read selected job from LAS X log", exc_info=True)
        return None
    return selected.get("Name") if selected else None


def prepare_select_job(client, job_name):
    """Pre-fire evidence for select_job: no-op decision plus api baseline.

    Returns ``(noop_result, context)``. ``noop_result`` is a command-style
    result dict (without timing - the command stamps that) when the target
    is provably already selected, else None. ``context`` carries
    ``api_baseline_name`` (the hybrid api leg's admissibility input) and
    ``api_said_selected`` (the API claimed the target was selected but a
    log-participating policy fired anyway - annotated on the result).

    No-op proof is source-coherent: in ``api`` mode the API readback
    decides, exactly as today. When the log participates (``log`` /
    ``hybrid``) only fresh log state can prove a no-op - a no-op re-select
    emits no new CurrentBlock event, and a stale API readback equalling the
    target is precisely the inadmissible evidence, so it must never
    suppress a real command. With the log stale or silent, the command
    fires and may time out unconfirmed: that is correct fail-closed
    behavior, not a bug.
    """
    profile = _state_reader_profile()
    source = profile.selected_job_confirm_source
    context = {
        "api_baseline_name": None,
        "api_baseline_reason": "not_attempted",
        "api_said_selected": False,
    }

    if source == "api":
        try:
            jobs = _readers.get_jobs(client, mode="api")
        except Exception:
            log.debug("Could not check current job selection before select_job", exc_info=True)
            return None, context
        for j in jobs or []:
            if j.get("IsSelected"):
                context["api_baseline_name"] = j.get("Name")
                break
        if context["api_baseline_name"] == job_name:
            return {
                "success": True,
                "confirmed": True,
                "message": f"'{job_name}' already selected",
                "logs": [],
            }, context
        return None, context

    # Log participates ("log" / "hybrid"): applied log state owns the no-op
    # decision.
    if _selected_job_name_from_log(profile) == job_name:
        return {
            "success": True,
            "confirmed": True,
            "message": f"'{job_name}' already selected",
            "logs": [_make_log_entry("info", "selected job already confirmed from LAS X log")],
        }, context
    if source == "log":
        try:
            if profile.selected_job_log_prime_cluster:
                jobs, reason = _selected_job_api_jobs(client, profile)
                if jobs is not None:
                    _prime_selected_job_log_cluster(client, jobs)
                else:
                    log.debug("Could not enumerate jobs before log priming: %s", reason)
        except Exception:
            log.debug("Could not prime jobs before log-backed select_job", exc_info=True)
        return None, context
    try:
        name, jobs, reason = _selected_job_api_baseline(client, profile)
        context["api_baseline_name"] = name
        context["api_baseline_reason"] = reason
        if jobs is not None:
            _prime_selected_job_log_cluster(client, jobs)
    except Exception:
        log.debug("Could not enumerate/prime jobs before select_job", exc_info=True)
    if context["api_baseline_name"] == job_name:
        context["api_said_selected"] = True
    return None, context
