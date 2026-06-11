"""Per-datum source capabilities - the one table behind the reader families.

Every datum the state readers serve is declared here once, with the legs
each source can provide:

- **passive legs** (``api_fn`` / ``log_fn``): answer "what is the state
  now?" for the routed readers in :mod:`router`. Either leg may be absent;
  a family asked for a leg the datum does not have fails closed with
  ``UnsupportedSource``, and ``hybrid`` degrades to the legs that exist.
- **evidence legs** (``evidence_log_fn`` + ``key_fn`` / ``target_fn``):
  answer "did the state visibly change / reach a target?" for
  :mod:`change_wait` and the confirmation race. These are deliberately
  separate from the passive legs - a passive value and command evidence
  are different questions even when they read the same log stream.

The table holds *capabilities* (facts about what a source can prove), not
preferences. Policy - which family is the default - lives in
``profiles.StateReaderProfile``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from . import api_reader, log_reader


class UnsupportedSource(RuntimeError):
    """The requested source family has no leg for this datum."""


def trust_present(reading) -> bool:
    return reading.error is None and reading.value is not None


def trust_status(reading) -> bool:
    return trust_present(reading) and reading.value != "Unknown"


@dataclass(frozen=True)
class DatumSpec:
    """Source capabilities for one datum.

    Passive legs are optional callables; evidence capabilities are present
    only for datums that support change detection / target confirmation.
    ``*_attr`` fields name ``StateReaderProfile`` attributes so every
    tunable stays in the profile.
    """

    mode_attr: str
    timeout_attr: str
    trust: Callable = trust_present
    api_fn: Callable | None = None      # (client, **kwargs) -> raw value
    log_fn: Callable | None = None      # (snapshot, *, max_age_s[, job_name])
    log_max_age_attr: str | None = None
    age_key: str | None = None          # key for age_for_snapshot()
    evidence_log_fn: Callable | None = None  # (snapshot) -> (value, observed_at)
    key_fn: Callable | None = None      # raw value -> comparable key or None
    target_fn: Callable | None = None   # target -> normalized key (validates)
    min_delta_attr: str | None = None   # profile attr for change min-delta
    numeric: bool = False


def key_delta(key, other):
    """Distance between two keys: max component delta for numeric tuples,
    ``None`` for equal discrete keys, ``inf`` for differing discrete keys."""
    if isinstance(key, tuple) and isinstance(other, tuple) \
            and len(key) == len(other):
        return max(abs(a - b) for a, b in zip(key, other, strict=True))
    return None if key == other else math.inf


def age_for_snapshot(snapshot, *, age_key=None, job_name=None):
    """Age of a datum's log value within *snapshot*, in seconds."""
    ages = log_reader.ages(snapshot)
    if job_name is not None:
        return ages.get("jobs", {}).get(job_name)
    if age_key == "jobs":
        values = [
            age for age in (ages.get("jobs") or {}).values()
            if age is not None
        ]
        job_list_age = ages.get("job_list")
        if job_list_age is not None:
            values.append(job_list_age)
        selected_age = ages.get("selected")
        if selected_age is not None:
            values.append(selected_age)
        current_block_age = ages.get("current_block")
        if current_block_age is not None:
            values.append(current_block_age)
        return max(values) if values else None
    if age_key == "selected_job":
        values = [
            age for age in (
                ages.get("current_block"),
                ages.get("selected"),
            )
            if age is not None
        ]
        return min(values) if values else None
    return ages.get(age_key)


def _selected_job_key(value):
    if not isinstance(value, dict):
        return None
    name = value.get("Name")
    if not isinstance(name, str) or not name.strip() or name == "Unknown":
        return None
    return name


def _selected_job_target(target):
    if not isinstance(target, str) or not target.strip() or target == "Unknown":
        raise ValueError(
            "selected_job target must be a non-empty job name")
    return target


def _selected_job_evidence(snapshot):
    # CurrentBlock is the measured fast-and-correct selection signal
    # (~0.2 s after a switch). SetCurrentSelectedElementID is an intent echo,
    # not applied state, so it is deliberately not used as evidence.
    if snapshot.current_block_name:
        return {"Name": snapshot.current_block_name}, snapshot.current_block_ts
    return None, None


def _xy_key(value):
    if not isinstance(value, dict):
        return None
    try:
        key = (float(value["x_um"]), float(value["y_um"]))
    except (KeyError, TypeError, ValueError):
        return None
    if any(math.isnan(c) or math.isinf(c) for c in key):
        return None
    return key


def _xy_target(target):
    if not isinstance(target, (tuple, list)) or len(target) != 2:
        raise ValueError("xy target must be a 2-item sequence")
    try:
        key = tuple(float(c) for c in target)
    except (TypeError, ValueError) as exc:
        raise ValueError("xy target must contain finite numbers") from exc
    if any(math.isnan(c) or math.isinf(c) for c in key):
        raise ValueError("xy target must contain finite numbers")
    return key


def _xy_evidence(snapshot):
    value = log_reader.get_xy(snapshot, max_age_s=None)
    observed_at = None if value is None else snapshot.xy_ts
    return value, observed_at


DATUMS = {
    "scan_status": DatumSpec(
        mode_attr="scan_status_mode",
        timeout_attr="scan_status_timeout_s",
        trust=trust_status,
        api_fn=lambda client, **kw: api_reader.get_scan_status(client),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_scan_status(
            snapshot, max_age_s=max_age_s),
        log_max_age_attr="scan_status_log_max_age_s",
        age_key="scan_status",
    ),
    "job_settings": DatumSpec(
        mode_attr="job_settings_mode",
        timeout_attr="job_settings_timeout_s",
        api_fn=lambda client, job_name, **kw: api_reader.get_job_settings(
            client, job_name, **kw),
        log_fn=lambda snapshot, *, max_age_s, job_name: (
            log_reader.get_job_settings(
                job_name, snapshot, max_age_s=max_age_s)),
        log_max_age_attr="job_settings_log_max_age_s",
    ),
    "hardware_info": DatumSpec(
        mode_attr="hardware_info_mode",
        timeout_attr="hardware_info_timeout_s",
        api_fn=lambda client, **kw: api_reader.get_hardware_info(client, **kw),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_hardware_info(
            snapshot, max_age_s=max_age_s),
        log_max_age_attr="hardware_info_log_max_age_s",
        age_key="hardware_info",
    ),
    "xy": DatumSpec(
        mode_attr="xy_mode",
        timeout_attr="xy_timeout_s",
        api_fn=lambda client, **kw: api_reader.get_xy(client, **kw),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_xy(
            snapshot, max_age_s=max_age_s),
        log_max_age_attr="xy_log_max_age_s",
        age_key="xy",
        evidence_log_fn=_xy_evidence,
        key_fn=_xy_key,
        target_fn=_xy_target,
        min_delta_attr="change_wait_xy_min_delta_um",
        numeric=True,
    ),
    "jobs": DatumSpec(
        mode_attr="jobs_mode",
        timeout_attr="jobs_timeout_s",
        api_fn=lambda client, **kw: api_reader.get_jobs(client, **kw),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_jobs(
            snapshot, max_age_s=max_age_s),
        log_max_age_attr="jobs_log_max_age_s",
        age_key="jobs",
    ),
    "selected_job": DatumSpec(
        mode_attr="selected_job_mode",
        timeout_attr="selected_job_timeout_s",
        api_fn=lambda client, **kw: api_reader.get_selected_job(client, **kw),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_selected_job(
            snapshot, max_age_s=max_age_s),
        log_max_age_attr="selected_job_log_max_age_s",
        age_key="selected_job",
        evidence_log_fn=_selected_job_evidence,
        key_fn=_selected_job_key,
        target_fn=_selected_job_target,
    ),
}


def spec(datum) -> DatumSpec:
    found = DATUMS.get(datum)
    if found is None:
        raise ValueError(f"unknown datum {datum!r}; known: {sorted(DATUMS)}")
    return found


def change_spec(datum) -> DatumSpec:
    """The spec for *datum*, required to support change/target evidence."""
    found = spec(datum)
    if found.key_fn is None or found.evidence_log_fn is None:
        raise ValueError(
            f"datum {datum!r} does not support change detection; "
            f"supported: {sorted(d for d, s in DATUMS.items() if s.key_fn)}")
    return found
