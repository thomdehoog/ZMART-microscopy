"""Create the conda environment for the focus workflow.

One environment, ``ZMART--focus--main``. Scoring sharpness needs numpy, a DCT
from scipy, and the readers -- no cellpose, no torch, no GPU. Keeping it out
of the vision environment means a focus run costs a small environment rather
than a deep-learning one.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# conda_utils lives in the shared engine, three directories up — on the path
# before it is imported, so this runs as a plain script from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))

from conda_utils import (  # noqa: E402
    detect_gpu,
    env_exists,
    get_conda_exe,
    get_conda_info,
    get_torch_install_args,
    gpu_label,
    list_envs_by_prefix,
)



WORKFLOW = "focus"
PYTHON_VERSION = "3.12"

PIP_PACKAGES = [
    "pyyaml",
    "numpy",
    "scipy",         # scipy.fft.dctn, the entropy metric's transform
    # Before 2026.6.1 tifffile imports a name zarr 3.3 moved, and the first
    # read fails with a misleading "zarr 3.3.0 < 3 is not supported".
    "tifffile>=2026.6.1",
    "imagecodecs",
    "ngio",          # OME-Zarr, NGFF 0.4 and 0.5
    "ome-types",     # OME-XML metadata
]

#: ``__STEPS__`` is replaced with this workflow's steps directory before the
#: check runs. A placeholder rather than a format field, because these are
#: Python one-liners and braces are theirs.
DIAGNOSTICS = [
    (
        "DCT transform",
        "import numpy as np; from scipy.fft import dctn; "
        "print('OK' if dctn(np.zeros((8, 8)), norm='ortho').shape == (8, 8) else 'FAIL')",
    ),
    (
        "TIFF/zarr interop",
        "import tifffile, tifffile.zarr, zarr; "
        "print(tifffile.__version__ + ' + zarr ' + zarr.__version__)",
    ),
    (
        "scores a z-stack in an OME-Zarr position",
        "import sys, tempfile, numpy as np, ngio; "
        "from pathlib import Path; "
        "d = Path(tempfile.mkdtemp()) / 'p.zarr'; "
        "a = np.zeros((1, 1, 5, 32, 32), dtype='uint16'); "
        "a[0, 0, 2] = np.random.default_rng(0).integers(0, 4096, size=(32, 32)); "
        "ngio.create_ome_zarr_from_array(d, a, pixelsize=1.0, z_spacing=1.0, "
        "axes_names=('t','c','z','y','x'), levels=1, overwrite=True); "
        "sys.path.insert(0, r'__STEPS__'); "
        "from score_focus import run; "
        "payload = dict(input=dict(image_path=str(d)), metadata=dict(verbose=0)); "
        "peak = run(payload, dict(), skip_ends=0)['score_focus']['peak_index']; "
        "print('OK' if abs(peak - 2) < 0.5 else 'FAIL peak=' + str(peak))",
    ),
]


WIDTH = 70


def banner(title: str) -> None:
    print()
    print("=" * WIDTH)
    print(f"  {title}")
    print("=" * WIDTH)


def section(title: str) -> None:
    print()
    print(f"  {title}")
    print(f"  {'-' * (WIDTH - 4)}")


def info(label: str, value: str) -> None:
    print(f"  {label + ':':<24s} {value}")


def ok(message: str) -> None:
    print(f"  [ OK ]    {message}")


def fail(message: str) -> None:
    print(f"  [FAIL]    {message}")


def skip(message: str) -> None:
    print(f"  [SKIP]    {message}")


def warn(message: str) -> None:
    print(f"  [WARN]    {message}")


def cmd_line(cmd: list[str]) -> None:
    print(f"  [ RUN]    {' '.join(cmd)}")


def setup_workflow_env(
    *,
    workflow: str,
    pip_packages: list[str],
    diagnostics: list[tuple[str, str]],
    python_version: str = "3.12",
    install_torch: bool = True,
    default_step: str = "main",
) -> None:
    """Create a ZMART--<workflow>--<step> conda env."""
    parser = argparse.ArgumentParser(
        description=f"Set up conda env for {workflow} workflow"
    )
    parser.add_argument(
        "--step",
        default=default_step,
        help=f"Step name for isolation (default: {default_step})",
    )
    parser.add_argument(
        "--python",
        default=python_version,
        help=f"Python version (default: {python_version})",
    )
    parser.add_argument(
        "--gpu",
        default=None,
        help="PyTorch GPU backend: cu128, cu124, cu121, mps, cpu (default: auto-detect)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )
    args = parser.parse_args()

    env_name = f"ZMART--{workflow}--{args.step}"
    gpu = (args.gpu or detect_gpu()) if install_torch else None
    t_start = time.time()

    banner("ZMART Analysis -- Environment Setup")

    section("System")
    import platform as pf

    info("Platform", f"{pf.system()} ({pf.machine()})")
    info("Python target", args.python)
    info("GPU backend", gpu_label(gpu) if install_torch else "not used")

    try:
        conda_info = get_conda_info()
    except FileNotFoundError as e:
        fail(str(e))
        sys.exit(1)

    conda_version = conda_info.get("conda_version", "unknown")
    _warn_old_conda(conda_version)
    info("Conda version", conda_version)

    section("Conda")
    conda = get_conda_exe(conda_info)
    envs_dirs = conda_info.get("envs_dirs", [])

    info("Executable", conda)
    info("Root prefix", conda_info.get("root_prefix", "unknown"))
    info("Envs directory", envs_dirs[0] if envs_dirs else "unknown")

    if env_exists(conda_info, env_name):
        fail(f"Environment '{env_name}' already exists.")
        print(f"         Remove it first: python clean_env.py --step {args.step}")
        sys.exit(1)

    section("Environment")
    info("Name", env_name)
    info("Workflow", workflow)
    info("Step", args.step)

    total_steps = 4 if install_torch else 3

    section(f"[1/{total_steps}] Creating conda environment")
    create_cmd = [
        conda,
        "create",
        "-n",
        env_name,
        f"python={args.python}",
        "-y",
        "-q",
    ]
    cmd_line(create_cmd)
    if args.dry_run:
        skip("dry run")
    else:
        result = subprocess.run(create_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            fail("Failed to create environment")
            print(result.stderr)
            sys.exit(1)
        ok(f"Created {env_name}")

    next_step = 2
    if install_torch:
        section(f"[{next_step}/{total_steps}] Installing PyTorch ({gpu_label(gpu)})")
        pip_cmd = [
            conda,
            "run",
            "--no-capture-output",
            "-n",
            env_name,
            "pip",
            "install",
        ] + get_torch_install_args(gpu)
        cmd_line(pip_cmd)
        if args.dry_run:
            skip("dry run")
        else:
            result = subprocess.run(pip_cmd)
            if result.returncode != 0:
                fail("PyTorch installation failed")
                sys.exit(1)
            ok("PyTorch installed")
            _run_torch_backend_check(conda, env_name, gpu)
        next_step += 1

    section(f"[{next_step}/{total_steps}] Installing analysis packages")
    pip_cmd = [
        conda,
        "run",
        "--no-capture-output",
        "-n",
        env_name,
        "pip",
        "install",
    ] + pip_packages
    print(f"  Packages: {', '.join(pip_packages)}")
    cmd_line(pip_cmd)
    if args.dry_run:
        skip("dry run")
    else:
        result = subprocess.run(pip_cmd)
        if result.returncode != 0:
            fail("Package installation failed")
            sys.exit(1)
        for pkg in pip_packages:
            ok(pkg)

    next_step += 1
    section(f"[{next_step}/{total_steps}] Running diagnostics")
    if args.dry_run:
        skip("dry run")
    else:
        _run_diagnostics(conda, env_name, diagnostics)

    elapsed = time.time() - t_start

    banner("Setup Complete")
    section("Summary")
    info("Environment", env_name)
    info("GPU backend", gpu_label(gpu) if install_torch else "not used")
    info("Python", args.python)
    torch_packages = 2 if install_torch else 0
    info("Packages", str(len(pip_packages) + torch_packages))
    info("Time", f"{elapsed:.0f}s")

    section("Next steps")
    print(f"  Activate:    conda activate {env_name}")
    print(f"  Remove:      python clean_env.py --step {args.step}")
    print()
    print("=" * WIDTH)


def clean_workflow_envs(*, workflow: str) -> None:
    """Remove ZMART--<workflow>--* conda envs."""
    parser = argparse.ArgumentParser(
        description=f"Remove conda envs for {workflow} workflow"
    )
    parser.add_argument(
        "--step",
        default=None,
        help="Remove only this step's env. If omitted, removes all.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching environments without removing them",
    )
    args = parser.parse_args()

    prefix = f"ZMART--{workflow}--"
    t_start = time.time()

    banner("ZMART Analysis -- Environment Cleanup")

    section("Conda")
    try:
        conda_info = get_conda_info()
    except FileNotFoundError as e:
        fail(str(e))
        sys.exit(1)

    conda = get_conda_exe(conda_info)
    envs_dirs = conda_info.get("envs_dirs", [])

    info("Executable", conda)
    info("Envs directory", envs_dirs[0] if envs_dirs else "unknown")

    all_matching = list_envs_by_prefix(conda_info, prefix)
    if args.step:
        target_name = f"{prefix}{args.step}"
        targets = [target_name] if target_name in all_matching else []
        if not targets:
            section("Result")
            fail(f"Environment '{target_name}' not found")
            if all_matching:
                print()
                print("  Available environments:")
                for name in all_matching:
                    print(f"    {name}")
            sys.exit(1)
    else:
        targets = all_matching

    section("Environments found")
    if not targets:
        info("Matching", f"0 (pattern: {prefix}*)")
        banner("Nothing to remove")
        return

    info("Matching", str(len(targets)))
    for name in targets:
        print(f"    {name}")

    if args.dry_run:
        section("Result")
        skip(f"dry run -- {len(targets)} environment(s) would be removed")
        print()
        print("=" * WIDTH)
        return

    section("Removing")
    removed = 0
    for name in targets:
        cmd = [conda, "env", "remove", "-n", name, "-y"]
        cmd_line(cmd)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            ok(name)
            removed += 1
        else:
            fail(name)

    elapsed = time.time() - t_start

    banner("Cleanup Complete")
    section("Summary")
    info("Removed", f"{removed}/{len(targets)} environment(s)")
    info("Time", f"{elapsed:.0f}s")

    if removed < len(targets):
        print()
        fail("Some environments could not be removed")

    print()
    print("=" * WIDTH)


def _warn_old_conda(conda_version: str) -> None:
    if conda_version == "unknown":
        return
    try:
        major, minor, *_ = conda_version.split(".")
        if float(f"{major}.{minor}") < 25.7:
            warn("Conda < 25.7 can be unreliable for env switching")
    except (ValueError, IndexError):
        return


def _run_diagnostics(
    conda: str, env_name: str, diagnostics: list[tuple[str, str]]
) -> None:
    all_passed = True
    for label, code in diagnostics:
        result = subprocess.run(
            [
                conda,
                "run",
                "--no-capture-output",
                "-n",
                env_name,
                "python",
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
        )
        output = result.stdout.strip()
        if result.returncode == 0:
            ok(f"{label:<28s} {output}")
        else:
            fail(f"{label:<28s}")
            all_passed = False

    if not all_passed:
        banner("Setup Failed")
        print("  Some diagnostics did not pass.")
        sys.exit(1)


def _run_torch_backend_check(conda: str, env_name: str, gpu: str) -> None:
    if gpu == "cpu":
        code = (
            "import torch; "
            "x = torch.ones((2, 2)); "
            "print(f'{torch.__version__} CPU tensor OK shape={tuple(x.shape)}')"
        )
    elif gpu == "mps":
        code = (
            "import torch; "
            "assert torch.backends.mps.is_available(), 'MPS is not available'; "
            "x = torch.ones((2, 2), device='mps'); "
            "print(f'{torch.__version__} MPS tensor OK device={x.device}')"
        )
    else:
        code = (
            "import torch; "
            "assert torch.cuda.is_available(), 'CUDA is not available'; "
            "x = torch.ones((2, 2), device='cuda'); "
            "torch.cuda.synchronize(); "
            "print(f'{torch.__version__} CUDA tensor OK device={x.device} "
            "name={torch.cuda.get_device_name(0)}')"
        )

    result = subprocess.run(
        [
            conda,
            "run",
            "--no-capture-output",
            "-n",
            env_name,
            "python",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip()
    if result.returncode == 0:
        ok(f"{'PyTorch backend check':<28s} {output}")
        return
    fail(f"{'PyTorch backend check':<28s}")
    if result.stderr.strip():
        print(result.stderr.strip())
    sys.exit(1)


if __name__ == "__main__":
    steps = str(Path(__file__).resolve().parents[1] / "steps")
    setup_workflow_env(
        workflow=WORKFLOW,
        pip_packages=PIP_PACKAGES,
        diagnostics=[
            (label, code.replace("__STEPS__", steps)) for label, code in DIAGNOSTICS
        ],
        python_version=PYTHON_VERSION,
        install_torch=False,
        default_step="main",
    )
