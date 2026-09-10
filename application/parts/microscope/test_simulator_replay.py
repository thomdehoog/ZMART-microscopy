"""Optional numerical replay of saved LAS X captures; never operates the instrument."""

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest
import zarr
from zmart_viewer.projections import write_projection

from zmart_analysis.workflows.object_analysis.steps.detect_objects import segment_position


def test_saved_simulator_mips_match_originals_and_detector(tmp_path):
    evidence = os.environ.get("ZMART_SIMULATOR_RECORDS")
    if not evidence:
        pytest.skip("Set ZMART_SIMULATOR_RECORDS to a simulator probe's records.json")
    records = json.loads(Path(evidence).read_text(encoding="utf-8"))
    assert records
    for index, record in enumerate(records):
        source = Path(record["zarr_path"])
        originals = {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()
        }
        vendor_before = {
            p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in record["original_sha256"]
        }
        volume = np.asarray(zarr.open_group(str(source), mode="r")["0"])
        expected = volume.max(axis=2, keepdims=True)
        product = write_projection(source, tmp_path / f"capture-{index}.ome.zarr", "max")
        np.testing.assert_array_equal(zarr.open_group(str(product), mode="r")["0"][:], expected)
        detected = segment_position(
            str(source),
            {},
            z="max",
            method="fast",
            channels=[0],
            threshold=100,
            diameter=14,
            gpu=False,
        )
        np.testing.assert_array_equal(detected["image_2d"], expected[0, 0, 0])
        assert all(
            hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in originals.items()
        )
        assert all(
            hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest
            for p, digest in vendor_before.items()
        )
        # LAS X updates shared project XML on later captures; saved TIFFs are immutable.
        assert all(
            vendor_before[p] == digest
            for p, digest in record["original_sha256"].items()
            if Path(p).suffix.lower() in (".tif", ".tiff")
        )
