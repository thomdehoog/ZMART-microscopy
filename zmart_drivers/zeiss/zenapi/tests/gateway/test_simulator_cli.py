"""``python -m zenapi.simulator`` starts, writes a config.ini, and serves the driver."""

import subprocess
import sys
import time
from pathlib import Path

import pytest


def test_cli_serves_until_interrupted(tmp_path):
    import zenapi as drv

    zeiss_dir = Path(drv.__file__).resolve().parents[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "zenapi.simulator", "--port", "0", "--workdir", str(tmp_path)],
        cwd=str(zeiss_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        config = tmp_path / "config.ini"
        deadline = time.time() + 20
        while not config.exists() and time.time() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"simulator exited early:\n{proc.stdout.read()}")
            time.sleep(0.1)
        assert config.exists(), "the simulator did not write config.ini"
        time.sleep(0.2)  # the file is written after the port is open; give it a beat
        client = drv.connect(str(config))
        try:
            assert drv.ping(client)
            assert "ZMART_Snap" in drv.get_available_experiments(client)
        finally:
            drv.close(client)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
