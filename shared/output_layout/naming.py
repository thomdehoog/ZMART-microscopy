"""Lab-wide canonical naming and layout for zmart-microscopy outputs.

Image layout is FLAT — one folder per acquisition type, one 2-D plane per
file, no sidecar XML::

    <output_root>/<acquisition_type>/<acquisition_type>_<hash6>_<position_label>_c<cc>_z<zzzzz>.ome.tiff

Each file is a single 2-D plane keyed only by channel (`c`) and z-slice
(`z`). `hash6` is minted PER ACQUISITION (not per session) and is a 6-char
base36 encoding of seconds-since-EPOCH (2026-01-01 UTC), so it is
chronologically meaningful AND lexicographically sortable. `position_label`
names the position; it is sanitized to ``[A-Za-z0-9_-]`` and length-capped.

There is no longer a companion ``.ome.xml``: the state of the
machine/software at export time is embedded directly in each plane's
OME-XML (a driver concern).

Length caps on `experiment`, `acquisition_type`, and `position_label` keep
total paths under Windows MAX_PATH (260) for a shallow output_root.

Pure functions plus frozen `Naming` / `LayoutPlan` dataclasses. Only
`build_layout` performs I/O (creates the run directory).

``build_xml_name`` and ``build_position_analysis_name`` remain for the
per-position analysis / legacy-companion workflow (a later migration
commit); they are not part of the current flat image contract.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

# Seconds-since-unix-epoch for 2026-01-01 00:00:00 UTC. The hash encodes
# (acquisition_start_time - EPOCH) in base36; values before EPOCH are invalid.
EPOCH = 1767225600

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"  # base36 lowercase, ASCII-sortable

# Length caps for inputs to keep total paths under Windows MAX_PATH=260
# with a shallow output_root. 40+25 leaves comfortable budget.
MAX_EXPERIMENT_LEN = 40
MAX_ACQUISITION_TYPE_LEN = 25
MAX_POSITION_LABEL_LEN = 40

_HASH_LEN = 6
_COLLISION_RETRY_CAP = 10

# kebab-case lowercase: tokens separated by single hyphens
_ACQUISITION_TYPE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# experiment: alnum, underscore, hyphen (operator-facing freeform but bounded)
_EXPERIMENT_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_HASH_RE = re.compile(r"^[0-9a-z]{6}$")
# position_label: any char outside this set is sanitized to '_'
_POSITION_LABEL_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]")


def run_hash(start_time: float | None = None) -> str:
    """6-char base36 encoding of seconds-since-EPOCH.

    Lexicographically sortable, chronologically meaningful. Deterministic
    from start_time. Defaults to current UTC time.
    """
    t = start_time if start_time is not None else time.time()
    n = int(t - EPOCH)
    if n < 0:
        raise ValueError(f"start_time {t} is before convention epoch {EPOCH} (2026-01-01 UTC)")
    if n == 0:
        return "0" * _HASH_LEN
    digits: list[str] = []
    while n:
        n, r = divmod(n, 36)
        digits.append(ALPHABET[r])
    return "".join(reversed(digits)).rjust(_HASH_LEN, "0")


@dataclass(frozen=True)
class Naming:
    """Slot values for a single canonical 2-D image plane.

    A flat image file is identified by its ``acquisition_type``, the
    per-acquisition ``hash6``, a ``position_label``, and the channel/z-slice
    coordinates (``c``, ``z``). ``position_label`` is sanitized in-place to
    ``[A-Za-z0-9_-]`` (any other char -> ``_``); the RAW label is
    length-capped at :data:`MAX_POSITION_LABEL_LEN`.
    """

    acquisition_type: str
    hash6: str
    position_label: str
    c: int = 0
    z: int = 0

    def __post_init__(self) -> None:
        if not _ACQUISITION_TYPE_RE.match(self.acquisition_type):
            raise ValueError(
                f"acquisition_type must be kebab-case lowercase, got: {self.acquisition_type!r}"
            )
        if len(self.acquisition_type) > MAX_ACQUISITION_TYPE_LEN:
            raise ValueError(
                f"acquisition_type too long "
                f"({len(self.acquisition_type)} > {MAX_ACQUISITION_TYPE_LEN}): "
                f"{self.acquisition_type!r}"
            )
        if not _HASH_RE.match(self.hash6):
            raise ValueError(f"hash6 must be 6 base36 chars (0-9, a-z), got: {self.hash6!r}")
        if len(self.position_label) > MAX_POSITION_LABEL_LEN:
            raise ValueError(
                f"position_label too long "
                f"({len(self.position_label)} > {MAX_POSITION_LABEL_LEN}): "
                f"{self.position_label!r}"
            )
        # Frozen dataclass: sanitize the label in place. Reject a label that
        # is empty (or becomes so — it never does, since '_' is a safe char).
        sanitized = _POSITION_LABEL_UNSAFE_RE.sub("_", self.position_label)
        if not sanitized:
            raise ValueError("position_label must be non-empty")
        object.__setattr__(self, "position_label", sanitized)


def build_image_name(n: Naming) -> str:
    """Canonical flat image filename: one 2-D plane keyed by ``c`` and ``z``."""
    return (
        f"{n.acquisition_type}_{n.hash6}_{n.position_label}"
        f"_c{n.c:02d}_z{n.z:05d}.ome.tiff"
    )


def build_xml_name(n: Naming) -> str:
    """Canonical XML companion filename. Omits c and z (one XML per position)."""
    return (
        f"{n.acquisition_type}_{n.hash6}"
        f"_k{n.k:05d}_m{n.m:05d}_g{n.g:05d}_p{n.p:05d}"
        f"_t{n.t:05d}_v{n.v:02d}.ome.xml"
    )


def acquisition_dir(output_root: Path | str, kind: str) -> Path:
    """Canonical acquisition-kind directory under a run root."""
    return Path(output_root) / kind


def acquisition_data_dir(output_root: Path | str, kind: str) -> Path:
    """Legacy nested ``data/`` directory for one acquisition kind.

    Retained for drivers/workflows not yet migrated to the flat layout. The
    flat image contract writes directly under :func:`acquisition_dir`.
    """
    return acquisition_dir(output_root, kind) / "data"


def acquisition_metadata_dir(output_root: Path | str, kind: str) -> Path:
    """Legacy nested metadata directory for one acquisition kind.

    Retired by the flat, no-sidecar layout (state is embedded per-plane).
    Retained only so unmigrated callers keep importing cleanly.
    """
    return acquisition_data_dir(output_root, kind) / "metadata"


def build_position_analysis_name(n: Naming) -> str:
    """Per-position analysis artifact. Same slots as XML (k,m,g,p,t,v), .npz extension."""
    return (
        f"{n.acquisition_type}_{n.hash6}"
        f"_k{n.k:05d}_m{n.m:05d}_g{n.g:05d}_p{n.p:05d}"
        f"_t{n.t:05d}_v{n.v:02d}.npz"
    )


_IMAGE_NAME_RE = re.compile(
    r"^(?P<acq>[a-z0-9]+(?:-[a-z0-9]+)*)_(?P<hash>[0-9a-z]{6})"
    r"_(?P<position_label>[A-Za-z0-9_-]+)_c(?P<c>\d{2})_z(?P<z>\d{5})"
    r"\.ome\.tiff$"
)


def parse_image_name(filename: str) -> Naming | None:
    """Inverse of build_image_name. Returns None on no match."""
    m = _IMAGE_NAME_RE.match(filename)
    if not m:
        return None
    return Naming(
        acquisition_type=m.group("acq"),
        hash6=m.group("hash"),
        position_label=m.group("position_label"),
        c=int(m.group("c")),
        z=int(m.group("z")),
    )


@dataclass(frozen=True)
class LayoutPlan:
    """Computed paths for a run. Built by `build_layout`."""

    output_root: Path
    experiment: str
    hash6: str
    start_time_utc: float

    @property
    def run_dir(self) -> Path:
        return self.output_root / f"{self.experiment}_{self.hash6}"

    def acquisition_dir(self, kind: str) -> Path:
        return acquisition_dir(self.run_dir, kind)

    def data_dir(self, kind: str) -> Path:
        return acquisition_data_dir(self.run_dir, kind)

    def metadata_dir(self, kind: str) -> Path:
        return acquisition_metadata_dir(self.run_dir, kind)

    def analysis_dir(self, kind: str) -> Path:
        return self.acquisition_dir(kind) / "analysis"

    def logs_dir(self, kind: str) -> Path:
        return self.acquisition_dir(kind) / "logs"


def build_layout(
    output_root: Path | str,
    experiment: str,
    *,
    start_time: float | None = None,
) -> LayoutPlan:
    """Build a LayoutPlan and atomically create the run directory.

    Uses `mkdir(exist_ok=False)` so two parallel processes can't race-create
    the same run dir. On hash collision (same UTC second), bumps start_time
    by 1s and retries, up to `_COLLISION_RETRY_CAP` attempts. Fails fast
    beyond that — operator collision implies a real bug, not a race.
    """
    if not experiment:
        raise ValueError("experiment must be non-empty")
    if len(experiment) > MAX_EXPERIMENT_LEN:
        raise ValueError(
            f"experiment too long ({len(experiment)} > {MAX_EXPERIMENT_LEN}): {experiment!r}"
        )
    if not _EXPERIMENT_RE.match(experiment):
        raise ValueError(f"experiment must match [a-zA-Z0-9_-]+, got: {experiment!r}")

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    t0 = start_time if start_time is not None else time.time()

    for offset in range(_COLLISION_RETRY_CAP):
        candidate_time = t0 + offset
        h = run_hash(candidate_time)
        candidate_dir = output_root / f"{experiment}_{h}"
        try:
            candidate_dir.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            continue
        return LayoutPlan(
            output_root=output_root,
            experiment=experiment,
            hash6=h,
            start_time_utc=candidate_time,
        )

    raise RuntimeError(
        f"{_COLLISION_RETRY_CAP} consecutive 1-second slots already taken "
        f"under {output_root} for experiment {experiment!r} — operator "
        f"collision or filesystem pathology"
    )
