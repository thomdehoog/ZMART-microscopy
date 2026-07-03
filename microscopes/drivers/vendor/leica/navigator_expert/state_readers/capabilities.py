"""Per-datum source capabilities - the one table behind the reader families.

Every datum the state readers serve is declared here once, with the passive
legs (``api_fn`` / ``log_fn``) each source can provide - answering "what is the
state now?" for the routed readers in :mod:`router`. Either leg may be absent;
a family asked for a leg the datum does not have fails closed with
``UnsupportedSource``, and ``hybrid`` degrades to the legs that exist.

The table holds *capabilities* (facts about what a source can prove), not
preferences. Policy - which family is the default - lives in
``profiles.StateReaderProfile``.
"""

from __future__ import annotations

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

    Passive legs are optional callables. ``*_attr`` fields name
    ``StateReaderProfile`` attributes so every tunable stays in the profile.
    """

    mode_attr: str
    timeout_attr: str
    trust: Callable = trust_present
    api_fn: Callable | None = None  # (client, **kwargs) -> raw value
    log_fn: Callable | None = None  # (snapshot, *, max_age_s[, job_name])
    log_max_age_attr: str | None = None
    age_key: str | None = None  # key for age_for_snapshot()


def age_for_snapshot(snapshot, *, age_key=None, job_name=None):
    """Age of a datum's log value within *snapshot*, in seconds."""
    ages = log_reader.ages(snapshot)
    if job_name is not None:
        return ages.get("jobs", {}).get(job_name)
    if age_key == "jobs":
        values = [age for age in (ages.get("jobs") or {}).values() if age is not None]
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
            age
            for age in (
                ages.get("current_block"),
                ages.get("selected"),
            )
            if age is not None
        ]
        return min(values) if values else None
    return ages.get(age_key)


DATUMS = {
    "scan_status": DatumSpec(
        mode_attr="scan_status_mode",
        timeout_attr="scan_status_timeout_s",
        trust=trust_status,
        api_fn=lambda client, **kw: api_reader.get_scan_status(client),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_scan_status(
            snapshot, max_age_s=max_age_s
        ),
        log_max_age_attr="scan_status_log_max_age_s",
        age_key="scan_status",
    ),
    "job_settings": DatumSpec(
        mode_attr="job_settings_mode",
        timeout_attr="job_settings_timeout_s",
        api_fn=lambda client, job_name, **kw: api_reader.get_job_settings(client, job_name, **kw),
        log_fn=lambda snapshot, *, max_age_s, job_name: log_reader.get_job_settings(
            job_name, snapshot, max_age_s=max_age_s
        ),
        log_max_age_attr="job_settings_log_max_age_s",
    ),
    "hardware_info": DatumSpec(
        mode_attr="hardware_info_mode",
        timeout_attr="hardware_info_timeout_s",
        api_fn=lambda client, **kw: api_reader.get_hardware_info(client, **kw),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_hardware_info(
            snapshot, max_age_s=max_age_s
        ),
        log_max_age_attr="hardware_info_log_max_age_s",
        age_key="hardware_info",
    ),
    "xy": DatumSpec(
        mode_attr="xy_mode",
        timeout_attr="xy_timeout_s",
        api_fn=lambda client, **kw: api_reader.get_xy(client, **kw),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_xy(snapshot, max_age_s=max_age_s),
        log_max_age_attr="xy_log_max_age_s",
        age_key="xy",
    ),
    "jobs": DatumSpec(
        mode_attr="jobs_mode",
        timeout_attr="jobs_timeout_s",
        api_fn=lambda client, **kw: api_reader.get_jobs(client, **kw),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_jobs(snapshot, max_age_s=max_age_s),
        log_max_age_attr="jobs_log_max_age_s",
        age_key="jobs",
    ),
    "selected_job": DatumSpec(
        mode_attr="selected_job_mode",
        timeout_attr="selected_job_timeout_s",
        api_fn=lambda client, **kw: api_reader.get_selected_job(client, **kw),
        log_fn=lambda snapshot, *, max_age_s: log_reader.get_selected_job(
            snapshot, max_age_s=max_age_s
        ),
        log_max_age_attr="selected_job_log_max_age_s",
        age_key="selected_job",
    ),
}


def spec(datum) -> DatumSpec:
    found = DATUMS.get(datum)
    if found is None:
        raise ValueError(f"unknown datum {datum!r}; known: {sorted(DATUMS)}")
    return found
