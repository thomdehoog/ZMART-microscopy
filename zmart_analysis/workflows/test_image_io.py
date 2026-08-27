"""
Unit tests for image_io.

Builds synthetic OME-Zarr positions in both NGFF 0.4 (Zarr v2) and NGFF
0.5 (Zarr v3, sharded) and checks that planes, metadata and physical
coordinates come back the same either way.

Run from an environment with ngio installed:
    python test_image_io.py
    python -m pytest test_image_io.py -v
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _image_io import is_ome_zarr, is_tiff, load_plane, to_physical  # noqa: E402


PIXEL_SIZE = 0.325
Z_SPACING = 1.0
ORIGIN_YX = (1000.0, 2000.0)
SHAPE = (2, 2, 5, 64, 64)  # t, c, z, y, x


def _make_position(path, ngff_version, array, shards=None):
    """Write one synthetic OME-Zarr position."""
    import ngio

    ngio.create_ome_zarr_from_array(
        path,
        array,
        pixelsize=PIXEL_SIZE,
        z_spacing=Z_SPACING,
        axes_names=("t", "c", "z", "y", "x"),
        channels_meta=["DAPI", "GFP"],
        translation=(0.0, 0.0, 0.0, ORIGIN_YX[0], ORIGIN_YX[1]),
        levels=2,
        chunks=(1, 1, 1, 32, 32),
        shards=shards,
        ngff_version=ngff_version,
        overwrite=True,
    )


def _make_ome_tiff(path, array, tile=(32, 32), positions=True):
    """Write the same content as _make_position, as a single OME-TIFF."""
    import tifffile

    n_planes = array.shape[0] * array.shape[1] * array.shape[2]
    metadata = {
        "axes": "TCZYX",
        "PhysicalSizeX": PIXEL_SIZE, "PhysicalSizeXUnit": "\u00b5m",
        "PhysicalSizeY": PIXEL_SIZE, "PhysicalSizeYUnit": "\u00b5m",
        "PhysicalSizeZ": Z_SPACING,
        "Channel": {"Name": ["DAPI", "GFP"]},
    }
    if positions:
        metadata["Plane"] = {
            "PositionY": [ORIGIN_YX[0]] * n_planes,
            "PositionX": [ORIGIN_YX[1]] * n_planes,
            "PositionYUnit": ["\u00b5m"] * n_planes,
            "PositionXUnit": ["\u00b5m"] * n_planes,
        }

    tifffile.imwrite(path, array, photometric="minisblack", tile=tile,
                     metadata=metadata)


class OmeZarrTestCase(unittest.TestCase):
    """Shared fixtures: one position per NGFF version."""

    @classmethod
    def setUpClass(cls):
        try:
            import ngio  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("ngio is not installed")

        cls.tmpdir = Path(tempfile.mkdtemp(prefix="image_io_test_"))
        rng = np.random.default_rng(0)
        cls.array = rng.integers(0, 4096, SHAPE, dtype=np.uint16)

        cls.stores = {
            "0.4": cls.tmpdir / "position_v04.zarr",
            "0.5": cls.tmpdir / "position_v05.zarr",
        }
        _make_position(cls.stores["0.4"], "0.4", cls.array)
        # NGFF 0.5 is Zarr v3, so it can also carry shards.
        _make_position(cls.stores["0.5"], "0.5", cls.array,
                       shards=(1, 1, 1, 64, 64))

        cls.tiff = cls.tmpdir / "position.ome.tif"
        _make_ome_tiff(cls.tiff, cls.array)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)


class TestDetection(OmeZarrTestCase):
    """Tests for is_ome_zarr()."""

    def test_detects_v04_store(self):
        # NGFF 0.4 keeps its metadata in .zattrs
        self.assertTrue((self.stores["0.4"] / ".zattrs").exists())
        self.assertTrue(is_ome_zarr(self.stores["0.4"]))

    def test_detects_v05_store(self):
        # NGFF 0.5 keeps its metadata in zarr.json
        self.assertTrue((self.stores["0.5"] / "zarr.json").exists())
        self.assertTrue(is_ome_zarr(self.stores["0.5"]))

    def test_rejects_plain_file(self):
        plain = self.tmpdir / "image.tif"
        plain.write_bytes(b"not a zarr")
        self.assertFalse(is_ome_zarr(plain))

    def test_remote_url_by_suffix(self):
        self.assertTrue(is_ome_zarr("s3://bucket/plate.zarr/B/03/0"))
        self.assertFalse(is_ome_zarr("s3://bucket/image.tif"))


class TestPlaneSelection(OmeZarrTestCase):
    """Both NGFF versions must yield identical planes."""

    def test_default_takes_middle_z(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                plane, meta = load_plane(store)
                np.testing.assert_array_equal(plane, self.array[0, 0, 2])
                self.assertEqual(meta["index"], {"t": 0, "z": 2})

    def test_explicit_indices(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                plane, meta = load_plane(store, t=1, c=1, z=4)
                np.testing.assert_array_equal(plane, self.array[1, 1, 4])
                self.assertEqual(meta["index"], {"t": 1, "z": 4})
                self.assertEqual(meta["channel"], 1)

    def test_channel_by_name(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                plane, meta = load_plane(store, c="GFP", z=0)
                np.testing.assert_array_equal(plane, self.array[0, 1, 0])
                self.assertEqual(meta["channel"], 1)
                self.assertEqual(meta["channel_name"], "GFP")

    def test_max_projection(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                plane, meta = load_plane(store, z="max")
                np.testing.assert_array_equal(plane, self.array[0, 0].max(axis=0))
                self.assertEqual(meta["projection"], "max")
                self.assertNotIn("z", meta["index"])

    def test_projection_keeps_dtype(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                for mode in ("max", "mean"):
                    plane, _ = load_plane(store, z=mode)
                    self.assertEqual(plane.dtype, self.array.dtype)

    def test_plane_is_always_2d(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                for z in (0, "mid", "max"):
                    plane, _ = load_plane(store, z=z)
                    self.assertEqual(plane.ndim, 2)

    def test_lower_resolution_level(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                plane, meta = load_plane(store, level=1)
                self.assertEqual(plane.shape, (32, 32))
                self.assertEqual(meta["level"], "1")
                self.assertAlmostEqual(meta["pixel_size"]["x"], PIXEL_SIZE * 2)

    def test_out_of_range_selection_raises(self):
        import ngio

        for version, store in self.stores.items():
            for kwargs in ({"t": 99}, {"z": 99}, {"c": 99}, {"c": "NOPE"},
                           {"level": 9}):
                with self.subTest(ngff=version, **kwargs):
                    with self.assertRaises((ngio.NgioValueError,
                                            ngio.NgioValidationError,
                                            ValueError)):
                        load_plane(store, **kwargs)

    def test_unknown_z_selection_names_the_options(self):
        with self.assertRaises(ValueError) as caught:
            load_plane(self.stores["0.5"], z="sum")
        self.assertIn("mid", str(caught.exception))
        self.assertIn("max", str(caught.exception))

    def test_mean_projection_values(self):
        plane, _ = load_plane(self.stores["0.5"], z="mean")
        expected = np.rint(self.array[0, 0].mean(axis=0)).astype(self.array.dtype)
        np.testing.assert_array_equal(plane, expected)


class TestMetadata(OmeZarrTestCase):
    """Metadata is normalized across NGFF versions."""

    def test_reports_ngff_version(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                _, meta = load_plane(store)
                self.assertEqual(meta["ngff_version"], version)
                self.assertEqual(meta["format"], "ome-zarr")

    def test_reports_axes_and_shape(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                _, meta = load_plane(store)
                self.assertEqual(meta["axes"], ["t", "c", "z", "y", "x"])
                self.assertEqual(meta["shape"], list(SHAPE))

    def test_reports_pixel_size_and_origin(self):
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                _, meta = load_plane(store)
                self.assertAlmostEqual(meta["pixel_size"]["y"], PIXEL_SIZE)
                self.assertAlmostEqual(meta["pixel_size"]["z"], Z_SPACING)
                self.assertAlmostEqual(meta["origin"]["y"], ORIGIN_YX[0])
                self.assertAlmostEqual(meta["origin"]["x"], ORIGIN_YX[1])
                self.assertEqual(meta["space_unit"], "micrometer")


class TestPhysicalCoordinates(OmeZarrTestCase):
    """Pixel centroids map to stage coordinates."""

    def test_scale_and_offset_applied(self):
        _, meta = load_plane(self.stores["0.5"])
        physical = to_physical(10.0, 20.0, meta)
        self.assertAlmostEqual(physical["y"], 10.0 * PIXEL_SIZE + ORIGIN_YX[0])
        self.assertAlmostEqual(physical["x"], 20.0 * PIXEL_SIZE + ORIGIN_YX[1])
        self.assertEqual(physical["unit"], "micrometer")

    def test_uses_the_loaded_level(self):
        _, meta = load_plane(self.stores["0.5"], level=1)
        physical = to_physical(10.0, 20.0, meta)
        self.assertAlmostEqual(physical["y"], 10.0 * PIXEL_SIZE * 2 + ORIGIN_YX[0])

    def test_none_without_spatial_metadata(self):
        self.assertIsNone(to_physical(1.0, 2.0, {"pixel_size": {}}))


class TestLazyReading(OmeZarrTestCase):
    """Only the chunks backing the requested plane are fetched."""

    METADATA_KEYS = (".zarray", ".zattrs", ".zgroup", ".zmetadata", "zarr.json")

    def _count_chunk_reads(self, **kwargs):
        """Number of distinct chunk or shard objects touched by one load."""
        from unittest.mock import patch
        from zarr.storage import LocalStore

        original = LocalStore.get
        reads = set()

        async def counting_get(self, key, *args, **kw):
            # A sharded read hits one object with several byte ranges,
            # so count distinct keys rather than calls.
            if key.rsplit("/", 1)[-1] not in counting_get.METADATA_KEYS:
                reads.add(key)
            return await original(self, key, *args, **kw)

        counting_get.METADATA_KEYS = self.METADATA_KEYS

        with patch.object(LocalStore, "get", counting_get):
            load_plane(**kwargs)

        return len(reads)

    def test_single_plane_reads_one_chunk_per_tile(self):
        # Level 0 holds 2*2*5 z-planes of 2x2 chunks: 80 chunks in all.
        # One plane is 4 of them, or a single shard when sharded.
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                reads = self._count_chunk_reads(source=store, t=0, c=0, z=2)
                self.assertGreater(reads, 0, "the read counter matched nothing")
                self.assertLessEqual(
                    reads, 4,
                    f"read {reads} chunks for a single plane, expected <= 4",
                )

    def test_projection_reads_only_its_own_stack(self):
        # A z-projection needs the 5 z planes of one (t, c), not all 20.
        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                reads = self._count_chunk_reads(source=store, t=0, c=0, z="max")
                self.assertGreater(reads, 0, "the read counter matched nothing")
                self.assertLessEqual(
                    reads, 20,
                    f"read {reads} chunks for one z-stack of 5 planes, "
                    f"expected <= 20 of the 80 in the array",
                )


    def test_reads_far_less_than_the_whole_array(self):
        import ngio

        for version, store in self.stores.items():
            with self.subTest(ngff=version):
                plane_reads = self._count_chunk_reads(source=store, z=2)

                from unittest.mock import patch
                from zarr.storage import LocalStore

                original = LocalStore.get
                everything = set()

                async def counting_get(self, key, *args, **kw):
                    if key.rsplit("/", 1)[-1] not in TestLazyReading.METADATA_KEYS:
                        everything.add(key)
                    return await original(self, key, *args, **kw)

                with patch.object(LocalStore, "get", counting_get):
                    container = ngio.open_ome_zarr_container(str(store), mode="r")
                    container.get_image().get_as_numpy()

                self.assertLess(
                    plane_reads, len(everything),
                    f"one plane read {plane_reads} objects, the whole array "
                    f"reads {len(everything)}",
                )


class TestAxisVariants(OmeZarrTestCase):
    """Positions are not always 5D: t, c and z may all be absent."""

    def _write(self, name, axes, shape):
        import ngio

        store = self.tmpdir / name
        array = np.random.default_rng(1).integers(0, 4096, shape, dtype=np.uint16)
        ngio.create_ome_zarr_from_array(
            store, array, pixelsize=PIXEL_SIZE, axes_names=axes,
            ngff_version="0.5", levels=1, overwrite=True,
        )
        return store, array

    def test_czyx(self):
        store, array = self._write("czyx.zarr", ("c", "z", "y", "x"), (2, 3, 32, 32))
        plane, meta = load_plane(store, c=1)
        np.testing.assert_array_equal(plane, array[1, 1])
        self.assertEqual(meta["index"], {"z": 1})

    def test_zyx(self):
        store, array = self._write("zyx.zarr", ("z", "y", "x"), (3, 32, 32))
        plane, _ = load_plane(store, z="max")
        np.testing.assert_array_equal(plane, array.max(axis=0))

    def test_channel_name_ignored_without_a_channel_axis(self):
        # The same YAML runs over positions that do not all have channels.
        store, array = self._write("zyx_nochan.zarr", ("z", "y", "x"), (3, 32, 32))
        plane, meta = load_plane(store, c="DAPI", z=0)
        np.testing.assert_array_equal(plane, array[0])
        self.assertIsNone(meta["channel"])
        self.assertIsNone(meta["channel_name"])

    def test_projection_not_claimed_without_a_z_axis(self):
        store, array = self._write("tyx_noz.zarr", ("t", "y", "x"), (2, 32, 32))
        plane, meta = load_plane(store, z="max")
        np.testing.assert_array_equal(plane, array[0])
        self.assertIsNone(meta["projection"])

    def test_yx(self):
        store, array = self._write("yx.zarr", ("y", "x"), (32, 32))
        plane, meta = load_plane(store)
        np.testing.assert_array_equal(plane, array)
        self.assertEqual(meta["index"], {})

    def test_tyx_without_z(self):
        store, array = self._write("tyx.zarr", ("t", "y", "x"), (4, 32, 32))
        plane, meta = load_plane(store, t=3)
        np.testing.assert_array_equal(plane, array[3])
        self.assertEqual(meta["index"], {"t": 3})


class TestOtherInputs(unittest.TestCase):
    """Image files and skimage samples still work."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="image_io_files_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_reads_a_tiff(self):
        from skimage.io import imsave

        path = self.tmpdir / "plane.tif"
        image = np.random.default_rng(2).integers(0, 255, (16, 16), dtype=np.uint8)
        imsave(path, image, check_contrast=False)

        plane, meta = load_plane(path)
        np.testing.assert_array_equal(plane, image)
        self.assertEqual(meta["format"], "tiff")

    def test_image_file_has_no_physical_coordinates(self):
        from skimage.io import imsave

        path = self.tmpdir / "plane2.tif"
        imsave(path, np.zeros((8, 8), dtype=np.uint8), check_contrast=False)

        _, meta = load_plane(path)
        self.assertEqual(meta["pixel_size"], {})
        self.assertIsNone(to_physical(1.0, 2.0, meta))

    def test_reads_a_plane_from_a_plain_stack(self):
        import tifffile

        path = self.tmpdir / "stack.tif"
        stack = np.random.default_rng(3).integers(0, 255, (3, 8, 8),
                                                 dtype=np.uint8)
        tifffile.imwrite(path, stack, photometric="minisblack",
                         metadata={"axes": "ZYX"})

        plane, meta = load_plane(path, z=2)
        np.testing.assert_array_equal(plane, stack[2])
        self.assertEqual(meta["index"], {"z": 2})

    def test_rejects_a_multi_dimensional_png(self):
        from skimage.io import imsave

        path = self.tmpdir / "rgb.png"
        imsave(path, np.zeros((8, 8, 3), dtype=np.uint8), check_contrast=False)

        with self.assertRaises(ValueError):
            load_plane(path)

    def test_unknown_skimage_sample(self):
        with self.assertRaises(ValueError):
            load_plane("skimage.not_a_dataset")

    def test_skimage_attribute_that_is_not_a_loader(self):
        with self.assertRaises(ValueError):
            load_plane("skimage.__file__")

    def test_rejects_an_rgb_file(self):
        from skimage.io import imsave

        path = self.tmpdir / "rgb.tif"
        imsave(path, np.zeros((8, 8, 3), dtype=np.uint8), check_contrast=False)

        with self.assertRaises(ValueError) as caught:
            load_plane(path)
        self.assertIn("RGB", str(caught.exception))


class TestPlateInput(OmeZarrTestCase):
    """A plate is not a position, and the error should say so."""

    def test_plate_error_lists_positions(self):
        import ngio

        store = self.tmpdir / "plate.zarr"
        ngio.create_empty_plate(
            store, name="plate",
            images=[ngio.ImageInWellPath(row="B", column="3", path="0")],
            ngff_version="0.5",
        )

        with self.assertRaises(ValueError) as caught:
            load_plane(store)

        message = str(caught.exception)
        self.assertIn("not a position", message)
        self.assertIn("B/03/0", message)


class TestWellInput(OmeZarrTestCase):
    """A well is not a position either."""

    def test_well_error_lists_positions(self):
        import ngio

        store = self.tmpdir / "well.zarr"
        well = ngio.create_empty_well(store, ngff_version="0.5", overwrite=True)
        for path in ("0", "1"):
            well.add_image(path)

        with self.assertRaises(ValueError) as caught:
            load_plane(store)

        message = str(caught.exception)
        self.assertIn("not a position", message)
        self.assertIn("Positions: 0, 1", message)

    def test_unrelated_zarr_group_keeps_its_own_error(self):
        import zarr

        store = self.tmpdir / "plain.zarr"
        zarr.create_group(store=str(store))

        with self.assertRaises(Exception) as caught:
            load_plane(store)
        self.assertNotIn("not a position", str(caught.exception))


class TestOmeTiff(OmeZarrTestCase):
    """The OME-TIFF path honours the same contract as OME-Zarr."""

    def test_detects_tiff(self):
        self.assertTrue(is_tiff(self.tiff))
        self.assertTrue(is_tiff("/data/position.OME.TIFF"))
        self.assertFalse(is_tiff("/data/position.zarr"))
        self.assertFalse(is_ome_zarr(self.tiff))

    def test_default_takes_middle_z(self):
        plane, meta = load_plane(self.tiff)
        np.testing.assert_array_equal(plane, self.array[0, 0, 2])
        self.assertEqual(meta["format"], "ome-tiff")
        self.assertEqual(meta["index"], {"t": 0, "z": 2})
        self.assertEqual(meta["channel"], 0)

    def test_explicit_indices(self):
        plane, _ = load_plane(self.tiff, t=1, c=1, z=4)
        np.testing.assert_array_equal(plane, self.array[1, 1, 4])

    def test_channel_by_name(self):
        plane, meta = load_plane(self.tiff, c="GFP", z=0)
        np.testing.assert_array_equal(plane, self.array[0, 1, 0])
        self.assertEqual(meta["channel_name"], "GFP")

    def test_projections(self):
        plane, meta = load_plane(self.tiff, z="max")
        np.testing.assert_array_equal(plane, self.array[0, 0].max(axis=0))
        self.assertEqual(meta["projection"], "max")

        plane, _ = load_plane(self.tiff, z="mean")
        expected = np.rint(self.array[0, 0].mean(axis=0)).astype(self.array.dtype)
        np.testing.assert_array_equal(plane, expected)

    def test_reports_pixel_size_and_origin(self):
        _, meta = load_plane(self.tiff)
        self.assertAlmostEqual(meta["pixel_size"]["y"], PIXEL_SIZE)
        self.assertAlmostEqual(meta["pixel_size"]["z"], Z_SPACING)
        self.assertAlmostEqual(meta["origin"]["y"], ORIGIN_YX[0])
        self.assertAlmostEqual(meta["origin"]["x"], ORIGIN_YX[1])
        self.assertEqual(meta["space_unit"], "micrometer")

    def test_physical_coordinates(self):
        _, meta = load_plane(self.tiff)
        physical = to_physical(10.0, 20.0, meta)
        self.assertAlmostEqual(physical["y"], 10.0 * PIXEL_SIZE + ORIGIN_YX[0])
        self.assertAlmostEqual(physical["x"], 20.0 * PIXEL_SIZE + ORIGIN_YX[1])

    def test_out_of_range_selection_raises(self):
        for kwargs in ({"t": 99}, {"z": 99}, {"c": 99}, {"c": "NOPE"},
                       {"level": 9}):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    load_plane(self.tiff, **kwargs)

    def test_pyramid_levels(self):
        import tifffile

        path = self.tmpdir / "pyramid.ome.tif"
        full = self.array[0, 0, 0]
        with tifffile.TiffWriter(path) as writer:
            writer.write(full, subifds=1, tile=(32, 32))
            writer.write(full[::2, ::2], subfiletype=1, tile=(32, 32))

        plane, meta = load_plane(path, level=1)
        self.assertEqual(plane.shape, (32, 32))
        np.testing.assert_array_equal(plane, full[::2, ::2])
        self.assertEqual(meta["level"], "1")

    def test_pyramid_pixel_size_follows_the_level(self):
        import tifffile

        path = self.tmpdir / "pyramid_meta.ome.tif"
        full = self.array[0, 0, 0]
        with tifffile.TiffWriter(path) as writer:
            writer.write(full, subifds=1, tile=(32, 32), photometric="minisblack",
                         metadata={"axes": "YX", "PhysicalSizeX": PIXEL_SIZE,
                                   "PhysicalSizeXUnit": "\u00b5m",
                                   "PhysicalSizeY": PIXEL_SIZE,
                                   "PhysicalSizeYUnit": "\u00b5m"})
            writer.write(full[::2, ::2], subfiletype=1, tile=(32, 32))

        _, meta = load_plane(path, level=1)
        self.assertAlmostEqual(meta["pixel_size"]["x"], PIXEL_SIZE * 2)

    def test_plain_tiff_without_ome_metadata(self):
        import tifffile

        path = self.tmpdir / "plain.tif"
        tifffile.imwrite(path, self.array[0, 0, 0])

        plane, meta = load_plane(path)
        np.testing.assert_array_equal(plane, self.array[0, 0, 0])
        self.assertEqual(meta["format"], "tiff")
        self.assertEqual(meta["pixel_size"], {})
        self.assertIsNone(to_physical(1.0, 2.0, meta))

    def test_rgb_tiff_is_refused(self):
        import tifffile

        path = self.tmpdir / "rgb.tif"
        tifffile.imwrite(path, np.zeros((16, 16, 3), dtype=np.uint8),
                         photometric="rgb")

        with self.assertRaises(ValueError) as caught:
            load_plane(path)
        self.assertIn("RGB", str(caught.exception))


class TestMultiPositionTiff(OmeZarrTestCase):
    """One TIFF can hold several positions; the caller says which."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        import tifffile

        cls.multi = cls.tmpdir / "two_positions.ome.tif"
        cls.first = cls.array[0, 0]
        cls.second = cls.array[1, 1]
        with tifffile.TiffWriter(cls.multi) as writer:
            writer.write(cls.first, metadata={"axes": "ZYX", "Name": "pos0"})
            writer.write(cls.second, metadata={"axes": "ZYX", "Name": "pos1"})

    def test_ambiguous_file_names_the_positions(self):
        with self.assertRaises(ValueError) as caught:
            load_plane(self.multi)

        message = str(caught.exception)
        self.assertIn("2 positions", message)
        self.assertIn("pos1", message)

    def test_select_by_index(self):
        plane, _ = load_plane(self.multi, series=1, z=0)
        np.testing.assert_array_equal(plane, self.second[0])

    def test_select_by_name(self):
        plane, _ = load_plane(self.multi, series="pos0", z=0)
        np.testing.assert_array_equal(plane, self.first[0])

    def test_unknown_position(self):
        with self.assertRaises(ValueError):
            load_plane(self.multi, series="pos9")


class TestFormatParity(OmeZarrTestCase):
    """
    The principle: a step must not care which format it was given.

    The same content is written as OME-Zarr 0.4, OME-Zarr 0.5 and
    OME-TIFF, and every selection must come back identical.
    """

    def _sources(self):
        return {"ngff 0.4": self.stores["0.4"],
                "ngff 0.5": self.stores["0.5"],
                "ome-tiff": self.tiff}

    def test_every_selection_agrees(self):
        selections = (
            {}, {"z": 0}, {"z": 4}, {"t": 1}, {"c": 1}, {"c": "GFP"},
            {"t": 1, "c": "GFP", "z": 3}, {"z": "max"}, {"z": "mean"},
            {"t": 1, "z": "max"},
        )

        for selection in selections:
            planes = {name: load_plane(source, **selection)[0]
                      for name, source in self._sources().items()}
            reference_name, reference = next(iter(planes.items()))

            for name, plane in planes.items():
                with self.subTest(selection=selection, format=name):
                    np.testing.assert_array_equal(
                        plane, reference,
                        f"{name} disagrees with {reference_name} "
                        f"for {selection}",
                    )

    def test_metadata_agrees(self):
        shared = ("axes", "shape", "dtype", "index", "projection", "channel",
                  "channel_name", "space_unit")

        results = {name: load_plane(source, t=1, c="GFP", z=3)[1]
                   for name, source in self._sources().items()}
        reference = results["ngff 0.5"]

        for name, meta in results.items():
            with self.subTest(format=name):
                for key in shared:
                    self.assertEqual(meta[key], reference[key], f"{key} differs")
                self.assertAlmostEqual(meta["pixel_size"]["x"],
                                       reference["pixel_size"]["x"])
                self.assertAlmostEqual(meta["origin"]["y"],
                                       reference["origin"]["y"])

    def test_physical_coordinates_agree(self):
        for name, source in self._sources().items():
            with self.subTest(format=name):
                _, meta = load_plane(source)
                physical = to_physical(12.0, 34.0, meta)
                self.assertAlmostEqual(physical["y"],
                                       12.0 * PIXEL_SIZE + ORIGIN_YX[0])
                self.assertAlmostEqual(physical["x"],
                                       34.0 * PIXEL_SIZE + ORIGIN_YX[1])
                self.assertEqual(physical["unit"], "micrometer")

class TestTiffLazyReading(OmeZarrTestCase):
    """TIFF reads decode tiles, not whole files."""

    def test_single_plane_decodes_few_tiles(self):
        from unittest.mock import patch
        from tifffile.zarr import ZarrTiffStore

        original = ZarrTiffStore.get
        reads = []

        async def counting_get(self, key, *args, **kwargs):
            if not str(key).endswith((".zarray", ".zgroup", ".zattrs",
                                      "zarr.json")):
                reads.append(key)
            return await original(self, key, *args, **kwargs)

        with patch.object(ZarrTiffStore, "get", counting_get):
            load_plane(self.tiff, t=0, c=0, z=2)
            plane_reads = len(reads)

            reads.clear()
            load_plane(self.tiff, t=0, c=0, z="max")
            stack_reads = len(reads)

        # 64x64 in 32x32 tiles is 4 per plane, and the array holds 20 planes.
        self.assertGreater(plane_reads, 0, "the read counter matched nothing")
        self.assertLessEqual(plane_reads, 4)
        self.assertLessEqual(stack_reads, 20)
        self.assertGreater(stack_reads, plane_reads)


class TestUnitReconciliation(unittest.TestCase):
    """
    Writers do not agree on units. A pixel size in one unit and a stage
    position in another has to come out as one coherent coordinate.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="image_io_units_"))
        cls.array = np.random.default_rng(5).integers(0, 255, (4, 4),
                                                     dtype=np.uint8)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _write(self, name, pixel_unit, pixel_size, position_unit, position):
        import tifffile

        path = self.tmpdir / name
        tifffile.imwrite(
            path, self.array, photometric="minisblack",
            metadata={
                "axes": "YX",
                "PhysicalSizeX": pixel_size, "PhysicalSizeXUnit": pixel_unit,
                "PhysicalSizeY": pixel_size, "PhysicalSizeYUnit": pixel_unit,
                "Plane": {"PositionX": [position], "PositionY": [position],
                          "PositionXUnit": [position_unit],
                          "PositionYUnit": [position_unit]},
            })
        return path

    def test_no_recorded_position_means_the_image_corner(self):
        import tifffile

        path = self.tmpdir / "no_position.ome.tif"
        tifffile.imwrite(path, self.array, photometric="minisblack",
                         metadata={"axes": "YX", "PhysicalSizeX": 0.5,
                                   "PhysicalSizeXUnit": "\u00b5m",
                                   "PhysicalSizeY": 0.5,
                                   "PhysicalSizeYUnit": "\u00b5m"})

        _, meta = load_plane(path)
        self.assertEqual(meta["origin"], {})
        physical = to_physical(10.0, 10.0, meta)
        self.assertAlmostEqual(physical["x"], 5.0)

    def test_position_in_millimeters_with_pixels_in_micrometers(self):
        path = self._write("mixed.ome.tif", "\u00b5m", 0.5, "mm", 2.0)

        _, meta = load_plane(path)
        self.assertEqual(meta["space_unit"], "micrometer")
        # 2 mm is 2000 um, and the coordinate has to be in one unit
        self.assertAlmostEqual(meta["origin"]["x"], 2000.0)

        physical = to_physical(10.0, 10.0, meta)
        self.assertAlmostEqual(physical["x"], 10.0 * 0.5 + 2000.0)

    def test_pixel_size_in_nanometers(self):
        path = self._write("nano.ome.tif", "nm", 325.0, "nm", 1000.0)

        _, meta = load_plane(path)
        self.assertEqual(meta["space_unit"], "nanometer")
        self.assertAlmostEqual(meta["pixel_size"]["x"], 325.0)
        self.assertAlmostEqual(meta["origin"]["x"], 1000.0)

    def test_unconvertible_position_unit_is_dropped(self):
        # Better no coordinate than a wrong one sent to a microscope.
        path = self._write("reference.ome.tif", "\u00b5m", 0.5,
                           "reference frame", 5.0)

        _, meta = load_plane(path)
        self.assertEqual(meta["pixel_size"]["x"], 0.5)
        self.assertIsNone(meta["origin"])
        self.assertIsNone(to_physical(1.0, 2.0, meta))


class TestForeignWriters(unittest.TestCase):
    """
    Stores written by hand rather than by ngio.

    Every other fixture here is written by the same library that reads it
    back, which cannot catch assumptions about how a writer names things.
    These are written straight through zarr, the way a converter would.
    """

    AXES = [
        {"name": "t", "type": "time", "unit": "second"},
        {"name": "c", "type": "channel"},
        {"name": "z", "type": "space", "unit": "micrometer"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]

    @classmethod
    def setUpClass(cls):
        try:
            import zarr  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("zarr is not installed")

        cls.tmpdir = Path(tempfile.mkdtemp(prefix="image_io_foreign_"))
        cls.array = np.random.default_rng(4).integers(
            0, 4096, (1, 2, 3, 32, 32), dtype=np.uint16)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    @classmethod
    def _datasets(cls, paths_and_scales):
        return [
            {"path": path,
             "coordinateTransformations": [
                 {"type": "scale", "scale": [1, 1, 1, scale, scale]},
                 {"type": "translation",
                  "translation": [0, 0, 0, ORIGIN_YX[0], ORIGIN_YX[1]]}]}
            for path, scale in paths_and_scales
        ]

    def _write_v04(self, name, dataset_names=("s0", "s1")):
        """NGFF 0.4: Zarr v2, metadata in .zattrs, no omero block."""
        import zarr

        store = self.tmpdir / name
        group = zarr.create_group(store=str(store), zarr_format=2)

        for path, data in ((dataset_names[0], self.array),
                           (dataset_names[1], self.array[:, :, :, ::2, ::2])):
            array = group.create_array(name=path, shape=data.shape,
                                       dtype=data.dtype, chunks=(1, 1, 1, 16, 16))
            array[:] = data

        group.attrs["multiscales"] = [{
            "version": "0.4", "name": "position", "axes": self.AXES,
            "datasets": self._datasets(
                ((dataset_names[0], PIXEL_SIZE), (dataset_names[1], PIXEL_SIZE * 2))),
        }]
        return store

    def _write_v05(self, name):
        """NGFF 0.5: Zarr v3, metadata under the ome attribute."""
        import zarr

        store = self.tmpdir / name
        group = zarr.create_group(store=str(store), zarr_format=3)
        array = group.create_array(name="0", shape=self.array.shape,
                                   dtype=self.array.dtype,
                                   chunks=(1, 1, 1, 16, 16))
        array[:] = self.array

        group.attrs["ome"] = {
            "version": "0.5",
            "multiscales": [{
                "version": "0.5", "name": "position", "axes": self.AXES,
                "datasets": self._datasets((("0", PIXEL_SIZE),)),
            }],
        }
        return store

    def test_reads_a_hand_written_v04(self):
        store = self._write_v04("foreign_v04.zarr")
        plane, meta = load_plane(store, c=1, z=0)
        np.testing.assert_array_equal(plane, self.array[0, 1, 0])
        self.assertEqual(meta["ngff_version"], "0.4")
        self.assertAlmostEqual(meta["pixel_size"]["x"], PIXEL_SIZE)
        self.assertAlmostEqual(meta["origin"]["x"], ORIGIN_YX[1])

    def test_reads_a_hand_written_v05(self):
        store = self._write_v05("foreign_v05.zarr")
        plane, meta = load_plane(store, c=1, z=2)
        np.testing.assert_array_equal(plane, self.array[0, 1, 2])
        self.assertEqual(meta["ngff_version"], "0.5")

    def test_level_is_an_index_whatever_the_datasets_are_called(self):
        # "0", "1", ... is only a convention. An integer level has to mean
        # "counting from full resolution" or the default breaks entirely.
        store = self._write_v04("foreign_levels.zarr", ("s0", "s1"))

        plane, meta = load_plane(store)
        self.assertEqual(plane.shape, (32, 32))
        self.assertEqual(meta["level"], "s0")

        plane, meta = load_plane(store, level=1)
        self.assertEqual(plane.shape, (16, 16))
        self.assertEqual(meta["level"], "s1")
        self.assertAlmostEqual(meta["pixel_size"]["x"], PIXEL_SIZE * 2)

    def test_level_can_still_be_named(self):
        store = self._write_v04("foreign_named.zarr", ("full", "half"))
        plane, meta = load_plane(store, level="half")
        self.assertEqual(plane.shape, (16, 16))
        self.assertEqual(meta["level"], "half")

    def test_unknown_level_lists_what_there_is(self):
        store = self._write_v04("foreign_bad_level.zarr", ("full", "half"))
        with self.assertRaises(ValueError) as caught:
            load_plane(store, level="quarter")
        self.assertIn("full, half", str(caught.exception))

    def test_channel_by_name_without_an_omero_block(self):
        store = self._write_v04("foreign_nochannels.zarr")
        with self.assertRaises(Exception) as caught:
            load_plane(store, c="DAPI")
        self.assertIn("DAPI", str(caught.exception))

    def test_bioformats2raw_container_names_its_positions(self):
        import zarr

        store = self.tmpdir / "converted.zarr"
        root = zarr.create_group(store=str(store), zarr_format=2)
        root.attrs["bioformats2raw.layout"] = 3
        root.create_group("OME")

        for series in ("0", "1"):
            image = root.create_group(series)
            array = image.create_array(name="0", shape=self.array.shape,
                                       dtype=self.array.dtype,
                                       chunks=(1, 1, 1, 16, 16))
            array[:] = self.array
            image.attrs["multiscales"] = [{
                "version": "0.4", "name": series, "axes": self.AXES,
                "datasets": self._datasets((("0", PIXEL_SIZE),)),
            }]

        with self.assertRaises(ValueError) as caught:
            load_plane(store)

        message = str(caught.exception)
        self.assertIn("not a position", message)
        self.assertIn("Positions: 0, 1", message)
        self.assertNotIn("OME", message.split("Positions:")[1])

        # and the position it points at does load
        plane, _ = load_plane(store / "1", z=0)
        np.testing.assert_array_equal(plane, self.array[0, 0, 0])


if __name__ == "__main__":
    unittest.main()
