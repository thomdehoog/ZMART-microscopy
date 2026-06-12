import importlib.util
import logging
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from navigator_expert.runtime import profiles


def _load_validator():
    path = Path(__file__).resolve().parents[1] / "hardware" / "validate_hardware.py"
    spec = importlib.util.spec_from_file_location("validate_hardware_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestValidateHardwareCli(unittest.TestCase):
    def setUp(self):
        self._profile = profiles.STATE_READERS
        self.addCleanup(self._restore)

    def _restore(self):
        profiles.STATE_READERS = self._profile

    def test_log_tuning_flags_preserve_current_confirm_source(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            selected_job_confirm_source="hybrid",
        )
        validator = _load_validator()
        args = SimpleNamespace(
            select_job_confirm_source=None,
            enable_log_select_confirm=False,
            mock=False,
            state_reader_mode=None,
            log_select_confirm_timeout_s=1.5,
            log_select_cluster_max_age_s=None,
            prime_log_select_cluster=False,
        )

        validator._apply_log_select_confirmation(args, logging.getLogger("validate-hardware-test"))

        self.assertEqual(profiles.STATE_READERS.selected_job_confirm_source, "hybrid")
        self.assertEqual(profiles.STATE_READERS.selected_job_log_confirm_timeout_s, 1.5)


if __name__ == "__main__":
    unittest.main()
