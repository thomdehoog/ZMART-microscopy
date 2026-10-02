"""Install every ZMART block fresh from GitHub into one environment.

Run it with any Python that can find conda (the base environment is fine):

    python install.py

What it does, in order, and why:

1. **The environment.** It creates the conda environment ``zmart-integration``
   from ``environment.yml`` (conda-forge only), unless it exists already.
2. **The five blocks, from GitHub.** It installs the ZMART Controller, the
   drivers, the viewer, the analysis engine and the interface with pip,
   straight from their repositories on GitHub, never from a folder on this
   computer. That way the checks see exactly what a new user would get.
3. **The parts that are not packages.** Three things live only in the
   repositories, so they are cloned into ``work/``: the controller's mock
   driver (it stays with the controller's tests), the analysis workflows
   (recipes and steps the engine runs) and the interface's browser walk
   (with the Node.js tools it needs, installed by ``npm ci``).
4. **The analysis environments.** Focus scoring and object detection run in
   conda environments of their own. Each is checked with its workflow's
   ``setup_env.py --check`` and created only when the check fails, so an
   environment made earlier on this computer is reused.
5. **The browser.** Playwright's Chromium, which the walk drives.

At the end it writes ``work/install-record.json``: which commit of each block
was installed and which was cloned, so a later failure can be traced back to
the exact code that was running.

Options:

    --env-name NAME        another name for the environment
    --no-analysis-envs     skip step 4 (the analysis check is then skipped)
    --no-walk-tools        skip ``npm ci`` and the browser (no walk possible)
    --analysis-steps LIST  which analysis environments to make, as
                           ``workflow:step`` separated by commas

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WINDOWS = platform.system() == "Windows"

#: Where every block lives on GitHub.
GITHUB = "https://github.com/thomdehoog"

#: The five blocks, as pip is asked for them. The addresses carry no branch on
#: purpose: the interface and the drivers name the controller, the viewer and
#: the analysis engine by these same addresses, and pip refuses one package
#: asked for at two different addresses. Without a branch, each repository's
#: default branch (``main``) is installed.
BLOCKS = {
    "zmart-controller": f"zmart-controller @ git+{GITHUB}/ZMART-controller",
    # The Leica and ZEISS extras bring what those drivers import, so that every
    # driver can be plugged in and checked.
    "zmart-drivers": f"zmart-drivers[leica,zeiss] @ git+{GITHUB}/ZMART-drivers",
    "zmart-viewer": f"zmart-viewer @ git+{GITHUB}/ZMART-viewer",
    "zmart-analysis": f"zmart-analysis @ git+{GITHUB}/ZMART-analysis",
    # The test extra brings pytest and the OME reader the interface's own
    # in-process analysis uses.
    "zmart-interface": f"zmart-interface[test] @ git+{GITHUB}/ZMART-interface",
}

#: The repositories cloned into work/, and what each is needed for.
CHECKOUTS = {
    "ZMART-controller": "the mock driver, which stays with the controller's tests",
    "ZMART-analysis": "the analysis workflows, which are not part of the package",
    "ZMART-interface": "the browser walk and the Node.js tools it runs with",
}

#: The analysis environments the walk needs: the focus map, and the fast
#: object detection with its measurements.
ANALYSIS_STEPS = "focus:main,object_analysis:classical"


def say(text: str) -> None:
    print(f"\n== {text}", flush=True)


def run(command: list[str], *, env: dict | None = None, cwd: Path | None = None,
        check: bool = True) -> int:
    """Run one command, showing it first, and stop the install if it fails."""
    print("$ " + " ".join(str(part) for part in command), flush=True)
    done = subprocess.run([str(part) for part in command], env=env, cwd=cwd)
    if check and done.returncode != 0:
        sys.exit(f"install stopped: the command above failed (exit {done.returncode})")
    return done.returncode


def find_conda() -> str:
    """Where conda is: ``CONDA_EXE`` (set by an activated conda), or the PATH."""
    found = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if not found:
        sys.exit("conda was not found; run this from a conda prompt, or set CONDA_EXE")
    return found


def environment_prefix(conda: str, name: str) -> Path | None:
    """The folder of the conda environment called *name*, or None if there is none."""
    listed = subprocess.run([conda, "env", "list", "--json"], capture_output=True, text=True,
                            check=True)
    for prefix in json.loads(listed.stdout)["envs"]:
        if Path(prefix).name == name:
            return Path(prefix)
    return None


def ensure_environment(conda: str, name: str) -> Path:
    """Create the environment from environment.yml, unless it exists already."""
    prefix = environment_prefix(conda, name)
    if prefix is not None:
        print(f"the environment {name} exists at {prefix}; it is reused")
        return prefix
    run([conda, "env", "create", "--file", HERE / "environment.yml", "--name", name])
    prefix = environment_prefix(conda, name)
    if prefix is None:
        sys.exit(f"conda made no environment called {name}")
    return prefix


def programs_of(prefix: Path) -> list[Path]:
    """The folders of an environment where its programs (python, node, git) are."""
    if WINDOWS:
        return [prefix, prefix / "Library" / "bin", prefix / "Scripts"]
    return [prefix / "bin"]


def python_of(prefix: Path) -> Path:
    return prefix / "python.exe" if WINDOWS else prefix / "bin" / "python"


def environment_for(prefix: Path, conda: str) -> dict:
    """This process's environment variables, with the environment's programs first.

    pip needs git to fetch from GitHub, and npm needs node: both come from the
    integration environment, so the computer's own copies (or their absence)
    do not matter. ``CONDA_EXE`` is passed on because the analysis engine finds
    conda through it.
    """
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([*map(str, programs_of(prefix)), env.get("PATH", "")])
    env["CONDA_EXE"] = conda
    return env


def install_blocks(python: Path, env: dict) -> None:
    """pip-install the five blocks from GitHub, upgrading whatever is there already."""
    run([python, "-m", "pip", "install", "--upgrade", *BLOCKS.values()], env=env)


def clone(work: Path, env: dict) -> None:
    """Clone (or bring up to date) the repositories whose parts are not installed."""
    work.mkdir(exist_ok=True)
    for name, why in CHECKOUTS.items():
        target = work / name
        print(f"{name}: {why}")
        if (target / ".git").is_dir():
            run(["git", "-C", target, "pull", "--ff-only"], env=env)
        else:
            run(["git", "clone", "--branch", "main", f"{GITHUB}/{name}", target], env=env)


def analysis_environments(python: Path, work: Path, steps: str, env: dict) -> list[dict]:
    """Check each analysis environment the walk needs, and make the ones that are missing.

    An environment that exists but fails its check (made earlier, before its
    workflow asked for one more package) is never removed here: removing an
    environment is the owner's decision. It is reported, with the command
    that removes it so the next install can make it afresh, and the install
    carries on; the walk may still pass if the missing package is one it does
    not use.
    """
    made = []
    for pair in filter(None, (one.strip() for one in steps.split(","))):
        workflow, step = pair.split(":")
        folder = work / "ZMART-analysis" / "workflows" / workflow / "environments"
        name = f"ZMART--{workflow}--{step}"
        print(f"{name}: checking whether it exists and works")
        if run([python, folder / "setup_env.py", "--step", step, "--check"], env=env,
               check=False) == 0:
            made.append({"environment": name, "action": "reused (its check passed)"})
        elif environment_prefix(env["CONDA_EXE"], name) is not None:
            made.append({
                "environment": name,
                "action": "exists but FAILS its check; left as it is",
                "to_make_it_afresh": f"python {folder / 'clean_env.py'} --step {step}, "
                                     "then run install.py again",
            })
        else:
            run([python, folder / "setup_env.py", "--step", step], env=env)
            made.append({"environment": name, "action": "created"})
    return made


def walk_tools(prefix: Path, work: Path, env: dict) -> None:
    """The interface's Node.js tools (Playwright, Vite), and Playwright's Chromium."""
    npm = "npm.cmd" if WINDOWS else "npm"
    npx = "npx.cmd" if WINDOWS else "npx"
    interface = work / "ZMART-interface"
    run([npm, "ci"], env=env, cwd=interface)
    run([npx, "playwright", "install", "chromium"], env=env, cwd=interface)


def commit_of(folder: Path, env: dict) -> str:
    return subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"], capture_output=True,
                          text=True, env=env).stdout.strip()


def installed_record(python: Path, env: dict) -> dict:
    """For each block: its version, and the GitHub commit pip installed it from."""
    program = (
        "import json\n"
        "from importlib.metadata import distribution\n"
        f"names = {list(BLOCKS)!r}\n"
        "out = {}\n"
        "for name in names:\n"
        "    d = distribution(name)\n"
        "    direct = json.loads(d.read_text('direct_url.json') or '{}')\n"
        "    out[name] = {'version': d.version, 'url': direct.get('url'),\n"
        "                 'commit': direct.get('vcs_info', {}).get('commit_id')}\n"
        "print(json.dumps(out))\n"
    )
    said = subprocess.run([str(python), "-c", program], capture_output=True, text=True, env=env,
                          check=True)
    return json.loads(said.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-name", default="zmart-integration")
    parser.add_argument("--no-analysis-envs", action="store_true")
    parser.add_argument("--no-walk-tools", action="store_true")
    parser.add_argument("--analysis-steps", default=ANALYSIS_STEPS)
    args = parser.parse_args(argv)
    work = HERE / "work"

    say("the environment")
    conda = find_conda()
    prefix = ensure_environment(conda, args.env_name)
    python = python_of(prefix)
    env = environment_for(prefix, conda)

    say("the five blocks, from GitHub")
    install_blocks(python, env)

    say("the repositories with the parts that are not installed")
    clone(work, env)

    analysis = []
    if not args.no_analysis_envs:
        say("the analysis environments")
        analysis = analysis_environments(python, work, args.analysis_steps, env)

    if not args.no_walk_tools:
        say("the walk's Node.js tools and browser")
        walk_tools(prefix, work, env)

    record = {
        "environment": str(prefix),
        "python": str(python),
        "installed": installed_record(python, env),
        "cloned": {name: commit_of(work / name, env) for name in CHECKOUTS},
        "analysis_environments": analysis,
    }
    (work / "install-record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    say("done")
    print(json.dumps(record, indent=2))
    print(f"\nNext: {python} -m pytest tests     (the plug-in checks)")
    print(f"      {python} run_walk.py         (the operator window, end to end)")
    failing = [one for one in analysis if "FAILS" in one["action"]]
    for one in failing:
        print(f"\nWARNING: {one['environment']} fails its check. To make it afresh: "
              f"{one['to_make_it_afresh']}")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
