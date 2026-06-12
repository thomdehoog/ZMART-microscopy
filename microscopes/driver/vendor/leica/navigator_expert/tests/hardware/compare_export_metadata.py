"""Offline metadata verifier for canonical LAS X ``save()`` outputs.

Exit codes: 0 no hard failures, 1 invalid metadata/mismatch, 2 setup error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

_HERE = Path(__file__).resolve()
_LEICA = _HERE.parents[3]
_REPO = _HERE.parents[6]
for _p in (_REPO, _LEICA):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.output_layout import parse_image_name  # noqa: E402

HARD_FIELDS = ("SizeX", "SizeY", "SizeZ", "SizeC", "SizeT")
PHYSICAL_AXES = ("X", "Y", "Z")
SOFT_COLLECTIONS = ("channels", "objectives", "detectors", "lasers")


@dataclass(frozen=True, order=True)
class PlaneKey:
    acquisition_type: str
    k: int
    m: int
    g: int
    p: int
    t: int
    v: int
    c: int
    z: int

    @property
    def position(self) -> PositionKey:
        return PositionKey(
            acquisition_type=self.acquisition_type,
            k=self.k,
            m=self.m,
            g=self.g,
            p=self.p,
            t=self.t,
            v=self.v,
        )

    def label(self) -> str:
        return (
            f"{self.acquisition_type}:k{self.k}:m{self.m}:g{self.g}:"
            f"p{self.p}:t{self.t}:v{self.v}:c{self.c}:z{self.z}"
        )


@dataclass(frozen=True, order=True)
class PositionKey:
    acquisition_type: str
    k: int
    m: int
    g: int
    p: int
    t: int
    v: int

    def label(self) -> str:
        return (
            f"{self.acquisition_type}:k{self.k}:m{self.m}:g{self.g}:"
            f"p{self.p}:t{self.t}:v{self.v}"
        )


@dataclass
class SavedRecord:
    key: PlaneKey
    image_path: Path
    xml_path: Path
    raw: dict[str, Any]


@dataclass
class SavedOutput:
    label: str
    root: Path
    summary: dict[str, Any]
    records: dict[PlaneKey, SavedRecord]
    xml_by_position: dict[PositionKey, Path]


class SetupError(RuntimeError):
    """Bad verifier input or missing required tooling."""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = _empty_report(args)

    try:
        nav = _load_output("navigator", Path(args.navigator_output))
        native = _load_output("native", Path(args.native_output))
        report["inputs"]["navigator"]["summary_entries"] = len(nav.records)
        report["inputs"]["native"]["summary_entries"] = len(native.records)

        _validate_output_ome(nav, report, require_schema=args.require_schema)
        _validate_output_ome(native, report, require_schema=args.require_schema)
        _compare_outputs(
            nav,
            native,
            report,
            require_pixel_equality=args.require_pixel_equality,
        )
        _assess_fair_readiness(nav, report)
        _assess_fair_readiness(native, report)
    except SetupError as e:
        _add(report, "hard_failures", "setup", "SETUP", str(e))
        report["exit_code"] = 2
    except Exception as e:
        _add(
            report,
            "hard_failures",
            "setup",
            "UNHANDLED",
            f"{type(e).__name__}: {e}",
        )
        report["exit_code"] = 2
    else:
        report["exit_code"] = 1 if report["hard_failures"] else 0

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
    _print_human_summary(report, json_out=args.json_out)
    return int(report["exit_code"])


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline metadata verifier for canonical LAS X save outputs."
    )
    parser.add_argument("--navigator-output", required=True, type=Path)
    parser.add_argument("--native-output", required=True, type=Path)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write the machine-readable JSON report.",
    )
    parser.add_argument(
        "--require-schema",
        action="store_true",
        help="Missing schema validator is setup failure (exit 2).",
    )
    parser.add_argument(
        "--require-pixel-equality",
        action="store_true",
        help="Require exact pixel equality for matched planes.",
    )
    return parser.parse_args(argv)


def _empty_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "inputs": {
            "navigator": {
                "root": str(Path(args.navigator_output)),
                "summary_entries": None,
            },
            "native": {
                "root": str(Path(args.native_output)),
                "summary_entries": None,
            },
        },
        "environment": {
            "validator": None,
            "schema_versions": [],
            "require_schema": bool(args.require_schema),
            "require_pixel_equality": bool(args.require_pixel_equality),
        },
        "ome_conformance": [],
        "semantic_comparison": {
            "plane_count": {},
            "position_count": {},
            "pixel_equality_checked": bool(args.require_pixel_equality),
        },
        "fair_readiness": {},
        "hard_failures": [],
        "warnings": [],
        "ignored_differences": [
            {
                "code": "EXPECTED_DIFFERENCES",
                "message": (
                    "File paths, source filenames, UUIDs, TiffData IFDs, "
                    "native .xlef/.xlif/.lof files, metadata location, and "
                    "timestamps are expected to differ and are ignored."
                ),
            }
        ],
        "exit_code": None,
    }


def _load_output(label: str, root: Path) -> SavedOutput:
    root = root.resolve()
    summary_path = root / "summary.json"
    if not summary_path.is_file():
        raise SetupError(f"{label}: missing required summary.json at {summary_path}")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SetupError(f"{label}: could not read summary.json: {e}") from e

    acqs = summary.get("acquisitions")
    if not isinstance(acqs, list) or not acqs:
        raise SetupError(f"{label}: summary.json has no acquisitions list")

    records: dict[PlaneKey, SavedRecord] = {}
    xml_by_position: dict[PositionKey, Path] = {}
    for i, record in enumerate(acqs):
        if not isinstance(record, dict):
            raise SetupError(f"{label}: acquisition record {i} is not an object")
        image_path = _resolve_record_path(root, record.get("image_path"))
        xml_path = _resolve_record_path(root, record.get("xml_path"))
        naming = _record_naming(record, image_path)
        key = _plane_key(naming)
        if key in records:
            raise SetupError(f"{label}: duplicate plane key {key.label()}")
        records[key] = SavedRecord(
            key=key,
            image_path=image_path,
            xml_path=xml_path,
            raw=record,
        )
        existing_xml = xml_by_position.get(key.position)
        if existing_xml is not None and existing_xml != xml_path:
            raise SetupError(
                f"{label}: position {key.position.label()} maps to multiple XMLs"
            )
        xml_by_position[key.position] = xml_path

    return SavedOutput(
        label=label,
        root=root,
        summary=summary,
        records=records,
        xml_by_position=xml_by_position,
    )


def _resolve_record_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise SetupError(f"summary record has invalid path: {value!r}")
    p = Path(value)
    if not p.is_absolute():
        p = root / Path(value.replace("/", os.sep))
    p = p.resolve()
    if not p.is_file():
        raise SetupError(f"summary path does not resolve: {p}")
    return p


def _record_naming(record: dict[str, Any], image_path: Path) -> dict[str, Any]:
    naming = record.get("naming")
    if isinstance(naming, dict):
        return naming
    parsed = parse_image_name(image_path.name)
    if parsed is None:
        raise SetupError(
            f"record lacks naming and image filename is not canonical: {image_path}"
        )
    return {
        "acquisition_type": parsed.acquisition_type,
        "k": parsed.k,
        "m": parsed.m,
        "g": parsed.g,
        "p": parsed.p,
        "t": parsed.t,
        "v": parsed.v,
        "c": parsed.c,
        "z": parsed.z,
    }


def _plane_key(naming: dict[str, Any]) -> PlaneKey:
    try:
        return PlaneKey(
            acquisition_type=str(naming["acquisition_type"]),
            k=int(naming.get("k", 0)),
            m=int(naming.get("m", 0)),
            g=int(naming.get("g", 0)),
            p=int(naming.get("p", 0)),
            t=int(naming.get("t", 0)),
            v=int(naming.get("v", 0)),
            c=int(naming.get("c", 0)),
            z=int(naming.get("z", 0)),
        )
    except Exception as e:
        raise SetupError(f"invalid naming record: {naming!r}") from e


def _validate_output_ome(
    output: SavedOutput,
    report: dict[str, Any],
    *,
    require_schema: bool,
) -> None:
    for image_path in sorted({r.image_path for r in output.records.values()}):
        result = _validate_tiff_ome(image_path, require_schema=require_schema)
        result["output"] = output.label
        report["ome_conformance"].append(result)
        _record_validation_result(result, report, require_schema=require_schema)

    for xml_path in sorted(set(output.xml_by_position.values())):
        result = _validate_xml_file(xml_path, require_schema=require_schema)
        result["output"] = output.label
        report["ome_conformance"].append(result)
        _record_validation_result(result, report, require_schema=require_schema)


def _validate_tiff_ome(path: Path, *, require_schema: bool) -> dict[str, Any]:
    try:
        import tifffile

        with tifffile.TiffFile(str(path)) as tif:
            xml_text = tif.pages[0].description or ""
    except Exception as e:
        return {
            "path": str(path),
            "kind": "ome.tiff",
            "status": "INVALID",
            "validator": "tifffile",
            "schema_version": None,
            "errors": [f"could not read TIFF ImageDescription: {e}"],
            "warnings": [],
            "known_repair_needed": None,
        }
    if "<OME" not in xml_text:
        return {
            "path": str(path),
            "kind": "ome.tiff",
            "status": "INVALID",
            "validator": "tifffile",
            "schema_version": None,
            "errors": ["TIFF has no embedded OME-XML ImageDescription"],
            "warnings": [],
            "known_repair_needed": None,
        }
    return _validate_ome_xml_text(
        xml_text,
        path=path,
        kind="ome.tiff",
        require_schema=require_schema,
        tiff_path=path,
    )


def _validate_xml_file(path: Path, *, require_schema: bool) -> dict[str, Any]:
    try:
        xml_text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        xml_text = path.read_text(encoding="latin-1")
    except Exception as e:
        return {
            "path": str(path),
            "kind": "ome.xml",
            "status": "INVALID",
            "validator": "xml-read",
            "schema_version": None,
            "errors": [f"could not read XML: {e}"],
            "warnings": [],
            "known_repair_needed": None,
        }
    return _validate_ome_xml_text(
        xml_text,
        path=path,
        kind="ome.xml",
        require_schema=require_schema,
    )


def _validate_ome_xml_text(
    xml_text: str,
    *,
    path: Path,
    kind: str,
    require_schema: bool,
    tiff_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    schema_version = None
    validator = "ome-types"
    schema_skipped = False
    known_repair_needed = 'Wavelength="0"' in xml_text

    try:
        root = ET.fromstring(xml_text)
        schema_version = _schema_version(root)
        missing = _missing_required_ome_fields(root)
        if missing:
            errors.append("missing required OME fields: " + ", ".join(missing))
    except Exception as e:
        root = None
        errors.append(f"XML parse failed: {e}")

    try:
        if tiff_path is not None:
            from ome_types import from_tiff

            from_tiff(str(tiff_path), validate=True)
        else:
            from ome_types import from_xml

            from_xml(xml_text, validate=True)
    except ImportError as e:
        validator = "none"
        schema_skipped = True
        warnings.append(f"ome-types unavailable: {e}")
        if require_schema:
            errors.append("schema validation required but unavailable")
    except Exception as e:
        errors.append(f"ome-types validation failed: {e}")

    if known_repair_needed:
        errors.append('known Leica OME repair still needed: Wavelength="0"')
    if errors:
        status = "INVALID"
    elif schema_skipped:
        status = "SKIP"
    else:
        status = "VALID"

    return {
        "path": str(path),
        "kind": kind,
        "status": status,
        "validator": validator,
        "schema_version": schema_version,
        "errors": errors,
        "warnings": warnings,
        "known_repair_needed": known_repair_needed,
    }


def _record_validation_result(
    result: dict[str, Any],
    report: dict[str, Any],
    *,
    require_schema: bool,
) -> None:
    validator = result.get("validator")
    if validator and report["environment"]["validator"] is None:
        report["environment"]["validator"] = validator
    schema_version = result.get("schema_version")
    if schema_version and schema_version not in report["environment"]["schema_versions"]:
        report["environment"]["schema_versions"].append(schema_version)

    status = result.get("status")
    if status == "INVALID":
        _add(
            report,
            "hard_failures",
            "ome_conformance",
            "OME_INVALID",
            f"{result['kind']} invalid: {result['path']}",
            details=result.get("errors"),
        )
    elif status == "SKIP":
        target = "hard_failures" if require_schema else "warnings"
        code = "SCHEMA_VALIDATOR_MISSING" if require_schema else "SCHEMA_SKIPPED"
        _add(
            report,
            target,
            "ome_conformance",
            code,
            f"schema validation skipped for {result['path']}",
            details=result.get("warnings") or result.get("errors"),
        )


def _missing_required_ome_fields(root: ET.Element) -> list[str]:
    pixels = _first_local(root, "Pixels")
    if pixels is None:
        return ["Pixels"]
    missing = [
        name
        for name in (
            "DimensionOrder",
            "Type",
            "SizeX",
            "SizeY",
            "SizeZ",
            "SizeC",
            "SizeT",
        )
        if pixels.attrib.get(name) in (None, "")
    ]
    if not list(_children_local(pixels, "Channel")):
        missing.append("Channel")
    return missing


def _compare_outputs(
    nav: SavedOutput,
    native: SavedOutput,
    report: dict[str, Any],
    *,
    require_pixel_equality: bool,
) -> None:
    include_acquisition_type = _include_acquisition_type_in_compare(nav, native)
    nav_records = _records_by_compare_key(nav, include_acquisition_type)
    native_records = _records_by_compare_key(native, include_acquisition_type)
    nav_keys = set(nav_records)
    native_keys = set(native_records)
    nav_xml = _xml_by_compare_key(nav, include_acquisition_type)
    native_xml = _xml_by_compare_key(native, include_acquisition_type)
    report["semantic_comparison"]["plane_count"] = {
        "navigator": len(nav_keys),
        "native": len(native_keys),
    }
    report["semantic_comparison"]["position_count"] = {
        "navigator": len(nav_xml),
        "native": len(native_xml),
    }
    report["semantic_comparison"]["acquisition_type_normalized"] = (
        not include_acquisition_type
    )

    if nav_keys != native_keys:
        _add(
            report,
            "hard_failures",
            "semantic",
            "PLANE_GRID_MISMATCH",
            "plane grids differ",
            details={
                "navigator_only": [
                    _compare_key_label(k) for k in sorted(nav_keys - native_keys)
                ],
                "native_only": [
                    _compare_key_label(k) for k in sorted(native_keys - nav_keys)
                ],
            },
        )
    if set(nav_xml) != set(native_xml):
        _add(
            report,
            "hard_failures",
            "semantic",
            "POSITION_GRID_MISMATCH",
            "position/XML grids differ",
            details={
                "navigator_only": [
                    _compare_key_label(k)
                    for k in sorted(set(nav_xml) - set(native_xml))
                ],
                "native_only": [
                    _compare_key_label(k)
                    for k in sorted(set(native_xml) - set(nav_xml))
                ],
            },
        )

    xml_meta_nav = {
        key: _ome_metadata_from_file(path)
        for key, path in nav_xml.items()
    }
    xml_meta_native = {
        key: _ome_metadata_from_file(path)
        for key, path in native_xml.items()
    }

    for pos_key in sorted(set(xml_meta_nav) & set(xml_meta_native)):
        _compare_companion_metadata(
            _compare_key_label(pos_key),
            xml_meta_nav[pos_key],
            xml_meta_native[pos_key],
            report,
        )

    image_info_nav = {
        key: _image_info(record.image_path)
        for key, record in nav_records.items()
    }
    image_info_native = {
        key: _image_info(record.image_path)
        for key, record in native_records.items()
    }
    for key in sorted(nav_keys & native_keys):
        _compare_image_info(
            _compare_key_label(key),
            image_info_nav[key],
            image_info_native[key],
            nav_records[key].image_path,
            native_records[key].image_path,
            report,
            require_pixel_equality=require_pixel_equality,
        )


def _compare_companion_metadata(
    label: str,
    nav: dict[str, Any],
    native: dict[str, Any],
    report: dict[str, Any],
) -> None:
    for field in HARD_FIELDS:
        _compare_required_when_present(
            report,
            section="semantic",
            code="OME_SIZE_MISMATCH",
            label=label,
            field=field,
            left=nav["sizes"].get(field),
            right=native["sizes"].get(field),
        )
    for axis in PHYSICAL_AXES:
        left = nav["physical"].get(axis)
        right = native["physical"].get(axis)
        field = f"PhysicalSize{axis}"
        if left is None or right is None:
            if left != right:
                _add(
                    report,
                    "warnings",
                    "semantic",
                    "PHYSICAL_SIZE_PRESENCE_ASYMMETRY",
                    f"{label}: {field} present in one output only",
                    details={"navigator": left, "native": right},
                )
            continue
        if not _float_close(left["um"], right["um"]):
            _add(
                report,
                "hard_failures",
                "semantic",
                "PHYSICAL_SIZE_MISMATCH",
                f"{label}: {field} differs",
                details={"navigator": left, "native": right},
            )

    _compare_required_when_present(
        report,
        section="semantic",
        code="CHANNEL_COUNT_MISMATCH",
        label=label,
        field="channel_count",
        left=nav.get("channel_count"),
        right=native.get("channel_count"),
    )
    for collection in SOFT_COLLECTIONS:
        if nav.get(collection) != native.get(collection):
            _add(
                report,
                "warnings",
                "semantic",
                "SOFT_METADATA_DIFFERENCE",
                f"{label}: {collection} differs",
                details={
                    "field": collection,
                    "navigator": nav.get(collection),
                    "native": native.get(collection),
                },
            )


def _compare_image_info(
    label: str,
    nav: dict[str, Any],
    native: dict[str, Any],
    nav_path: Path,
    native_path: Path,
    report: dict[str, Any],
    *,
    require_pixel_equality: bool,
) -> None:
    for field in ("shape", "dtype", "pixel_type"):
        _compare_required_when_present(
            report,
            section="semantic",
            code="IMAGE_METADATA_MISMATCH",
            label=label,
            field=field,
            left=nav.get(field),
            right=native.get(field),
        )
    if not require_pixel_equality:
        return
    try:
        import numpy as np
        import tifffile

        nav_arr = tifffile.imread(str(nav_path))
        native_arr = tifffile.imread(str(native_path))
        equal = np.array_equal(nav_arr, native_arr)
    except Exception as e:
        _add(
            report,
            "hard_failures",
            "semantic",
            "PIXEL_EQUALITY_ERROR",
            f"{label}: pixel equality check failed to run",
            details=str(e),
        )
        return
    if not equal:
        _add(
            report,
            "hard_failures",
            "semantic",
            "PIXEL_MISMATCH",
            f"{label}: pixel arrays differ",
            details={"navigator": str(nav_path), "native": str(native_path)},
        )


def _include_acquisition_type_in_compare(
    nav: SavedOutput,
    native: SavedOutput,
) -> bool:
    nav_types = {k.acquisition_type for k in nav.records}
    native_types = {k.acquisition_type for k in native.records}
    return not (
        len(nav_types) == 1
        and len(native_types) == 1
        and nav_types != native_types
    )


def _records_by_compare_key(
    output: SavedOutput,
    include_acquisition_type: bool,
) -> dict[tuple[Any, ...], SavedRecord]:
    records: dict[tuple[Any, ...], SavedRecord] = {}
    for key, record in output.records.items():
        compare_key = _plane_compare_key(key, include_acquisition_type)
        if compare_key in records:
            raise SetupError(
                f"{output.label}: duplicate normalized plane key "
                f"{_compare_key_label(compare_key)}"
            )
        records[compare_key] = record
    return records


def _xml_by_compare_key(
    output: SavedOutput,
    include_acquisition_type: bool,
) -> dict[tuple[Any, ...], Path]:
    out: dict[tuple[Any, ...], Path] = {}
    for key, path in output.xml_by_position.items():
        compare_key = _position_compare_key(key, include_acquisition_type)
        if compare_key in out and out[compare_key] != path:
            raise SetupError(
                f"{output.label}: duplicate normalized position key "
                f"{_compare_key_label(compare_key)}"
            )
        out[compare_key] = path
    return out


def _plane_compare_key(
    key: PlaneKey,
    include_acquisition_type: bool,
) -> tuple[Any, ...]:
    parts = (key.k, key.m, key.g, key.p, key.t, key.v, key.c, key.z)
    return (key.acquisition_type, *parts) if include_acquisition_type else parts


def _position_compare_key(
    key: PositionKey,
    include_acquisition_type: bool,
) -> tuple[Any, ...]:
    parts = (key.k, key.m, key.g, key.p, key.t, key.v)
    return (key.acquisition_type, *parts) if include_acquisition_type else parts


def _compare_key_label(key: tuple[Any, ...]) -> str:
    if len(key) == 9:
        acq, k, m, g, p, t, v, c, z = key
        return f"{acq}:k{k}:m{m}:g{g}:p{p}:t{t}:v{v}:c{c}:z{z}"
    if len(key) == 8:
        k, m, g, p, t, v, c, z = key
        return f"k{k}:m{m}:g{g}:p{p}:t{t}:v{v}:c{c}:z{z}"
    if len(key) == 7:
        acq, k, m, g, p, t, v = key
        return f"{acq}:k{k}:m{m}:g{g}:p{p}:t{t}:v{v}"
    if len(key) == 6:
        k, m, g, p, t, v = key
        return f"k{k}:m{m}:g{g}:p{p}:t{t}:v{v}"
    return str(key)


def _compare_required_when_present(
    report: dict[str, Any],
    *,
    section: str,
    code: str,
    label: str,
    field: str,
    left: Any,
    right: Any,
) -> None:
    if left is None or right is None:
        if left != right:
            _add(
                report,
                "warnings",
                section,
                "PRESENCE_ASYMMETRY",
                f"{label}: {field} present in one output only",
                details={"field": field, "navigator": left, "native": right},
            )
        return
    if left != right:
        _add(
            report,
            "hard_failures",
            section,
            code,
            f"{label}: {field} differs",
            details={"field": field, "navigator": left, "native": right},
        )


def _ome_metadata_from_file(path: Path) -> dict[str, Any]:
    text = _read_xml_text(path)
    try:
        root = ET.fromstring(text)
    except Exception as e:
        return {
            "path": str(path),
            "parse_error": str(e),
            "sizes": {},
            "physical": {},
            "channels": [],
            "channel_count": None,
            "objectives": [],
            "detectors": [],
            "lasers": [],
            "schema_version": None,
            "filename_refs": [],
        }
    pixels = _first_local(root, "Pixels")
    sizes = {}
    physical = {}
    pixel_type = None
    channels: list[dict[str, str]] = []
    if pixels is not None:
        pixel_type = pixels.attrib.get("Type")
        for field in HARD_FIELDS:
            sizes[field] = _int_or_none(pixels.attrib.get(field))
        for axis in PHYSICAL_AXES:
            value = _float_or_none(pixels.attrib.get(f"PhysicalSize{axis}"))
            unit = pixels.attrib.get(f"PhysicalSize{axis}Unit")
            if value is not None:
                physical[axis] = _normalize_physical_size(value, unit)
        channels = [
            _clean_attrs(ch.attrib)
            for ch in _children_local(pixels, "Channel")
        ]
    return {
        "path": str(path),
        "schema_version": _schema_version(root),
        "sizes": sizes,
        "pixel_type": pixel_type,
        "physical": physical,
        "channels": channels,
        "channel_count": sizes.get("SizeC") or len(channels) or None,
        "objectives": [_clean_attrs(e.attrib) for e in _iter_local(root, "Objective")],
        "detectors": [_clean_attrs(e.attrib) for e in _iter_local(root, "Detector")],
        "lasers": [_clean_attrs(e.attrib) for e in _iter_local(root, "Laser")],
        "filename_refs": _filename_refs(text),
    }


def _image_info(path: Path) -> dict[str, Any]:
    try:
        import tifffile

        arr = tifffile.imread(str(path))
        xml_text = ""
        with tifffile.TiffFile(str(path)) as tif:
            if tif.pages:
                xml_text = tif.pages[0].description or ""
        pixel_type = _pixel_type_from_xml(xml_text) or _dtype_to_ome_type(str(arr.dtype))
        return {
            "shape": list(arr.shape),
            "dtype": str(arr.dtype),
            "pixel_type": pixel_type,
        }
    except Exception as e:
        return {
            "shape": None,
            "dtype": None,
            "pixel_type": None,
            "error": str(e),
        }


def _pixel_type_from_xml(xml_text: str) -> str | None:
    if "<OME" not in xml_text:
        return None
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None
    pixels = _first_local(root, "Pixels")
    if pixels is None:
        return None
    return pixels.attrib.get("Type")


def _dtype_to_ome_type(dtype: str) -> str | None:
    return {
        "uint8": "uint8",
        "uint16": "uint16",
        "uint32": "uint32",
        "int8": "int8",
        "int16": "int16",
        "int32": "int32",
        "float32": "float",
        "float64": "double",
    }.get(dtype)


def _assess_fair_readiness(output: SavedOutput, report: dict[str, Any]) -> None:
    records = list(output.records.values())
    image_paths = [r.image_path for r in records]
    xml_paths = sorted(set(output.xml_by_position.values()))
    checksum_paths = sorted(set(image_paths + xml_paths))
    xml_meta = {
        pos: _ome_metadata_from_file(path)
        for pos, path in output.xml_by_position.items()
    }
    filename_refs = sorted({
        ref
        for meta in xml_meta.values()
        for ref in meta.get("filename_refs", [])
    })
    canonical_basenames = {p.name for p in image_paths}
    source_refs = [
        ref for ref in filename_refs
        if Path(ref).name not in canonical_basenames
    ]
    if source_refs:
        _add(
            report,
            "warnings",
            "fair_readiness",
            "COMPANION_SOURCE_FILENAME_REFS",
            (
                f"{output.label}: companion XML references source filenames; "
                "canonical summary paths remain the location truth"
            ),
            details=source_refs[:20],
        )

    lineage_present = all(r.raw.get("lineage") for r in records)
    source_exporter_present = all(r.raw.get("source_exporter") for r in records)
    source_present = all(r.raw.get("source") for r in records)
    physical_present = {
        axis: all(axis in meta.get("physical", {}) for meta in xml_meta.values())
        for axis in PHYSICAL_AXES
    }
    channel_metadata_present = all(
        bool(meta.get("channels")) for meta in xml_meta.values()
    )
    objective_reported = any(meta.get("objectives") for meta in xml_meta.values())

    if not lineage_present:
        _add(
            report,
            "warnings",
            "fair_readiness",
            "PROVENANCE_LINEAGE_MISSING",
            f"{output.label}: at least one summary record has no lineage",
        )
    if not source_exporter_present or not source_present:
        _add(
            report,
            "warnings",
            "fair_readiness",
            "SOURCE_PROVENANCE_MISSING",
            f"{output.label}: source_exporter/source not complete in summary",
        )
    if not all(physical_present.values()):
        _add(
            report,
            "warnings",
            "fair_readiness",
            "PHYSICAL_SIZE_INCOMPLETE",
            f"{output.label}: PhysicalSize metadata incomplete",
            details=physical_present,
        )
    if not channel_metadata_present:
        _add(
            report,
            "warnings",
            "fair_readiness",
            "CHANNEL_METADATA_INCOMPLETE",
            f"{output.label}: channel metadata missing from at least one companion",
        )
    if not objective_reported:
        _add(
            report,
            "warnings",
            "fair_readiness",
            "OBJECTIVE_METADATA_MISSING",
            f"{output.label}: objective metadata not found in companions",
        )

    report["fair_readiness"][output.label] = {
        "name": "FAIR-readiness",
        "not_fair_compliance": True,
        "findable": {
            "summary_entries": len(records),
            "source_exporter_recorded": source_exporter_present,
            "source_recorded": source_present,
        },
        "accessible_self_contained": {
            "summary_paths_resolve": True,
            "companion_source_filename_refs": source_refs,
        },
        "reusable_provenance": {
            "physical_size_present": physical_present,
            "channel_metadata_present": channel_metadata_present,
            "objective_metadata_reported": objective_reported,
            "lineage_present": lineage_present,
            "job_recorded": any("job" in r.raw for r in records),
            "driver_version_recorded": any("driver_version" in r.raw for r in records),
            "materialization_step_recorded": any(
                "materialization_step" in r.raw for r in records
            ),
        },
        "checksums_sha256": {
            _rel_display(p, output.root): _sha256(p) for p in checksum_paths
        },
    }


def _read_xml_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _schema_version(root: ET.Element) -> str | None:
    tag = root.tag
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


def _first_local(root: ET.Element, name: str) -> ET.Element | None:
    for element in root.iter():
        if _local_name(element.tag) == name:
            return element
    return None


def _iter_local(root: ET.Element, name: str):
    for element in root.iter():
        if _local_name(element.tag) == name:
            yield element


def _children_local(root: ET.Element, name: str):
    for element in list(root):
        if _local_name(element.tag) == name:
            yield element


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if tag.startswith("{") else tag


def _clean_attrs(attrs: dict[str, Any]) -> dict[str, str]:
    return {
        _local_name(str(k)): str(v)
        for k, v in sorted(attrs.items())
    }


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_physical_size(value: float, unit: str | None) -> dict[str, Any]:
    unit_key = (unit or "um").strip().lower()
    scale_to_um = {
        "um": 1.0,
        "\u00b5m": 1.0,
        "micrometer": 1.0,
        "micrometers": 1.0,
        "micrometre": 1.0,
        "micrometres": 1.0,
        "nm": 0.001,
        "nanometer": 0.001,
        "nanometers": 0.001,
        "nanometre": 0.001,
        "nanometres": 0.001,
        "mm": 1000.0,
        "m": 1000000.0,
    }
    scale = scale_to_um.get(unit_key)
    return {
        "value": value,
        "unit": unit,
        "um": value * scale if scale is not None else None,
        "normalized_unit": "um" if scale is not None else None,
    }


def _float_close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left == right
    return abs(left - right) <= max(
        1e-6,
        5e-3 * max(abs(left), abs(right), 1.0),
    )


def _filename_refs(xml_text: str) -> list[str]:
    return sorted(set(re.findall(r'FileName="([^"]+)"', xml_text)))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel_display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _add(
    report: dict[str, Any],
    bucket: str,
    section: str,
    code: str,
    message: str,
    *,
    details: Any = None,
) -> None:
    item = {
        "section": section,
        "code": code,
        "message": message,
    }
    if details is not None:
        item["details"] = details
    report[bucket].append(item)


def _print_human_summary(report: dict[str, Any], *, json_out: Path | None) -> None:
    statuses: dict[str, int] = {}
    for item in report["ome_conformance"]:
        statuses[item["status"]] = statuses.get(item["status"], 0) + 1
    print("Export metadata verifier")
    print(f"  OME conformance: {statuses}")
    print(f"  hard failures   : {len(report['hard_failures'])}")
    print(f"  warnings        : {len(report['warnings'])}")
    print(f"  ignored         : {len(report['ignored_differences'])}")
    if json_out:
        print(f"  JSON report     : {json_out}")
    else:
        print("  JSON report     : not written (--json-out not set)")
    print(f"  exit code       : {report['exit_code']}")

    if report["hard_failures"]:
        print("\nHard failures:")
        for item in report["hard_failures"][:20]:
            print(f"  [{item['code']}] {item['message']}")
    if report["warnings"]:
        print("\nWarnings:")
        for item in report["warnings"][:20]:
            print(f"  [{item['code']}] {item['message']}")


if __name__ == "__main__":
    raise SystemExit(main())
