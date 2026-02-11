#!/usr/bin/env python3
"""
lasx_api_enrichment.py -- Enrich parsed LAS X templates with live API data.

Adds pixel size, image/tile size, zoom, scan speed, objective info, and
hardware details that can only be obtained from a running LAS X instance.
The parser alone does not compute these values.

This module now uses the generic :mod:`microscope_connector` interface.
You can pass either a :class:`MicroscopeConnector` instance (preferred) or
a raw Leica SDK client object (backward-compatible).

Usage
-----
    from vendors.lasx.parser import parse_template
    from vendors.lasx.api_enrichment import enrich_with_api_data

    data = parse_template(xml_path, lrp_path, rgn_path)

    # Preferred: let the enrichment create its own connection
    data = enrich_with_api_data(data)

    # Or pass an existing generic connector
    from microscope_connector import initialize_api
    api = initialize_api("lasx", client_name="PythonClient")
    data = enrich_with_api_data(data, connector=api)

    # Backward-compatible: pass a raw Leica SDK client object
    data = enrich_with_api_data(data, existing_client=raw_client)

Metadata
--------
    Author:  Adaptive Feedback Microscopy project
    Version: 1.1.0
    License: MIT
    Python:  >= 3.9
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# â”€â”€â”€ Import the generic connector framework â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Falls back gracefully if not available (e.g. no microscope SDK installed).

try:
    from microscope_connector import MicroscopeConnector, initialize_api
    CONNECTOR_AVAILABLE = True
except ImportError:
    MicroscopeConnector = None  # type: ignore[assignment, misc]
    CONNECTOR_AVAILABLE = False

__all__ = [
    "enrich_with_api_data",
    "get_job_pixel_size",
    "get_job_tile_size",
]

__version__ = "1.1.0"


# â”€â”€â”€ Helper Functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _parse_size_string(size_str: str) -> Optional[Dict[str, Any]]:
    """
    Parse a LAS X size string into numeric values and a unit.

    Handles common formats returned by the LAS X API:

    - ``"290.63 um x 290.63 um"``
    - ``"568.74 nm x 568.74 nm"``
    - ``"1.16 mm x 1.16 mm"``

    Also handles the mojibake ``\\u00c2\\u00b5m`` that sometimes appears
    for the micro-sign (u+00B5) due to double-encoded UTF-8.

    Parameters
    ----------
    size_str : str
        Raw size string from the API.

    Returns
    -------
    dict or None
        ``{"x": float, "y": float, "unit": str}`` where *unit* is one
        of ``"nm"``, ``"um"``, ``"mm"``.  Returns ``None`` on parse failure.
    """
    if not size_str:
        return None

    try:
        # Normalise known encoding artefacts to plain "um"
        size_str = size_str.replace("\u00c2\u00b5m", "um").replace("\u00b5m", "um")

        parts = size_str.lower().split("x")
        if len(parts) != 2:
            return None

        x_part = parts[0].strip()
        y_part = parts[1].strip()

        x_val = float("".join(c for c in x_part if c.isdigit() or c == "."))
        y_val = float("".join(c for c in y_part if c.isdigit() or c == "."))

        # Determine unit (check "nm" and "mm" before "um" to avoid substring match)
        lowered = size_str.lower()
        if "nm" in lowered:
            unit = "nm"
        elif "mm" in lowered:
            unit = "mm"
        else:
            unit = "um"

        return {"x": x_val, "y": y_val, "unit": unit}

    except Exception:
        return None


def _to_um(value: float, unit: str) -> float:
    """Convert a length value to micrometres."""
    if unit == "nm":
        return value / 1_000.0
    if unit == "mm":
        return value * 1_000.0
    return value  # already um


# â”€â”€â”€ Hardware Enrichment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _enrich_hardware_settings(
    parsed_hw: Dict[str, Any],
    api_hw: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Merge live API hardware data into the file-parsed hardware settings.

    The API is considered more authoritative for runtime values such as
    the current turret state, filter-wheel positions, and scan-speed limits.

    Parameters
    ----------
    parsed_hw : dict
        Hardware settings from the file parser.
    api_hw : dict
        Hardware info returned by :meth:`MicroscopeConnector.get_hardware_info`.

    Returns
    -------
    dict
        Enriched hardware settings with ``_api_enriched = True``.
    """
    enriched = parsed_hw.copy()

    # System identification
    if api_hw.get("SerialNumber"):
        enriched["SerialNumber"] = api_hw["SerialNumber"]
    if api_hw.get("SystemType"):
        enriched["SystemType"] = api_hw["SystemType"]

    # Scan speed limits
    if "ScanSpeed" in api_hw:
        api_scan = api_hw["ScanSpeed"]
        enriched["ScanSpeed"] = {
            "Max": api_scan.get("Max"),
            "Min": api_scan.get("Min"),
        }
        if "ResonantSpeed" in api_scan:
            enriched["ScanSpeed"]["ResonantSpeed"] = api_scan["ResonantSpeed"]

    # Microscope body and objectives (current turret state)
    if "Microscope" in api_hw and "objectives" in api_hw["Microscope"]:
        api_objectives = api_hw["Microscope"]["objectives"]
        if api_objectives:
            enriched["Microscope"] = enriched.get("Microscope", {}).copy()
            enriched["Microscope"]["objectives"] = []
            enriched["Microscope"]["name"] = api_hw["Microscope"].get("name", "")
            enriched["Microscope"]["AfcInstalled"] = api_hw["Microscope"].get(
                "AfcInstalled", False
            )
            for obj in api_objectives:
                enriched["Microscope"]["objectives"].append({
                    "Immersion": obj.get("immersion", ""),
                    "Magnification": obj.get("magnification"),
                    "NumericalAperture": obj.get("numericalAperture"),
                    "ObjectiveNumber": obj.get("objectiveNumber"),
                    "name": obj.get("name", ""),
                    "slotIndex": obj.get("slotIndex"),
                    "isMotCorr": obj.get("isMotCorr", False),
                })

    # Optical components â€” prefer live state from API
    if "FilterWheels" in api_hw:
        enriched["FilterWheels"] = api_hw["FilterWheels"]
    if "LightSources" in api_hw:
        enriched["LightSources"] = api_hw["LightSources"]
    if "LightSinks" in api_hw:
        enriched["LightSinks"] = api_hw["LightSinks"]

    enriched["_api_enriched"] = True
    return enriched


# â”€â”€â”€ Job Enrichment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _enrich_acquisition_job(
    parsed_job: Dict[str, Any],
    api_settings: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enrich a single acquisition job with live API settings.

    This is where the critical improvements happen: pixel size, image/tile
    size, zoom, scan speed, objective, and detector configuration are all
    sourced from the running LAS X instance.

    Parameters
    ----------
    parsed_job : dict
        Job data from the file parser.
    api_settings : dict
        Settings returned by :meth:`MicroscopeConnector.get_job_settings`.

    Returns
    -------
    dict
        Enriched job data with ``_api_enriched = True``.
    """
    enriched = parsed_job.copy()

    # Pixel size (nm or um -> always stored in um)
    if "pixelSize" in api_settings:
        pixel_info = _parse_size_string(api_settings["pixelSize"])
        if pixel_info:
            enriched["pixelSize_um"] = {
                "x": round(_to_um(pixel_info["x"], pixel_info["unit"]), 6),
                "y": round(_to_um(pixel_info["y"], pixel_info["unit"]), 6),
            }
            enriched["pixelSize_raw"] = api_settings["pixelSize"]

    # Image / tile size (um or mm -> stored in um)
    if "imageSize" in api_settings:
        size_info = _parse_size_string(api_settings["imageSize"])
        if size_info:
            x_um = _to_um(size_info["x"], size_info["unit"])
            y_um = _to_um(size_info["y"], size_info["unit"])
            enriched["tileSize_um"] = round((x_um + y_um) / 2.0, 4)
            enriched["imageSize_um"] = {
                "x": round(x_um, 4),
                "y": round(y_um, 4),
            }
            enriched["imageSize_raw"] = api_settings["imageSize"]

    # Format (resolution)
    if "format" in api_settings:
        enriched["format"] = api_settings["format"]

    # Zoom
    if "zoom" in api_settings:
        z = api_settings["zoom"]
        enriched["zoom"] = {
            "current": z.get("current"),
            "min": z.get("min"),
            "max": z.get("max"),
        }

    # Scan speed
    if "scanSpeed" in api_settings:
        s = api_settings["scanSpeed"]
        enriched["scanSpeed"] = {
            "value": s.get("value"),
            "unit": s.get("unit", "Hz"),
            "isResonant": s.get("isResonant", False),
        }

    # Scan mode, sequential mode, scan field rotation
    if "scanMode" in api_settings:
        enriched["scanMode"] = api_settings["scanMode"]
    if "sequentialMode" in api_settings:
        enriched["sequentialMode"] = api_settings["sequentialMode"]
    if "scanFieldRotation" in api_settings:
        enriched["scanFieldRotation"] = api_settings["scanFieldRotation"].get("value", 0.0)

    # Objective
    if "objective" in api_settings:
        obj = api_settings["objective"]
        enriched["objective"] = {
            "name": obj.get("name", ""),
            "magnification": obj.get("magnification"),
            "numericalAperture": obj.get("numericalAperture"),
            "immersion": obj.get("immersion", ""),
            "slotIndex": obj.get("slotIndex"),
        }
        if "motCorrPos" in obj:
            enriched["objective"]["motCorrPos"] = obj["motCorrPos"]

    # Active settings (detectors, lasers, etc.)
    if "activeSettings" in api_settings:
        enriched["activeSettings"] = api_settings["activeSettings"]

    # Autofocus state
    if "autoFocus" in api_settings:
        enriched["autoFocus"] = api_settings["autoFocus"]

    enriched["_api_enriched"] = True
    return enriched


# â”€â”€â”€ Connector Resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _resolve_connector(
    connector: Any = None,
    existing_client: Any = None,
    client_name: str = "ParserEnrichment",
    timeout: float = 15.0,
) -> tuple:
    """
    Resolve the various ways a connection can be provided.

    Returns ``(connector, owns_connector)`` where *owns_connector* is True
    if the caller should disconnect when done.

    Parameters
    ----------
    connector : MicroscopeConnector, optional
        Preferred: a ready-to-use generic connector.
    existing_client : Any, optional
        Backward-compatible: a raw vendor SDK client object.  Will be
        wrapped in a ``LasXConnector.from_existing_client()`` call.
    client_name : str
        Used only when creating a brand-new connection.
    timeout : float
        Timeout for API operations.

    Returns
    -------
    tuple[MicroscopeConnector, bool]
        The resolved connector and whether the caller owns it.

    Raises
    ------
    RuntimeError
        If no connection can be established.
    """
    # Case 1: Caller provided a ready MicroscopeConnector
    if connector is not None:
        return connector, False

    # Case 2: Backward-compatible raw client object
    if existing_client is not None:
        try:
            from .connector import LasXConnector
            wrapped = LasXConnector.from_existing_client(existing_client, timeout=timeout)
            return wrapped, False
        except ImportError:
            raise RuntimeError(
                "Cannot wrap existing_client: lasx_connector module not available."
            )

    # Case 3: Create a new connection via the generic factory
    try:
        new_connector = initialize_api(
            "lasx",
            client_name=client_name,
            timeout=timeout,
            auto_connect=True,
        )
        return new_connector, True
    except Exception as e:
        raise RuntimeError(
            f"Could not connect to microscope API. "
            f"The API connection is required to obtain pixel size and image size. "
            f"Detail: {e}"
        ) from e


# â”€â”€â”€ Main Enrichment Function â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def enrich_with_api_data(
    parsed_data: Dict[str, Any],
    connector: Any = None,
    *,
    existing_client: Any = None,
    client_name: str = "ParserEnrichment",
    timeout: float = 15.0,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Enrich parsed template data with live values from the microscope API.

    The API connection is **required** to obtain pixel size and image size;
    the file parser does not compute these.

    Parameters
    ----------
    parsed_data : dict
        Output from :func:`lasx_parser.parse_template`.
    connector : MicroscopeConnector, optional
        A connected :class:`MicroscopeConnector` instance (preferred).
        If provided, the caller retains ownership of the connection.
    existing_client : Any, optional
        **Backward-compatible**: a raw Leica SDK ``LasxApiClientPyModel``
        object.  Will be wrapped automatically.  Prefer *connector* for
        new code.
    client_name : str
        Name for a new API connection (used only when neither *connector*
        nor *existing_client* is provided).
    timeout : float
        Timeout in seconds for API operations.
    verbose : bool
        Print progress messages.

    Returns
    -------
    dict
        Enriched data with pixel sizes, tile sizes, hardware details, etc.

    Raises
    ------
    RuntimeError
        If the connector framework is not available or the connection fails.
    """
    if not CONNECTOR_AVAILABLE:
        raise RuntimeError(
            "microscope_connector module not available. "
            "Install it and the appropriate backend (e.g. lasx_connector) "
            "to obtain pixel size and image size from the API."
        )

    if verbose:
        print("  Attempting API enrichment...")

    # Resolve the connection
    conn, owns_connector = _resolve_connector(
        connector=connector,
        existing_client=existing_client,
        client_name=client_name,
        timeout=timeout,
    )

    if verbose:
        backend = getattr(conn, "backend_name", "unknown")
        if owns_connector:
            print(f"  OK: Connected to {backend!r} API")
        else:
            print(f"  OK: Using existing {backend!r} connection")

    try:
        enriched = parsed_data.copy()
        hw_enriched = False
        jobs_enriched: List[str] = []

        # â”€â”€ Hardware settings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        api_hw = conn.get_hardware_info()
        if api_hw:
            if verbose:
                print(f"  OK: Hardware info -- {api_hw.get('SystemType', 'Unknown')}")
            enriched["hardware_settings"] = _enrich_hardware_settings(
                enriched.get("hardware_settings", {}),
                api_hw,
            )
            hw_enriched = True

        # â”€â”€ Acquisition jobs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        api_jobs = conn.get_jobs_list()
        if api_jobs:
            if verbose:
                print(f"  OK: Found {len(api_jobs)} jobs in API")

            for api_job in api_jobs:
                job_name = api_job.get("Name")
                if not job_name:
                    continue

                # Only enrich jobs that exist in the parsed data
                if job_name in enriched.get("acquisition_jobs", {}):
                    api_settings = conn.get_job_settings(job_name)
                    if api_settings:
                        enriched["acquisition_jobs"][job_name] = _enrich_acquisition_job(
                            enriched["acquisition_jobs"][job_name],
                            api_settings,
                        )
                        jobs_enriched.append(job_name)

                        # Propagate tile size to visualisation data
                        tile_size = enriched["acquisition_jobs"][job_name].get("tileSize_um")
                        if tile_size is not None:
                            viz = enriched.get("visualization_data", {})
                            if "job_tile_sizes" in viz:
                                viz["job_tile_sizes"][job_name] = tile_size

                        if verbose:
                            job_data = enriched["acquisition_jobs"][job_name]
                            pixel = job_data.get("pixelSize_raw", "?")
                            tile = job_data.get("tileSize_um", "?")
                            print(f"    {job_name}: pixel={pixel}, tile={tile} um")

        # â”€â”€ Propagate tile sizes to position groups â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        positions = enriched.get("acquisition_positions", {})
        for gid, group in positions.items():
            jn = group.get("job_name")
            if jn and jn in enriched.get("acquisition_jobs", {}):
                api_tile_size = enriched["acquisition_jobs"][jn].get("tileSize_um")
                if api_tile_size is not None:
                    group["tile_size_um"] = api_tile_size
                    h = api_tile_size / 2.0
                    for pos in group.get("positions", []):
                        pos["bounding_box"] = {
                            "x_min_um": round(pos["x_um"] - h, 4),
                            "y_min_um": round(pos["y_um"] - h, 4),
                            "x_max_um": round(pos["x_um"] + h, 4),
                            "y_max_um": round(pos["y_um"] + h, 4),
                        }

        # â”€â”€ Warn about missing critical values â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if verbose:
            missing_pixel = [
                jn for jn, jd in enriched.get("acquisition_jobs", {}).items()
                if not jd.get("pixelSize") and not jd.get("pixelSize_raw")
            ]
            missing_image = [
                jn for jn, jd in enriched.get("acquisition_jobs", {}).items()
                if not jd.get("imageSize") and not jd.get("imageSize_raw")
            ]
            if missing_pixel:
                print(f"  WARNING: pixelSize not obtained from API for: {missing_pixel}")
            if missing_image:
                print(f"  WARNING: imageSize not obtained from API for: {missing_image}")

        # â”€â”€ Metadata â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        enriched["_api_enrichment"] = {
            "success": True,
            "backend": getattr(conn, "backend_name", "unknown"),
            "hardware_enriched": hw_enriched,
            "jobs_enriched": jobs_enriched,
        }

        if verbose:
            print("  OK: API enrichment complete")

        return enriched

    except Exception as e:
        raise RuntimeError(f"API enrichment failed: {e}") from e

    finally:
        if owns_connector and conn is not None:
            conn.disconnect()


# â”€â”€â”€ Convenience Functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def get_job_pixel_size(
    job_name: str,
    connector: Any = None,
    *,
    existing_client: Any = None,
    timeout: float = 15.0,
) -> Optional[Dict[str, float]]:
    """
    Get the current pixel size for a job directly from the API.

    Parameters
    ----------
    job_name : str
        Name of the acquisition job.
    connector : MicroscopeConnector, optional
        A connected connector to reuse.
    existing_client : Any, optional
        Backward-compatible raw SDK client object.
    timeout : float
        API timeout in seconds.

    Returns
    -------
    dict or None
        ``{"x": float, "y": float}`` in micrometres, or ``None``.
    """
    if not CONNECTOR_AVAILABLE:
        return None

    conn = None
    owns = False

    try:
        conn, owns = _resolve_connector(
            connector=connector,
            existing_client=existing_client,
            timeout=timeout,
        )

        settings = conn.get_job_settings(job_name)
        if settings and "pixelSize" in settings:
            info = _parse_size_string(settings["pixelSize"])
            if info:
                return {
                    "x": _to_um(info["x"], info["unit"]),
                    "y": _to_um(info["y"], info["unit"]),
                }
        return None

    except Exception:
        return None

    finally:
        if owns and conn is not None:
            conn.disconnect()


def get_job_tile_size(
    job_name: str,
    connector: Any = None,
    *,
    existing_client: Any = None,
    timeout: float = 15.0,
) -> Optional[float]:
    """
    Get the current tile/image size for a job directly from the API.

    Parameters
    ----------
    job_name : str
        Name of the acquisition job.
    connector : MicroscopeConnector, optional
        A connected connector to reuse.
    existing_client : Any, optional
        Backward-compatible raw SDK client object.
    timeout : float
        API timeout in seconds.

    Returns
    -------
    float or None
        Tile size in micrometres (average of x and y), or ``None``.
    """
    if not CONNECTOR_AVAILABLE:
        return None

    conn = None
    owns = False

    try:
        conn, owns = _resolve_connector(
            connector=connector,
            existing_client=existing_client,
            timeout=timeout,
        )

        settings = conn.get_job_settings(job_name)
        if settings and "imageSize" in settings:
            info = _parse_size_string(settings["imageSize"])
            if info:
                x_um = _to_um(info["x"], info["unit"])
                y_um = _to_um(info["y"], info["unit"])
                return (x_um + y_um) / 2.0
        return None

    except Exception:
        return None

    finally:
        if owns and conn is not None:
            conn.disconnect()


# â”€â”€â”€ CLI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


if __name__ == "__main__":
    print("LAS X API Enrichment Module")
    print("=" * 50)

    if not CONNECTOR_AVAILABLE:
        print("Warning: microscope_connector not available")
        print("  Make sure microscope_connector.py and lasx_connector.py")
        print("  are in your Python path.")
    else:
        try:
            api = initialize_api("lasx", auto_connect=True)
            print(f"\nConnected: {api!r}")

            jobs = api.get_jobs_list()
            if jobs:
                print("\n--- Testing API Queries ---")
                for job in jobs:
                    name = job.get("Name")
                    if not job.get("IsAutofocus"):
                        pixel = get_job_pixel_size(name, connector=api)
                        tile = get_job_tile_size(name, connector=api)
                        print(f"  {name}: pixel={pixel}, tile={tile}")

            api.disconnect()
            print("\nOK: Disconnected")

        except RuntimeError as e:
            print(f"\nWarning: {e}")
            print("  enrich_with_api_data() will raise if called without a connection.")
