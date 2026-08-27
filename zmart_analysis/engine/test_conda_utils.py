"""Unit tests for ``engine.conda_utils``.

Run from a conda-enabled terminal::

    pytest engine/test_conda_utils.py -v
"""

import unittest
from pathlib import Path

from engine.conda_utils import (
    get_conda_info,
    get_conda_exe,
    env_exists,
    list_envs_by_prefix,
    detect_gpu,
    gpu_label,
    get_torch_install_args,
)


class TestGetCondaInfo(unittest.TestCase):
    """Tests for get_conda_info()."""

    def test_returns_dict(self):
        info = get_conda_info()
        self.assertIsInstance(info, dict)

    def test_has_required_keys(self):
        info = get_conda_info()
        for key in ["conda_version", "envs", "envs_dirs", "root_prefix"]:
            self.assertIn(key, info, f"Missing key: {key}")

    def test_conda_version_is_string(self):
        info = get_conda_info()
        self.assertIsInstance(info["conda_version"], str)
        # Should look like "X.Y.Z"
        parts = info["conda_version"].split(".")
        self.assertGreaterEqual(len(parts), 2)

    def test_envs_is_list(self):
        info = get_conda_info()
        self.assertIsInstance(info["envs"], list)

    def test_envs_dirs_is_list(self):
        info = get_conda_info()
        self.assertIsInstance(info["envs_dirs"], list)
        self.assertGreater(len(info["envs_dirs"]), 0)

    def test_root_prefix_exists(self):
        info = get_conda_info()
        self.assertTrue(Path(info["root_prefix"]).exists())


class TestGetCondaExe(unittest.TestCase):
    """Tests for get_conda_exe()."""

    def test_returns_string(self):
        info = get_conda_info()
        exe = get_conda_exe(info)
        self.assertIsInstance(exe, str)

    def test_executable_exists_or_is_conda(self):
        info = get_conda_info()
        exe = get_conda_exe(info)
        # Either a path that exists, or bare "conda" (on PATH)
        self.assertTrue(
            Path(exe).exists() or exe == "conda",
            f"Executable not found: {exe}",
        )


class TestEnvExists(unittest.TestCase):
    """Tests for env_exists()."""

    def test_existing_env(self):
        info = get_conda_info()
        # At least one env should exist
        if info["envs"]:
            name = Path(info["envs"][0]).name
            self.assertTrue(env_exists(info, name))

    def test_nonexistent_env(self):
        info = get_conda_info()
        self.assertFalse(env_exists(info, "this_env_does_not_exist_12345"))


class TestListEnvsByPrefix(unittest.TestCase):
    """Tests for list_envs_by_prefix()."""

    def test_returns_list(self):
        info = get_conda_info()
        result = list_envs_by_prefix(info, "SMART--")
        self.assertIsInstance(result, list)

    def test_nonexistent_prefix(self):
        info = get_conda_info()
        result = list_envs_by_prefix(info, "ZZZZZ_NONEXISTENT_PREFIX_")
        self.assertEqual(result, [])

    def test_all_match_prefix(self):
        info = get_conda_info()
        prefix = "SMART--"
        result = list_envs_by_prefix(info, prefix)
        for name in result:
            self.assertTrue(name.startswith(prefix))


class TestDetectGpu(unittest.TestCase):
    """Tests for detect_gpu()."""

    def test_returns_string(self):
        gpu = detect_gpu()
        self.assertIsInstance(gpu, str)

    def test_valid_value(self):
        gpu = detect_gpu()
        valid = {"cpu", "mps", "cu118", "cu121", "cu124", "cu126", "cu128"}
        self.assertIn(gpu, valid, f"Unexpected GPU value: {gpu}")


class TestGpuLabel(unittest.TestCase):
    """Tests for gpu_label()."""

    def test_cpu(self):
        self.assertIn("CPU", gpu_label("cpu"))

    def test_mps(self):
        self.assertIn("MPS", gpu_label("mps"))

    def test_cuda(self):
        label = gpu_label("cu124")
        self.assertIn("NVIDIA", label)
        self.assertIn("12.4", label)


class TestGetTorchInstallArgs(unittest.TestCase):
    """Tests for get_torch_install_args()."""

    def test_cpu_has_index_url(self):
        args = get_torch_install_args("cpu")
        self.assertIn("torch", args)
        self.assertIn("--index-url", args)
        self.assertIn("cpu", args[-1])

    def test_cuda_has_index_url(self):
        args = get_torch_install_args("cu124")
        self.assertIn("torch", args)
        self.assertIn("--index-url", args)
        self.assertIn("cu124", args[-1])

    def test_mps_no_index_url(self):
        args = get_torch_install_args("mps")
        self.assertIn("torch", args)
        self.assertNotIn("--index-url", args)


if __name__ == "__main__":
    unittest.main()
