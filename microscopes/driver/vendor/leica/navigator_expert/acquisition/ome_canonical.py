"""Generate canonical SMART OME metadata.

Vendor OME is parsed as input/provenance. The files written by ``save``
use this module as the output metadata contract.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from typing import Any

from .. import state_readers as _readers
from ..commands import settings as _core_settings
from ..runtime import utils as _core_utils
from . import ome as _ome
from .product import AcquisitionMetadata, ChannelMetadata, PlaneIndex

OME_NS = "http://www.openmicroscopy.org/Schemas/OME/2016-06"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
MICROMETER = "\u00b5m"
JOB_SETTINGS_READ_TIMEOUT_S = 1.0
JOB_SETTINGS_API_TIMEOUT_S = 0.25

ET.register_namespace("", OME_NS)
ET.register_namespace("xsi", XSI_NS)


def metadata_from_ome_xml(
    xml: bytes | str,
    *,
    size_x: int | None = None,
    size_y: int | None = None,
    size_t: int | None = None,
    size_z: int | None = None,
    size_c: int | None = None,
    pixel_type: str | None = None,
) -> AcquisitionMetadata:
    """Extract the minimal SMART metadata contract from vendor OME XML."""
    text = xml.decode("utf-8", errors="replace") if isinstance(xml, bytes) else xml
    root = ET.fromstring(text)
    pixels = _first_local(root, "Pixels")
    if pixels is None:
        raise RuntimeError("OME metadata has no Pixels element")

    channels = _channels_from_pixels(pixels, size_c=size_c)
    metadata = AcquisitionMetadata(
        size_x=_required_int(size_x, pixels, "SizeX"),
        size_y=_required_int(size_y, pixels, "SizeY"),
        size_t=_required_int(size_t, pixels, "SizeT"),
        size_z=_required_int(size_z, pixels, "SizeZ"),
        size_c=_required_int(size_c, pixels, "SizeC"),
        pixel_type=pixel_type or pixels.attrib.get("Type") or "uint16",
        physical_size_x_um=_physical_um(pixels, "X"),
        physical_size_y_um=_physical_um(pixels, "Y"),
        physical_size_z_um=_physical_um(pixels, "Z"),
        channels=tuple(channels),
    )
    return _ensure_channels(metadata)


def metadata_with_shape_and_grid(
    metadata: AcquisitionMetadata,
    *,
    size_x: int,
    size_y: int,
    size_t: int,
    size_z: int,
    size_c: int,
    pixel_type: str,
) -> AcquisitionMetadata:
    """Override vendor-declared dimensions with the collected source product."""
    return _ensure_channels(replace(
        metadata,
        size_x=size_x,
        size_y=size_y,
        size_t=size_t,
        size_z=size_z,
        size_c=size_c,
        pixel_type=pixel_type,
    ))


def metadata_with_job_physical_sizes(
    metadata: AcquisitionMetadata,
    client: Any,
    job_name: str,
    *,
    read_timeout_s: float = JOB_SETTINGS_READ_TIMEOUT_S,
) -> AcquisitionMetadata:
    """Prefer live job geometry for physical sizes, falling back to vendor OME.

    Vendor OME can be internally valid but semantically wrong. LAS X native
    AutoSave has been observed to write ``PhysicalSizeZ`` as range/sections
    instead of the OME inter-plane spacing. The job settings are the
    authoritative source for physical sampling when they can be read quickly.
    """
    settings = _read_job_settings_bounded(client, job_name, timeout_s=read_timeout_s)
    if not isinstance(settings, dict):
        return metadata

    x_um, y_um = _xy_pixel_sizes_from_job_settings(settings)
    z_um = _z_spacing_from_job_settings(settings)

    updates: dict[str, float | None] = {}
    if x_um is not _UNKNOWN:
        updates["physical_size_x_um"] = x_um
    if y_um is not _UNKNOWN:
        updates["physical_size_y_um"] = y_um
    if z_um is not _UNKNOWN:
        updates["physical_size_z_um"] = z_um
    if not updates:
        return metadata
    return replace(metadata, **updates)


def plane_xml(
    metadata: AcquisitionMetadata,
    *,
    index: PlaneIndex,
    filename: str,
    shape_yx: tuple[int, int],
) -> bytes:
    """Return valid single-plane OME XML for one canonical image file."""
    plane_meta = metadata_with_shape_and_grid(
        metadata,
        size_x=shape_yx[1],
        size_y=shape_yx[0],
        size_t=1,
        size_z=1,
        size_c=1,
        pixel_type=metadata.pixel_type,
    )
    plane_meta = replace(
        plane_meta,
        physical_size_x_um=None,
        physical_size_y_um=None,
        physical_size_z_um=None,
    )
    channel = _ascii_channel(metadata.channel(index.c))
    return _ome_xml(
        plane_meta,
        image_name=filename,
        channels=(replace(channel, index=0),),
        tiff_entries=[(0, 0, 0, filename)],
    )


def companion_xml(
    metadata: AcquisitionMetadata,
    *,
    image_name: str,
    plane_filenames: dict[PlaneIndex, str],
) -> bytes:
    """Return OME XML describing one canonical position/timepoint."""
    entries = [
        (0, idx.z, idx.c, filename)
        for idx, filename in sorted(plane_filenames.items())
    ]
    return _ome_xml(
        replace(metadata, size_t=1),
        image_name=image_name,
        channels=metadata.channels,
        tiff_entries=entries,
    )


def extract_embedded_ome_xml(tiff_src: Path) -> bytes:
    """Return raw OME-XML from TIFF ImageDescription tag 270."""
    try:
        data = tiff_src.read_bytes()
    except OSError as e:
        raise RuntimeError(
            f"Could not read embedded OME source {tiff_src}: {e}"
        ) from e

    xml_raw, _offset, _count, _entry_pos, endian_or_err = _ome._read_tiff_tag_270(
        data
    )
    if xml_raw is not None:
        return xml_raw

    try:
        import tifffile

        with tifffile.TiffFile(str(tiff_src)) as tif:
            description = tif.pages[0].description
    except Exception as e:
        raise RuntimeError(
            f"Could not extract embedded OME-XML from {tiff_src}: "
            f"{endian_or_err}; tifffile fallback failed: {e}"
        ) from e
    if not description or "<OME" not in description:
        raise RuntimeError(
            f"Could not extract embedded OME-XML from {tiff_src}: "
            f"{endian_or_err}; tifffile found no OME ImageDescription"
        )
    return description.encode("utf-8")


def pixel_type_from_dtype(dtype: str) -> str:
    return {
        "uint8": "uint8",
        "uint16": "uint16",
        "uint32": "uint32",
        "int8": "int8",
        "int16": "int16",
        "int32": "int32",
        "float32": "float",
        "float64": "double",
    }.get(dtype, "uint16")


def _ome_xml(
    metadata: AcquisitionMetadata,
    *,
    image_name: str,
    channels: tuple[ChannelMetadata, ...],
    tiff_entries: list[tuple[int, int, int, str]],
) -> bytes:
    root = ET.Element(
        _tag("OME"),
        {
            _tag("schemaLocation", XSI_NS): f"{OME_NS} {OME_NS}/ome.xsd",
        },
    )
    image = ET.SubElement(root, _tag("Image"), {"ID": "Image:0", "Name": image_name})
    pixels_attrs = {
        "ID": "Pixels:0",
        "DimensionOrder": "XYZCT",
        "Type": metadata.pixel_type,
        "SizeX": str(metadata.size_x),
        "SizeY": str(metadata.size_y),
        "SizeZ": str(metadata.size_z),
        "SizeC": str(metadata.size_c),
        "SizeT": str(metadata.size_t),
    }
    _add_physical(pixels_attrs, "X", metadata.physical_size_x_um)
    _add_physical(pixels_attrs, "Y", metadata.physical_size_y_um)
    _add_physical(pixels_attrs, "Z", metadata.physical_size_z_um)
    pixels = ET.SubElement(image, _tag("Pixels"), pixels_attrs)

    for channel in channels:
        ET.SubElement(pixels, _tag("Channel"), _channel_attrs(channel))
    for first_t, first_z, first_c, filename in tiff_entries:
        tiff_data = ET.SubElement(
            pixels,
            _tag("TiffData"),
            {
                "FirstT": str(first_t),
                "FirstZ": str(first_z),
                "FirstC": str(first_c),
                "IFD": "0",
                "PlaneCount": "1",
            },
        )
        uuid_el = ET.SubElement(tiff_data, _tag("UUID"), {"FileName": filename})
        uuid_el.text = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, filename))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _channel_attrs(channel: ChannelMetadata) -> dict[str, str]:
    attrs = {
        "ID": f"Channel:0:{channel.index}",
        "SamplesPerPixel": "1",
    }
    if channel.name:
        attrs["Name"] = channel.name
    if channel.color is not None:
        attrs["Color"] = str(channel.color)
    if channel.wavelength_nm is not None and channel.wavelength_nm > 0:
        attrs["EmissionWavelength"] = _num(channel.wavelength_nm)
        attrs["EmissionWavelengthUnit"] = "nm"
    return attrs


def _ascii_channel(channel: ChannelMetadata) -> ChannelMetadata:
    name = channel.name
    if name is not None:
        try:
            name.encode("ascii")
        except UnicodeEncodeError:
            name = None
    return replace(channel, name=name)


def _channels_from_pixels(
    pixels: ET.Element,
    *,
    size_c: int | None,
) -> list[ChannelMetadata]:
    channels = []
    for i, channel in enumerate(_children_local(pixels, "Channel")):
        wavelength = (
            _wavelength_nm(
                channel.attrib.get("EmissionWavelength"),
                channel.attrib.get("EmissionWavelengthUnit"),
            )
            or _wavelength_nm(
                channel.attrib.get("ExcitationWavelength"),
                channel.attrib.get("ExcitationWavelengthUnit"),
            )
        )
        channels.append(ChannelMetadata(
            index=i,
            name=channel.attrib.get("Name"),
            color=_int_or_none(channel.attrib.get("Color")),
            wavelength_nm=wavelength,
        ))
    count = size_c if size_c is not None else _int_or_none(pixels.attrib.get("SizeC"))
    if count is not None:
        channels_by_index = {c.index: c for c in channels}
        channels = [
            channels_by_index.get(i, ChannelMetadata(index=i))
            for i in range(count)
        ]
    return channels


def _ensure_channels(metadata: AcquisitionMetadata) -> AcquisitionMetadata:
    channels = {c.index: c for c in metadata.channels}
    return replace(
        metadata,
        channels=tuple(
            channels.get(i, ChannelMetadata(index=i))
            for i in range(metadata.size_c)
        ),
    )


_UNKNOWN = object()


def _read_job_settings_bounded(
    client: Any,
    job_name: str,
    *,
    timeout_s: float,
) -> dict | None:
    if client is None or not job_name:
        return None

    done = Event()
    result: dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["settings"] = _readers.get_job_settings(
                client,
                job_name,
                mode="api",
                timeout=JOB_SETTINGS_API_TIMEOUT_S,
                poll_interval=0.01,
                max_retries=1,
            )
        except Exception as e:  # pragma: no cover - defensive boundary
            result["error"] = e
        finally:
            done.set()

    Thread(target=_worker, daemon=True).start()
    if not done.wait(max(0.0, float(timeout_s))):
        return None
    settings = result.get("settings")
    return settings if isinstance(settings, dict) else None


def _xy_pixel_sizes_from_job_settings(
    settings: dict,
) -> tuple[float | object, float | object]:
    try:
        geom = _core_utils.parse_tile_geometry(settings)
    except Exception:
        return _UNKNOWN, _UNKNOWN
    x_um = _positive_float_or_unknown(geom.get("pixel_w_um"))
    y_um = _positive_float_or_unknown(geom.get("pixel_h_um"))
    return x_um, y_um


def _z_spacing_from_job_settings(settings: dict) -> float | None | object:
    stack = _stack_from_job_settings(settings)
    if not stack:
        return _UNKNOWN

    begin = _float_or_none(stack.get("begin"))
    end = _float_or_none(stack.get("end"))
    sections = _int_or_none(stack.get("sections"))
    if begin is None or end is None or sections is None:
        return _UNKNOWN
    if sections <= 1:
        return None
    return abs(end - begin) / float(sections - 1)


def _stack_from_job_settings(settings: dict) -> dict | None:
    stack = None
    try:
        normalized = _core_settings.make_changeable_copy(settings)
    except Exception:
        normalized = None
    if isinstance(normalized, dict) and isinstance(normalized.get("stack"), dict):
        stack = normalized["stack"]

    required = ("begin", "end", "sections")
    if not stack or any(stack.get(k) is None for k in required):
        raw_stack = settings.get("stack") if isinstance(settings, dict) else None
        if isinstance(raw_stack, dict):
            stack = {
                "begin": raw_stack.get("begin"),
                "end": raw_stack.get("end"),
                "sections": raw_stack.get("sections"),
            }
    return stack


def _add_physical(attrs: dict[str, str], axis: str, value_um: float | None) -> None:
    if value_um is None:
        return
    attrs[f"PhysicalSize{axis}"] = _num(value_um)
    attrs[f"PhysicalSize{axis}Unit"] = MICROMETER


def _physical_um(pixels: ET.Element, axis: str) -> float | None:
    value = _float_or_none(pixels.attrib.get(f"PhysicalSize{axis}"))
    if value is None:
        return None
    unit = pixels.attrib.get(f"PhysicalSize{axis}Unit")
    return _to_um(value, unit)


def _wavelength_nm(value: str | None, unit: str | None) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    unit_key = (unit or "nm").strip().lower()
    if unit_key in {"nm", "nanometer", "nanometers", "nanometre", "nanometres"}:
        return parsed
    if unit_key in {"um", MICROMETER, "micrometer", "micrometers"}:
        return parsed * 1000.0
    if unit_key == "m":
        return parsed * 1000000000.0
    return parsed


def _to_um(value: float, unit: str | None) -> float:
    unit_key = (unit or "um").strip().lower()
    if unit_key in {"um", MICROMETER, "micrometer", "micrometers"}:
        return value
    if unit_key in {"nm", "nanometer", "nanometers"}:
        return value * 0.001
    if unit_key == "m":
        return value * 1000000.0
    if unit_key == "mm":
        return value * 1000.0
    return value


def _required_int(override: int | None, pixels: ET.Element, name: str) -> int:
    if override is not None:
        return override
    value = _int_or_none(pixels.attrib.get(name))
    if value is None or value <= 0:
        raise RuntimeError(f"OME metadata missing positive {name}")
    return value


def _first_local(root: ET.Element, name: str) -> ET.Element | None:
    for element in root.iter():
        if _local(element.tag) == name:
            return element
    return None


def _children_local(root: ET.Element, name: str):
    for element in list(root):
        if _local(element.tag) == name:
            yield element


def _tag(name: str, ns: str = OME_NS) -> str:
    return f"{{{ns}}}{name}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _positive_float_or_unknown(value: Any) -> float | object:
    parsed = _float_or_none(value)
    if parsed is None or parsed <= 0:
        return _UNKNOWN
    return parsed


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num(value: float) -> str:
    return f"{value:.12g}"
