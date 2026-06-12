from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from navigator_expert.runtime import lasx_runtime, profiles


class TestLasxRuntime(unittest.TestCase):
    def test_missing_dlls_reports_required_names(self):
        root = Path(self._tmpdir.name)

        missing = lasx_runtime._missing_dlls(root)

        self.assertEqual(missing, list(lasx_runtime.REQUIRED_DLLS))

    def test_missing_dlls_accepts_complete_runtime_root(self):
        root = Path(self._tmpdir.name)
        for name in lasx_runtime.REQUIRED_DLLS:
            (root / name).write_bytes(b"")

        self.assertEqual(lasx_runtime._missing_dlls(root), [])

    def test_missing_runtime_fails_before_importing_clr(self):
        root = Path(self._tmpdir.name)
        profile = profiles.LasxApiProfile(runtime_root=str(root))

        with mock.patch.object(profiles, "LASX_API", profile):
            with self.assertRaisesRegex(RuntimeError, "Is LAS X installed"):
                lasx_runtime.load_lasx_api_runtime()

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
