"""Tests for simulation-mode image hijacking.

Two surfaces under test:

  Guard (per-frame allowlist on the companion XML's SystemTypeName):
    - Refuses to overwrite when the value isn't exactly "SIMULATOR" --
      including missing element, unreadable XML, and a real-instrument
      identifier like "STELLARIS 8". This is the load-bearing safety
      property; a regression here would let cfg.simulate=True silently
      replace real-hardware pixels with mock content.

  OME-rewrite (overwrite path):
    - Tag 270 (ImageDescription, the OME-XML) survives the rewrite
      byte-for-byte. This is enforced inside hijack_frame; the test
      pins it by reading tag 270 from the rewritten file directly.
    - Provider shape/dtype mismatch raises RuntimeError (not
      NonSimulatorFrameError) so the loop records a per-tile failure
      and continues -- not a run-fatal abort.

Fixtures are split. Most tests synthesize their companion XML and
OME-TIFF at test time with tifffile -- those pin the local recipe
against the implementer's mental model of LAS X output. A small
committed XML at ``fixtures/lasx_simulator_companion.ome.xml``
preserves the structurally-relevant shape of real LAS X output
(declaration form, OME root namespaces, the CustomAttributes
wrapper in its distinct CA-2008-09 namespace, real OriginalMetadata
encoding) and is the durable regression catch for the
SystemTypeName allowlist parser -- see
TestReadSystemTypeAgainstRealLasxXml.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile
from pipeline._hijack import (
    NonSimulatorFrameError,
    _read_system_type,
    hijack_frame,
)
from pipeline._mock_provider import get_provider
from shared.output_layout import Naming, build_xml_name

# ─── Helpers ──────────────────────────────────────────────────────


_OME_DESC_TMPL = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
    '<Image ID="Image:0"><Pixels ID="Pixels:0" DimensionOrder="XYCZT" '
    'Type="uint16" SizeX="16" SizeY="16" SizeC="1" SizeZ="1" SizeT="1"/>'
    "</Image>"
    "<StructuredAnnotations>"
    '<XMLAnnotation ID="Annotation:0">'
    "<Value><OriginalMetadata>"
    "<Key>Data - Image - Attachment - SystemTypeName</Key>"
    "<Value>{system_type}</Value>"
    "</OriginalMetadata></Value>"
    "</XMLAnnotation>"
    "</StructuredAnnotations>"
    "</OME>"
)
# Attribute-encoded OriginalMetadata fragment matching real LAS X
# output. The hijack's allowlist parser (pipeline/_hijack.py) walks
# OriginalMetadata via ElementTree across any namespace, so this
# inline form is namespace-inherited from its parent OME element in
# the synthesized companion XML below.
_INLINE_ORIGINAL_META = (
    '<OriginalMetadata Name="Data - Image - Attachment - SystemTypeName" Value="{system_type}"/>'
)


def _make_companion_xml(system_type: str) -> bytes:
    """Build a minimal companion .ome.xml carrying SystemTypeName."""
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        + _INLINE_ORIGINAL_META.format(system_type=system_type)
        + "</OME>"
    )
    return body.encode("utf-8")


def _make_companion_xml_without_system_type() -> bytes:
    """Build a valid minimal companion .ome.xml without SystemTypeName."""
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        '<Image ID="Image:0"><Pixels ID="Pixels:0" DimensionOrder="XYCZT" '
        'Type="uint16" SizeX="16" SizeY="16" SizeC="1" SizeZ="1" '
        'SizeT="1"/></Image>'
        "</OME>"
    )
    return body.encode("utf-8")


def _make_image_description(system_type: str) -> str:
    """tag-270 OME-XML that includes the inline OriginalMetadata line so
    the hijack's per-frame guard could (in principle) read either the
    companion XML or the tag's XML. The guard only reads the companion;
    we include the line here for symmetry with the live LAS X output."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        '<Image ID="Image:0"><Pixels ID="Pixels:0" DimensionOrder="XYCZT" '
        'Type="uint16" SizeX="16" SizeY="16" SizeC="1" SizeZ="1" '
        'SizeT="1"/></Image>' + _INLINE_ORIGINAL_META.format(system_type=system_type) + "</OME>"
    )


def _write_ome_tiff(path: Path, arr: np.ndarray, desc: str) -> None:
    """Write an .ome.tiff with description=desc verbatim (ome=False).

    Matches the hijack's own rewrite recipe -- ome=False is essential
    so tifffile does not regenerate the description from the array.
    """
    tifffile.imwrite(path, arr, description=desc, ome=False, photometric="minisblack")


def _build_result(tmp_dir: Path, system_type: str, *, shape=(16, 16), dtype=np.uint16):
    """Build a (layout, result) pair for a fake one-tile acquisition.

    Returns a SimpleNamespace shaped like the workflow-selected
    single-plane result (image, image_path, naming) plus a layout stub
    whose metadata_dir() points at tmp_dir/metadata so the companion XML
    resolves there.
    """
    naming = Naming(
        acquisition_type="overview-scan",
        hash6="abcdef",
        g=0,
        p=0,
    )
    metadata_dir = tmp_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    xml_path = metadata_dir / build_xml_name(naming)
    xml_path.write_bytes(_make_companion_xml(system_type))

    image_path = tmp_dir / "frame.ome.tiff"
    arr = np.full(shape, 100, dtype=dtype)
    _write_ome_tiff(image_path, arr, _make_image_description(system_type))

    layout = SimpleNamespace(
        metadata_dir=lambda kind: metadata_dir,
    )
    result = SimpleNamespace(
        image=arr,
        image_path=image_path,
        naming=naming,
    )
    return layout, result


def _constant_provider(value: int):
    """Provider that always returns a constant-valued array of the
    requested shape and dtype. Lets tests assert "pixels changed" by
    comparing against the original constant."""

    def _p(shape, dtype, *, naming):
        return np.full(shape, value, dtype=dtype)

    return _p


def _write_native_autosave_vendor_system_type(
    metadata_dir: Path,
    system_type: str,
    *,
    name: str = "metadata_Overview001.xlif",
) -> Path:
    vendor_dir = metadata_dir / "vendor" / "lasx_native_autosave"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    path = vendor_dir / name
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Metadata>"
        f'<Attachment Name="HardwareSetting" SystemTypeName="{system_type}">'
        '<ATLConfocalSettingDefinition SystemSerialNumber="TEST" />'
        "</Attachment>"
        "</Metadata>",
        encoding="utf-8",
    )
    return path


# ─── Guard: positive allowlist ────────────────────────────────────


class TestGuardRejectsNonSimulator:
    def test_rejects_real_instrument(self, tmp_path):
        """A real-hardware companion XML must abort the hijack with
        NonSimulatorFrameError -- the load-bearing safety property."""
        layout, result = _build_result(tmp_path, "STELLARIS 8")
        with pytest.raises(NonSimulatorFrameError):
            hijack_frame(
                result, kind="overview-scan", layout=layout, provider=_constant_provider(42)
            )

    def test_rejects_missing_systemtype_element(self, tmp_path):
        """A companion XML without the SystemTypeName OriginalMetadata
        element -- unknown system -- must abort."""
        layout, result = _build_result(tmp_path, "SIMULATOR")
        # Overwrite the companion XML with one that lacks the
        # SystemTypeName element entirely.
        metadata_dir = layout.metadata_dir("overview-scan")
        xml_path = metadata_dir / build_xml_name(result.naming)
        xml_path.write_bytes(b'<?xml version="1.0"?><OME></OME>')
        with pytest.raises(NonSimulatorFrameError):
            hijack_frame(
                result, kind="overview-scan", layout=layout, provider=_constant_provider(42)
            )

    def test_rejects_missing_xml_file(self, tmp_path):
        """An unreadable companion XML (file does not exist on disk)
        must abort -- never silently overwrite."""
        layout, result = _build_result(tmp_path, "SIMULATOR")
        metadata_dir = layout.metadata_dir("overview-scan")
        xml_path = metadata_dir / build_xml_name(result.naming)
        xml_path.unlink()
        with pytest.raises(NonSimulatorFrameError):
            hijack_frame(
                result, kind="overview-scan", layout=layout, provider=_constant_provider(42)
            )

    def test_rejects_empty_string_systemtype(self, tmp_path):
        """An empty SystemTypeName value is neither 'SIMULATOR' nor a
        recognized real instrument -- abort to be safe."""
        layout, result = _build_result(tmp_path, "")
        with pytest.raises(NonSimulatorFrameError):
            hijack_frame(
                result, kind="overview-scan", layout=layout, provider=_constant_provider(42)
            )

    def test_does_not_overwrite_when_rejected(self, tmp_path):
        """A rejected guard MUST leave the original .ome.tiff bytes
        intact -- not even a partial overwrite is acceptable."""
        layout, result = _build_result(tmp_path, "STELLARIS 8")
        original_bytes = result.image_path.read_bytes()
        with pytest.raises(NonSimulatorFrameError):
            hijack_frame(
                result, kind="overview-scan", layout=layout, provider=_constant_provider(42)
            )
        assert result.image_path.read_bytes() == original_bytes


class TestNativeAutoSaveVendorFallback:
    def test_accepts_vendor_simulator_when_companion_lacks_systemtype(
        self,
        tmp_path,
    ):
        """Native AutoSave canonical XML lacks Leica OriginalMetadata, but
        copied vendor XLIF can still prove the frame is from the simulator."""
        layout, result = _build_result(tmp_path, "SIMULATOR")
        metadata_dir = layout.metadata_dir("overview-scan")
        xml_path = metadata_dir / build_xml_name(result.naming)
        xml_path.write_bytes(_make_companion_xml_without_system_type())
        _write_native_autosave_vendor_system_type(metadata_dir, "SIMULATOR")

        hijack_frame(
            result,
            kind="overview-scan",
            layout=layout,
            provider=_constant_provider(42),
        )

        new_arr = tifffile.imread(result.image_path)
        assert new_arr.min() == 42
        assert new_arr.max() == 42

    def test_rejects_vendor_real_instrument_when_companion_lacks_systemtype(
        self,
        tmp_path,
    ):
        layout, result = _build_result(tmp_path, "SIMULATOR")
        metadata_dir = layout.metadata_dir("overview-scan")
        xml_path = metadata_dir / build_xml_name(result.naming)
        xml_path.write_bytes(_make_companion_xml_without_system_type())
        _write_native_autosave_vendor_system_type(metadata_dir, "STELLARIS 8")
        original_bytes = result.image_path.read_bytes()

        with pytest.raises(NonSimulatorFrameError):
            hijack_frame(
                result,
                kind="overview-scan",
                layout=layout,
                provider=_constant_provider(42),
            )
        assert result.image_path.read_bytes() == original_bytes

    def test_rejects_conflicting_vendor_system_types(self, tmp_path):
        layout, result = _build_result(tmp_path, "SIMULATOR")
        metadata_dir = layout.metadata_dir("overview-scan")
        xml_path = metadata_dir / build_xml_name(result.naming)
        xml_path.write_bytes(_make_companion_xml_without_system_type())
        _write_native_autosave_vendor_system_type(
            metadata_dir,
            "SIMULATOR",
            name="metadata_A.xlif",
        )
        _write_native_autosave_vendor_system_type(
            metadata_dir,
            "STELLARIS 8",
            name="metadata_B.xlif",
        )
        original_bytes = result.image_path.read_bytes()

        with pytest.raises(NonSimulatorFrameError):
            hijack_frame(
                result,
                kind="overview-scan",
                layout=layout,
                provider=_constant_provider(42),
            )
        assert result.image_path.read_bytes() == original_bytes


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
        """A malformed XML must yield None (not crash). Belt-and-
        suspenders: the LAS X writer should never produce malformed
        XML, but the parser must fail closed -- a crash here would
        propagate as an uncaught exception out of the acquisition
        loop, which would record as a tile failure instead of a
        deliberate NonSimulatorFrameError."""
        xml = tmp_path / "bad.xml"
        xml.write_bytes(b"<OME><not-closed>")
        assert _read_system_type(xml) is None

    def test_attribute_order_value_before_name(self, tmp_path):
        """ET-based parser is attribute-order-independent (the previous
        regex required Name="..." to appear before Value="..." on the
        same element). LAS X's current writer happens to emit Name
        first, but the parser must not depend on that."""
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
        """The real LAS X envelope wraps OriginalMetadata in a
        CustomAttributes block whose default xmlns is the CA-2008-09
        schema -- distinct from the OME root namespace. A namespace-
        unaware parser (e.g. ``root.iter("OriginalMetadata")``) would
        miss them entirely. The ``{*}`` wildcard match must find them."""
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
    """Pin the allowlist parser against a real (sanitized) LAS X
    simulator companion XML. Without this fixture the parser was only
    validated against synthesized minimal XML -- a representation that
    happened to match the implementer's mental model of LAS X output,
    not LAS X itself.

    The fixture preserves the structurally-relevant shape:

      - the LAS X XML declaration (`standalone="no"`) and the long
        OME-XML warning comment
      - the OME root with all eight namespace declarations LAS X emits
      - the SemanticTypeDefinitions stub
      - the <CustomAttributes xmlns="...CA-2008-09"> wrapper -- the
        DIFFERENT namespace from the OME root that broke a naive
        non-namespace-aware parser implementation
      - a handful of real OriginalMetadata entries, including the
        SystemTypeName="SIMULATOR" one

    Operator-identifiable values (UUID, paths, names) are sanitized.
    """

    def test_allowlist_passes_on_real_simulator_xml(self):
        xml = _FIXTURES_DIR / "lasx_simulator_companion.ome.xml"
        assert xml.exists(), (
            f"fixture missing: {xml}. The real-LAS-X regression test "
            f"depends on this file being committed alongside the test."
        )
        assert _read_system_type(xml) == "SIMULATOR"


# ─── Overwrite: tag-270 preservation + provider validation ────────


class TestHijackOverwrite:
    def test_pixels_replaced_on_simulator(self, tmp_path):
        layout, result = _build_result(tmp_path, "SIMULATOR")
        # Original pixel value is 100 (see _build_result).
        assert tifffile.imread(result.image_path).max() == 100

        hijack_frame(result, kind="overview-scan", layout=layout, provider=_constant_provider(42))

        # Pixels overwritten with the provider's constant.
        new_arr = tifffile.imread(result.image_path)
        assert new_arr.min() == 42
        assert new_arr.max() == 42
        assert new_arr.shape == (16, 16)

    def test_tag_270_preserved_byte_for_byte(self, tmp_path):
        layout, result = _build_result(tmp_path, "SIMULATOR")
        with tifffile.TiffFile(result.image_path) as tif:
            desc_before = tif.pages[0].description

        hijack_frame(result, kind="overview-scan", layout=layout, provider=_constant_provider(42))

        with tifffile.TiffFile(result.image_path) as tif:
            desc_after = tif.pages[0].description
        # The OriginalMetadata SystemTypeName line is what the guard
        # would re-read. A silent regeneration that dropped it would
        # break the next run's guard -- pin byte-equality.
        assert desc_after == desc_before
        assert 'Value="SIMULATOR"' in desc_after

    def test_provider_shape_mismatch_is_runtime_error(self, tmp_path):
        """A provider that returns the wrong shape must raise
        RuntimeError -- NOT NonSimulatorFrameError -- so the
        acquisition loop records a per-tile failure and continues
        rather than hard-aborting the run."""
        layout, result = _build_result(tmp_path, "SIMULATOR")

        def bad_shape_provider(shape, dtype, *, naming):
            return np.zeros((shape[0] + 1, shape[1]), dtype=dtype)

        with pytest.raises(RuntimeError) as exc_info:
            hijack_frame(result, kind="overview-scan", layout=layout, provider=bad_shape_provider)
        assert not isinstance(exc_info.value, NonSimulatorFrameError)
        # Original file must remain intact -- the overwrite is atomic.
        assert tifffile.imread(result.image_path).max() == 100

    def test_provider_dtype_mismatch_is_runtime_error(self, tmp_path):
        layout, result = _build_result(tmp_path, "SIMULATOR")

        def bad_dtype_provider(shape, dtype, *, naming):
            return np.zeros(shape, dtype=np.uint8)  # not uint16

        with pytest.raises(RuntimeError) as exc_info:
            hijack_frame(result, kind="overview-scan", layout=layout, provider=bad_dtype_provider)
        assert not isinstance(exc_info.value, NonSimulatorFrameError)

    def test_multi_plane_saved_array_fails_loudly_not_silently(self, tmp_path):
        """Only single-plane single-channel saved frames are supported.
        A multi-plane saved frame must raise a clearly-labelled
        RuntimeError (per-tile path, recorded in hijack_failures and
        the loop continues), NOT a NonSimulatorFrameError (which would
        hard-abort the entire run).

        The previous implementation only had a generic shape-mismatch
        error: the 2-D mock provider would return shape (H, W) for a
        saved shape of (Z, H, W), and every tile in a multi-plane run
        would silently land in hijack_failures with an opaque mismatch
        message. This pins the explicit early reject + the operator-
        facing 'multi-plane unsupported' message."""
        # Build a (planes=2, H=16, W=16) saved frame on a SIMULATOR
        # companion so the allowlist passes and the 2D check is the
        # only thing that can fire.
        layout, result = _build_result(
            tmp_path,
            "SIMULATOR",
            shape=(2, 16, 16),
            dtype=np.uint16,
        )
        with pytest.raises(RuntimeError) as exc_info:
            hijack_frame(
                result, kind="overview-scan", layout=layout, provider=_constant_provider(42)
            )
        # Must NOT be NonSimulatorFrameError -- a multi-plane frame is
        # an unsupported scope, not a safety violation.
        assert not isinstance(exc_info.value, NonSimulatorFrameError)
        # Message must name the scope explicitly so the operator knows
        # what to do (extend the mock provider) instead of seeing a
        # mysterious shape error.
        assert "multi-plane" in str(exc_info.value).lower()


# ─── Mock provider unit ───────────────────────────────────────────


class TestMockProvider:
    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            get_provider("no-such-provider")

    def test_human_mitosis_matches_shape_and_dtype(self):
        provider = get_provider("skimage_human_mitosis")
        naming = Naming(
            acquisition_type="overview-scan",
            hash6="abcdef",
            g=2,
            p=5,
        )
        out = provider((128, 96), np.uint16, naming=naming)
        assert out.shape == (128, 96)
        assert out.dtype == np.uint16

    def test_human_mitosis_deterministic_per_naming(self):
        """Same (g, p) -> same content; different (g, p) -> different
        content. A deterministic mapping is what makes the mock
        tile-stitchable and reproducible across runs."""
        provider = get_provider("skimage_human_mitosis")
        n_a = Naming(acquisition_type="overview-scan", hash6="abcdef", g=0, p=0)
        n_b = Naming(acquisition_type="overview-scan", hash6="abcdef", g=0, p=1)

        a1 = provider((128, 128), np.uint16, naming=n_a)
        a2 = provider((128, 128), np.uint16, naming=n_a)
        b1 = provider((128, 128), np.uint16, naming=n_b)
        assert np.array_equal(a1, a2)
        assert not np.array_equal(a1, b1)
