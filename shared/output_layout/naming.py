"""Lab-wide canonical naming and layout for zmart-microscopy outputs.

Layout::

    media_path/smart/[experiment]_[hash6]/[acquisition-type]/{data,analysis,feedback}/

Filenames carry eight dimensional slots (k, m, g, p, t, v, c, z), each
zero-padded to a fixed width so listings sort sensibly. The XML companion
omits c and z (one XML per (k, m, g, p, t, v) position; it describes the
c x z grid). The 6-char `hash6` is base36-encoded seconds-since-EPOCH
(2026-01-01 UTC), so it is chronologically meaningful AND
lexicographically sortable.

Length caps on `experiment` and `acquisition_type` keep total paths under
Windows MAX_PATH (260) for a shallow output_root.

Pure functions plus frozen `Naming` / `LayoutPlan` dataclasses. Only
`build_layout` performs I/O (creates the run directory).
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

_HASH_LEN = 6
_COLLISION_RETRY_CAP = 10

# kebab-case lowercase: tokens separated by single hyphens
_ACQUISITION_TYPE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# experiment: alnum, underscore, hyphen (operator-facing freeform but bounded)
_EXPERIMENT_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_HASH_RE = re.compile(r"^[0-9a-z]{6}$")


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
    """Slot values for a single acquisition file.

    All 8 dimensional slots default to 0 when unused. Filename includes
    every slot; XML companion omits c and z (one XML per (k,m,g,p,t,v)
    position describes the c×z grid).
    """

    acquisition_type: str
    hash6: str
    k: int = 0
    m: int = 0
    g: int = 0
    p: int = 0
    t: int = 0
    v: int = 0
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


def build_image_name(n: Naming) -> str:
    """Canonical image filename. All 8 slots present, fixed-width zero-padded."""
    return (
        f"{n.acquisition_type}_{n.hash6}"
        f"_k{n.k:05d}_m{n.m:05d}_g{n.g:05d}_p{n.p:05d}"
        f"_t{n.t:05d}_v{n.v:02d}_c{n.c:02d}_z{n.z:05d}.ome.tiff"
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
    """Canonical data directory for one acquisition kind."""
    return acquisition_dir(output_root, kind) / "data"


def acquisition_metadata_dir(output_root: Path | str, kind: str) -> Path:
    """Canonical metadata directory for one acquisition kind."""
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
    r"_k(?P<k>\d{5})_m(?P<m>\d{5})_g(?P<g>\d{5})_p(?P<p>\d{5})"
    r"_t(?P<t>\d{5})_v(?P<v>\d{2})_c(?P<c>\d{2})_z(?P<z>\d{5})"
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
        k=int(m.group("k")),
        m=int(m.group("m")),
        g=int(m.group("g")),
        p=int(m.group("p")),
        t=int(m.group("t")),
        v=int(m.group("v")),
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
