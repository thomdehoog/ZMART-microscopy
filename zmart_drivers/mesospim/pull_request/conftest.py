"""Pytest grouping for the mesoSPIM Remote Control contribution tests."""
from pathlib import Path


_ADVERSARIAL_MODULES = {
    "test_remote_control_adversarial.py",
    "test_remote_control_transport_harsh.py",
}
_LIVE_VALID_MODULES = {"test_remote_control_live_valid.py"}
_LIVE_DEMO_ALL_MODULES = {"test_remote_control_live_demo_all.py"}


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "normal: functional, validation, protocol, and viability tests")
    config.addinivalue_line(
        "markers", "adversarial: bounded hostile-input and transport-abuse tests")
    config.addinivalue_line(
        "markers", "live_valid: opt-in valid calls that change and restore a live device")
    config.addinivalue_line(
        "markers", "live_demo_all: opt-in demo-only sweep of every allowlisted command")


def pytest_collection_modifyitems(items):
    """Put every collected test in exactly one public group."""
    for item in items:
        module_name = Path(str(item.fspath)).name
        if module_name in _ADVERSARIAL_MODULES:
            marker = "adversarial"
        elif module_name in _LIVE_VALID_MODULES:
            marker = "live_valid"
        elif module_name in _LIVE_DEMO_ALL_MODULES:
            marker = "live_demo_all"
        else:
            marker = "normal"
        item.add_marker(marker)
