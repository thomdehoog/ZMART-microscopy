"""Unit tests for the simulation-mode hijack helpers.

``test_sim_hijack.py`` covers the happy paths of :func:`hijack_records` (it
overwrites a simulator plane, preserves the OME description, counts planes,
and refuses a real-instrument or missing-metadata frame). This file pins the
pieces those end-to-end tests do not, all still on the surviving surface:

  - the ``SystemTypeName`` allowlist parser (:func:`_read_system_type`),
    including against a committed real (sanitized) LAS X companion XML;
  - the guard's remaining refusal cases -- a missing element, an empty value,
    and conflicting vendor metadata;
  - the overwrite's own failure cases -- a provider returning the wrong shape
    or dtype, and a multi-plane saved frame -- which must raise a per-frame
    ``RuntimeError`` (not the run-fatal ``NonSimulatorFrameError``) and leave
    the original file intact;
  - the mock provider lookup (:func:`get_provider`).

The committed fixture at ``fixtures/lasx_simulator_companion.ome.xml`` preserves
the structurally-relevant shape of real LAS X output (the XML declaration, the
OME root namespaces, and the ``CustomAttributes`` wrapper in its distinct
CA-2008-09 namespace) so the parser is checked against LAS X itself, not only
against synthesized minimal XML.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile
from workflow._hijack import NonSimulatorFrameError, _read_system_type, hijack_records
from workflow._mock_provider import get_provider

# ─── Helpers ──────────────────────────────────────────────────────

_OME_DESC = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
    '<Image ID="Image:0"><Pixels ID="Pixels:0" DimensionOrder="XYCZT" '
    'Type="uint16" SizeX="16" SizeY="16" SizeC="1" SizeZ="1" SizeT="1"/></Image>'
    '<OriginalMetadata Name="Data - Image - Attachment - SystemTypeName" '
    'Value="SIMULATOR"/>'
    "</OME>"
)


def _make_companion_xml(system_type: str) -> bytes:
    """Build a minimal companion XML carrying an inline SystemTypeName."""
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        f'<OriginalMetadata Name="Data - Image - Attachment - SystemTypeName" '
        f'Value="{system_type}"/>'
        "</OME>"
    )
    return body.encode("utf-8")


def _write_vendor_system_type(acq_dir: Path, system_type: str, *, name="metadata_A.xlif") -> None:
    vendor_dir = acq_dir / "vendor" / "lasx_native_autosave"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    (vendor_dir / name).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Metadata>"
        f'<Attachment Name="HardwareSetting" SystemTypeName="{system_type}">'
        '<ATLConfocalSettingDefinition SystemSerialNumber="TEST" />'
        "</Attachment></Metadata>",
        encoding="utf-8",
    )


def _saved_plane(
    tmp_path: Path,
    *,
    acquisition_type="overview",
    position_label="g00000-p00001",
    system_type: str | None = "SIMULATOR",
    fill: int = 100,
    shape=(16, 16),
    dtype=np.uint16,
) -> Path:
    """Write one flat canonical plane inside its acquisition dir + vendor XLIF.

    ``hijack_records`` derives the acquisition dir as the image's own parent,
    so the plane lives inside it. Returns the image path.
    """
    acq_dir = tmp_path / acquisition_type
    acq_dir.mkdir(parents=True, exist_ok=True)
    if system_type is not None:
        _write_vendor_system_type(acq_dir, system_type)
    filename = f"{acquisition_type}_abcdef_{position_label}_T000000_C00_Z00000.ome.tiff"
    path = acq_dir / filename
    arr = np.full(shape, fill, dtype=dtype)
    tifffile.imwrite(path, arr, description=_OME_DESC, ome=False, photometric="minisblack")
    return path


def _constant_provider(value: int):
    def _p(shape, dtype, *, naming):
        return np.full(shape, value, dtype=dtype)

    return _p


# ─── Guard: remaining refusal cases ───────────────────────────────


class TestGuardRefusalCases:
    def test_rejects_missing_systemtype_element(self, tmp_path):
        """Vendor metadata without any SystemTypeName attribute is an unknown
        system and must abort, leaving the file untouched."""
        img = _saved_plane(tmp_path, system_type="SIMULATOR")
        vendor_dir = img.parent / "vendor" / "lasx_native_autosave"
        for p in vendor_dir.glob("*.xlif"):
            p.write_text('<?xml version="1.0"?><Metadata></Metadata>', encoding="utf-8")
        original = img.read_bytes()

        with pytest.raises(NonSimulatorFrameError):
            hijack_records([{"images": [str(img)]}], _constant_provider(42))
        assert img.read_bytes() == original

    def test_rejects_empty_string_systemtype(self, tmp_path):
        """An empty SystemTypeName is neither 'SIMULATOR' nor a recognized real
        instrument -- refuse to be safe."""
        img = _saved_plane(tmp_path, system_type="")
        original = img.read_bytes()

        with pytest.raises(NonSimulatorFrameError):
            hijack_records([{"images": [str(img)]}], _constant_provider(42))
        assert img.read_bytes() == original

    def test_rejects_conflicting_vendor_system_types(self, tmp_path):
        """Two vendor files disagreeing on the system type is ambiguous, so the
        read fails closed and the frame is never overwritten."""
        img = _saved_plane(tmp_path, system_type="SIMULATOR", position_label="g00000-p00002")
        _write_vendor_system_type(img.parent, "STELLARIS 8", name="metadata_B.xlif")
        original = img.read_bytes()

        with pytest.raises(NonSimulatorFrameError):
            hijack_records([{"images": [str(img)]}], _constant_provider(42))
        assert img.read_bytes() == original


# ─── Overwrite: provider + shape failures are per-frame RuntimeErrors ──


class TestOverwriteFailures:
    def test_provider_shape_mismatch_is_runtime_error(self, tmp_path):
        """A provider returning the wrong shape must raise RuntimeError -- NOT
        NonSimulatorFrameError -- so the loop records a per-tile failure and
        continues rather than hard-aborting, and the file stays intact."""
        img = _saved_plane(tmp_path)

        def bad_shape_provider(shape, dtype, *, naming):
            return np.zeros((shape[0] + 1, shape[1]), dtype=dtype)

        with pytest.raises(RuntimeError) as exc_info:
            hijack_records([{"images": [str(img)]}], bad_shape_provider)
        assert not isinstance(exc_info.value, NonSimulatorFrameError)
        assert tifffile.imread(img).max() == 100

    def test_provider_dtype_mismatch_is_runtime_error(self, tmp_path):
        img = _saved_plane(tmp_path)

        def bad_dtype_provider(shape, dtype, *, naming):
            return np.zeros(shape, dtype=np.uint8)  # not uint16

        with pytest.raises(RuntimeError) as exc_info:
            hijack_records([{"images": [str(img)]}], bad_dtype_provider)
        assert not isinstance(exc_info.value, NonSimulatorFrameError)

    def test_multi_plane_saved_array_fails_loudly_not_silently(self, tmp_path):
        """Only single-plane single-channel saved frames are supported. A
        multi-plane saved frame must raise a clearly-labelled RuntimeError (a
        per-tile failure), NOT a NonSimulatorFrameError that would abort the
        whole run."""
        img = _saved_plane(tmp_path, shape=(2, 16, 16))

        with pytest.raises(RuntimeError) as exc_info:
            hijack_records([{"images": [str(img)]}], _constant_provider(42))
        assert not isinstance(exc_info.value, NonSimulatorFrameError)
        assert "multi-plane" in str(exc_info.value).lower()


# ─── _read_system_type unit ───────────────────────────────────────


class TestReadSystemType:
    def test_returns_simulator_value(self, tmp_path):
        xml = tmp_path / "x.xml"
        xml.write_bytes(_make_companion_xml("SIMULATOR"))
        assert _read_system_type(xml) == "SIMULATOR"

    def test_returns_real_instrument(self, tmp_path):
        xml = tmp_path / "x.xml"
        xml.write_bytes(_make_companion_xml("STELLARIS 8"))
        assert _read_system_type(xml) == "STELLARIS 8"

    def test_returns_none_on_missing_element(self, tmp_path):
        xml = tmp_path / "x.xml"
        xml.write_bytes(b"<OME></OME>")
        assert _read_system_type(xml) is None

    def test_returns_none_on_missing_file(self, tmp_path):
        assert _read_system_type(tmp_path / "nope.xml") is None

    def test_returns_none_on_unparseable_xml(self, tmp_path):
        """Malformed XML must yield None, not crash: the parser fails closed so
        the loop sees a deliberate NonSimulatorFrameError, never an uncaught
        exception mislabelled as a tile failure."""
        xml = tmp_path / "bad.xml"
        xml.write_bytes(b"<OME><not-closed>")
        assert _read_system_type(xml) is None

    def test_attribute_order_value_before_name(self, tmp_path):
        """The parser is attribute-order-independent (an earlier regex required
        Name before Value on the same element)."""
        xml = tmp_path / "reversed.xml"
        xml.write_bytes(
            b'<?xml version="1.0"?>'
            b'<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-09">'
            b'<OriginalMetadata Value="SIMULATOR" '
            b'Name="Data - Image - Attachment - SystemTypeName" />'
            b"</OME>"
        )
        assert _read_system_type(xml) == "SIMULATOR"

    def test_finds_element_in_distinct_child_namespace(self, tmp_path):
        """LAS X wraps OriginalMetadata in a CustomAttributes block whose default
        namespace differs from the OME root; the ``{*}`` wildcard must still
        find it where a namespace-unaware lookup would miss it."""
        xml = tmp_path / "ca_nested.xml"
        xml.write_bytes(
            b'<?xml version="1.0"?>'
            b'<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2008-09">'
            b"<CustomAttributes "
            b'xmlns="http://www.openmicroscopy.org/Schemas/CA/2008-09">'
            b"<OriginalMetadata "
            b'Name="Data - Image - Attachment - SystemTypeName" '
            b'Value="SIMULATOR" />'
            b"</CustomAttributes>"
            b"</OME>"
        )
        assert _read_system_type(xml) == "SIMULATOR"


# ─── Real LAS X simulator XML fixture ─────────────────────────────


_FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestReadSystemTypeAgainstRealLasxXml:
    """Pin the allowlist parser against a real (sanitized) LAS X simulator
    companion XML, so it is validated against LAS X itself and not only against
    synthesized minimal XML."""

    def test_allowlist_passes_on_real_simulator_xml(self):
        xml = _FIXTURES_DIR / "lasx_simulator_companion.ome.xml"
        assert xml.exists(), (
            f"fixture missing: {xml}. The real-LAS-X regression test "
            f"depends on this file being committed alongside the test."
        )
        assert _read_system_type(xml) == "SIMULATOR"


# ─── Mock provider unit ───────────────────────────────────────────


class TestMockProvider:
    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            get_provider("no-such-provider")

    def test_human_mitosis_matches_shape_and_dtype(self):
        pytest.importorskip("skimage")
        provider = get_provider("skimage_human_mitosis")
        naming = SimpleNamespace(
            acquisition_type="overview-scan",
            hash6="abcdef",
            position_label="g00002-p00005",
        )
        out = provider((128, 96), np.uint16, naming=naming)
        assert out.shape == (128, 96)
        assert out.dtype == np.uint16

    def test_human_mitosis_deterministic_per_naming(self):
        """Same (g, p) -> same content; different (g, p) -> different content.
        A deterministic mapping is what makes the mock tile-stitchable and
        reproducible across runs."""
        pytest.importorskip("skimage")
        provider = get_provider("skimage_human_mitosis")
        n_a = SimpleNamespace(
            acquisition_type="overview-scan", hash6="abcdef", position_label="g00000-p00000"
        )
        n_b = SimpleNamespace(
            acquisition_type="overview-scan", hash6="abcdef", position_label="g00000-p00001"
        )

        a1 = provider((128, 128), np.uint16, naming=n_a)
        a2 = provider((128, 128), np.uint16, naming=n_a)
        b1 = provider((128, 128), np.uint16, naming=n_b)
        assert np.array_equal(a1, a2)
        assert not np.array_equal(a1, b1)
