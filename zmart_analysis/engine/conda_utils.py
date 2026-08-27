"""
Shared conda utilities for environment setup and cleanup scripts.

Provides conda discovery, environment queries, and GPU detection.
"""

import os
import subprocess
import platform
import shutil
import json
import re
from pathlib import Path

# Conda sets CONDA_EXE when any environment is activated.
# This propagates to all subprocesses automatically.
CONDA_CMD = os.environ.get("CONDA_EXE", "conda")


def get_conda_info():
    """Get conda configuration via 'conda info --json'.

    This is the single source of truth for the conda executable,
    environment directories, and existing environments.

    Uses CONDA_EXE environment variable to find conda, which is set
    automatically by conda activation and propagates to subprocesses.

    Returns
    -------
    dict
        Parsed JSON output from conda info.

    Raises
    ------
    FileNotFoundError
        If conda is not available.
    """
    try:
        result = subprocess.run(
            [CONDA_CMD, "info", "--json"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except FileNotFoundError:
        pass

    raise FileNotFoundError(
        "Could not run 'conda info'. Please ensure:\n"
        "  - Conda is installed\n"
        "  - You are running from a conda-enabled terminal\n"
        "    (Anaconda Prompt, Miniconda Prompt, or terminal with conda init)"
    )


def get_conda_exe(conda_info):
    """Get the conda executable path from conda info."""
    conda_exe = conda_info.get("conda_exe")
    if conda_exe and Path(conda_exe).exists():
        return conda_exe
    return CONDA_CMD


def env_exists(conda_info, env_name):
    """Check if a conda environment exists."""
    for env_path in conda_info.get("envs", []):
        if Path(env_path).name == env_name:
            return True
    return False


def list_envs_by_prefix(conda_info, prefix):
    """List all conda envs whose name starts with prefix."""
    matching = []
    for env_path in conda_info.get("envs", []):
        name = Path(env_path).name
        if name.startswith(prefix):
            matching.append(name)
    return matching


def detect_gpu():
    """Auto-detect available GPU acceleration and CUDA version.

    Returns
    -------
    str
        "cu128", "cu124", etc. for NVIDIA CUDA (matched to installed version),
        "mps" for Apple Silicon, "cpu" otherwise.
    """
    system = platform.system()

    if system == "Darwin":
        if platform.machine() == "arm64":
            return "mps"
        return "cpu"

    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return "cpu"

    try:
        result = subprocess.run(
            [nvidia_smi], capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return "cpu"

        for line in result.stdout.split("\n"):
            if "CUDA Version" in line:
                match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", line)
                if match:
                    major, minor = int(match.group(1)), int(match.group(2))
                    cuda_tag = f"cu{major}{minor}"
                    available = ["cu128", "cu126", "cu124", "cu121", "cu118"]
                    if cuda_tag in available:
                        return cuda_tag
                    for tag in available:
                        tag_major = int(tag[2:-1])
                        tag_minor = int(tag[-1])
                        if tag_major < major or (tag_major == major and tag_minor <= minor):
                            return tag
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return "cu124"


def gpu_label(gpu):
    """Human-readable label for the GPU backend."""
    if gpu == "mps":
        return "Apple MPS (Metal Performance Shaders)"
    elif gpu == "cpu":
        return "CPU (no GPU acceleration)"
    else:
        version = f"{gpu[2:-1]}.{gpu[-1]}"
        return f"NVIDIA CUDA {version}"


def get_torch_install_args(gpu):
    """Get pip install arguments for PyTorch based on GPU type."""
    if gpu == "mps":
        return ["torch", "torchvision"]
    elif gpu == "cpu":
        return ["torch", "torchvision",
                "--index-url", "https://download.pytorch.org/whl/cpu"]
    else:
        return ["torch", "torchvision",
                "--index-url", f"https://download.pytorch.org/whl/{gpu}"]
