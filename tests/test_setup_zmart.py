"""The installer, setup_zmart.py: its parts, and the whole run on a stand-in computer.

The installer runs conda and pip, which take many minutes and need the
internet. These checks hand it a stand-in for its shell instead, which answers
the way conda, pip and the checks' programs answer, so that every path through
the installer can be checked in seconds: a setup that works, one where conda
cannot make an environment, and one where an analysis step does not load.
What the real commands do is checked by running the installer itself on a
computer (``python setup_zmart.py``).

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from zmart_setup import analysis, blocks, checks, layout, main, releases, starting  # noqa: E402
from zmart_setup.shell import Done  # noqa: E402

RELEASES = releases.read(REPO / "releases.toml")

#: The analysis pipelines ZMART Analysis's ``examples`` holds, as far as the setup reads them:
#: each environment's file, and a step that names it.
EXAMPLE_PIPELINES = {
    "focus": {"main": ("ZMART--focus--main", ["score_focus"])},
    "object_analysis": {"classical": ("ZMART--object_analysis--classical", ["segment_watershed"]),
                        "umap": ("ZMART--object_analysis--umap", ["reduce_dimensions"]),
                        "cellpose": (analysis.CELLPOSE, ["segment_cellpose"])},
}


def the_clones(beside: Path) -> Path:
    """Stand-ins for the two clones next to ZMART Microscopy: the analysis pipelines, and the built page."""
    for workflow, environments in EXAMPLE_PIPELINES.items():
        folder = beside / "ZMART-analysis" / "examples" / workflow
        for file, (name, steps) in environments.items():
            (folder / "environments").mkdir(parents=True, exist_ok=True)
            (folder / "environments" / f"{file}.yml").write_text(f"name: {name}\n", encoding="utf-8")
            (folder / "steps").mkdir(exist_ok=True)
            for step in steps:
                (folder / "steps" / f"{step}.py").write_text(f'META = {{"environment": "{name}"}}\n',
                                                              encoding="utf-8")
    page = beside / "ZMART-interface" / "examples" / "built-page"
    page.mkdir(parents=True, exist_ok=True)
    (page / "index.html").write_text("<html></html>", encoding="utf-8")
    return beside


# ----------------------------------------------------------------- the parts


def test_releases_name_every_block_at_a_tag():
    assert set(RELEASES.refs) == set(releases.BLOCKS)
    for block in releases.BLOCKS:
        assert RELEASES.version(block), f"{block} is not pinned to a release tag: {RELEASES.refs[block]}"


def test_the_trial_file_names_every_block():
    trial = releases.read(REPO / "releases-trial.toml")
    assert set(trial.refs) == set(releases.BLOCKS)


def test_a_setup_can_install_from_the_trial_file(a_setup):
    code, report, said, computer = a_setup("--releases", str(REPO / "releases-trial.toml"),
                                           "--no-coder", "--microscope", "mock", "--no-cellpose")
    assert report["facts"]["releases"]["file"] == "releases-trial.toml"
    asked = " ".join(" ".join(cmd) for cmd in computer.commands)
    assert "github.com/thomdehoog/ZMART-interface@examples-and-workflows" in asked


def test_a_block_is_asked_for_at_its_release():
    assert RELEASES.address("zmart-drivers", "leica") == (
        f"zmart-drivers[leica] @ git+https://github.com/{RELEASES.github}/ZMART-drivers@{RELEASES.refs['zmart-drivers']}"
    )


def test_a_change_can_be_tried_from_another_account_and_branch():
    tried = releases.read(REPO / "releases.toml", "thomdehoog", ["zmart-interface=examples-and-workflows"])
    assert tried.address("zmart-interface") == (
        "zmart-interface @ git+https://github.com/thomdehoog/ZMART-interface@examples-and-workflows"
    )
    assert tried.version("zmart-interface") is None  # a branch has no version to compare with


def test_a_wrong_ref_is_said_plainly():
    with pytest.raises(ValueError, match="BLOCK=REF"):
        releases.read(REPO / "releases.toml", refs=["zmart-everything=v1"])


def test_the_mock_needs_no_drivers_package_and_the_leica_its_extra():
    assert "zmart-drivers" not in blocks.which_blocks("mock")
    assert blocks.which_blocks("leica")["zmart-drivers"] == "leica"
    # The notebook's environment gets the controller, the analysis engine and the driver; no window.
    assert set(blocks.which_blocks("leica", layout.CODER)) == {"zmart-controller", "zmart-analysis",
                                                               "zmart-drivers"}


def test_both_environments_are_made_from_the_workflows_own_files():
    for environment in (layout.OPERATOR, layout.CODER):
        named = re.search(r"^name:\s*(\S+)", environment.file.read_text(encoding="utf-8"), re.M)
        assert named and named[1] == environment.name, environment.file


def test_the_notebooks_analysis_environments_have_their_files_and_steps():
    found = analysis.environments_in(layout.CODERS)
    assert set(found) == {"ZMART--target_acquisition_for_coders--classical",
                          "ZMART--target_acquisition_for_coders--focus"}
    for name, one in found.items():
        assert one.file.is_file() and one.steps, name


def test_cellpose_is_made_only_when_asked_for(tmp_path):
    folders = [the_clones(tmp_path) / "ZMART-analysis" / "examples"]
    assert analysis.CELLPOSE not in analysis.wanted(folders, cellpose=False)
    assert analysis.CELLPOSE in analysis.wanted(folders, cellpose=True)


def test_a_coder_gets_the_pipelines_of_both_halves(tmp_path):
    operators = [the_clones(tmp_path) / "ZMART-analysis" / "examples"]
    both = analysis.wanted(operators + [layout.CODERS], False)
    assert set(analysis.wanted(operators, False)) < set(both)
    assert "ZMART--target_acquisition_for_coders--focus" in both


def test_a_step_with_a_dataclass_loads_in_the_check_as_in_the_engine(tmp_path):
    step = ("from __future__ import annotations\n"
            "from dataclasses import dataclass\n\n"
            "@dataclass(frozen=True)\n"
            "class Measured:\n"
            "    name: str\n")
    paths = []
    for copy in ("non-coders", "coders"):
        path = tmp_path / copy / "measure_objects.py"
        path.parent.mkdir()
        path.write_text(step, encoding="utf-8")
        paths.append(str(path))
    done = subprocess.run([sys.executable, "-c", analysis.LOAD_THE_STEPS, *paths],
                          capture_output=True, text=True)
    assert json.loads(done.stdout.strip().splitlines()[-1])["failed"] == {}, done.stdout + done.stderr


def test_the_start_file_opens_the_window_on_our_workflows(tmp_path):
    operator, notebook = starting.starts_for(Path("C:/conda/zmart-for-non-coders"),
                                             Path("/opt/conda/envs/zmart-for-coders"), "D:/ZMART data")
    text = starting.windows_file(operator, "C:/miniforge3/Scripts/conda.exe")
    assert '-m zmart_interface.launcher --output-root "D:/ZMART data"' in text
    assert str(layout.clones()["interface"].workflows) in text
    assert str(layout.clones()["analysis"].workflows) in text
    assert 'set "TEMP=' + str(Path("C:/conda/zmart-for-non-coders") / "tmp") in text
    assert "conda activate" not in text  # the environment's programs are set up directly
    assert "zmart-install-doctor.md" in text and "pause" in text
    posix = starting.posix_file(notebook, "/opt/conda/bin/conda")
    assert "-m jupyterlab" in posix and str(layout.CODERS) in posix
    assert f"{Path('/opt/conda/envs/zmart-for-coders')}/bin/python" in posix


def test_the_doctor_is_a_claude_code_agent_that_reads_the_report():
    doctor = (REPO / ".claude" / "agents" / "zmart-install-doctor.md").read_text(encoding="utf-8")
    front = re.match(r"---\n(.*?)\n---\n", doctor, re.S)
    assert front and "name: zmart-install-doctor" in front[1] and "description:" in front[1]
    assert "local/setup-report.json" in doctor and "setup_zmart.py --check" in doctor


# ------------------------------------------------------ the whole run, stood in


class AStandInComputer:
    """A shell that answers like conda, pip and the checks' programs, without running anything.

    ``broken`` names what should fail: ``"environment"`` (conda cannot make
    the ZMART environment) or ``"step"`` (one analysis step does not load).
    """

    def __init__(self, record, broken: str = "") -> None:
        self.record = record
        self.broken = broken
        self.environments = {"base": Path("/opt/conda")}
        self.commands: list[list[str]] = []

    def run(self, command, *, env=None, cwd=None, timeout=None, quiet=False) -> Done:
        command = [str(part) for part in command]
        self.commands.append(command)
        self.record.log("$ " + " ".join(command))
        text = " ".join(command)
        if command[1:3] == ["env", "list"]:
            return self._ok({"envs": [str(folder) for folder in self.environments.values()]})
        if command[0] == "git" and "status" in command and self.broken == "clone":
            return Done(command, 0, " M examples/target_acquisition/flow.ts\n")
        if command[1:3] == ["info", "--json"]:
            return self._ok({"root_prefix": "/opt/conda", "envs_dirs": ["/opt/conda/envs"]})
        if command[1:3] == ["env", "create"]:
            file = Path(cwd or ".") / command[-1] if cwd else Path(command[-1])
            name = re.search(r"^name:\s*(\S+)", file.read_text(encoding="utf-8"), re.M)[1]
            if self.broken == "environment" and name == blocks.NAME:
                return Done(command, 1, "CondaHTTPError: HTTP 000 CONNECTION FAILED\n")
            self.environments[name] = Path("/opt/conda/envs") / name
            return Done(command, 0, "done\n")
        if command[1:3] in (["env", "update"], ["--version"]) or command[1] == "--version":
            return Done(command, 0, "conda 24.9.2\n")
        if "-c" not in command:
            return Done(command, 0, "")  # pip install, pip check
        program = command[command.index("-c") + 1]
        if program == blocks.WHAT_THE_BLOCKS_NEED:
            return Done(command, 0, "numpy>=1.24\nzarr>=3\n")
        if program == checks.OME_TIFF:
            if self.broken == "ome" and "zmart-for-coders" in command[0]:
                return Done(command, 1, "ModuleNotFoundError: No module named 'ome_types'\n")
            return self._ok({"channels": 2, "pixel_size_um": 0.5})
        if program == checks.VERSIONS:
            return self._ok({block: RELEASES.version(block) for block in command[command.index("-c") + 2:]})
        if program == checks.THE_WORKFLOWS:
            return self._ok({"folder": "x", "halves": ["target_acquisition"], "page": True})
        if program == checks.THE_BRIDGE:
            return self._ok({"page_bytes": 3_600_000, "listed": {"instruments": ["interface-mock"]}})
        if program == analysis.LOAD_THE_STEPS:
            failed = {"segment_watershed.py": "ModuleNotFoundError: skimage"} if (
                self.broken == "step" and any("segment_watershed" in part for part in command)) else {}
            return self._ok({"failed": failed, "gpu": None})
        if program == checks.THE_FOCUS:
            return self._ok({"state": "done", "peak_z_um": 108.0, "expected": 108.0, "error": None})
        if "jupyterlab" in text:
            return self._ok("4.4.0")
        return Done(command, 0, "")

    def _ok(self, said) -> Done:
        return Done(["stand-in"], 0, json.dumps(said) + "\n")


@pytest.fixture
def a_setup(tmp_path, monkeypatch, capsys):
    """Run setup_zmart.py on the stand-in computer; answer its exit code, report and what it said."""
    def run(*argv, broken=""):
        computers = []

        def shell(record):
            computers.append(AStandInComputer(record, broken))
            return computers[-1]

        monkeypatch.setattr(main, "LOCAL", tmp_path / "local")
        monkeypatch.setattr(layout, "BESIDE", the_clones(tmp_path / "beside"))
        monkeypatch.setattr(main, "Shell", shell)
        monkeypatch.setattr(main.conda, "find_conda", lambda: "/opt/conda/bin/conda")
        monkeypatch.setattr(starting, "desktop", lambda: None)
        code = main.main(list(argv))
        report = json.loads((tmp_path / "local" / "setup-report.json").read_text(encoding="utf-8"))
        return code, report, capsys.readouterr().out, computers[0]

    return run


def test_a_setup_that_works_says_zmart_is_ready(a_setup, tmp_path):
    code, report, said, computer = a_setup("--no-coder", "--microscope", "mock", "--no-cellpose")
    assert code == 0, said
    assert report["verdict"] == "ready"
    assert "ZMART is ready." in said
    assert (tmp_path / "local" / "setup.log").is_file()
    assert list((tmp_path / "local").glob("ZMART interface.*"))
    assert not list((tmp_path / "local").glob("Start *"))
    assert report["answers"] == {"coder": False, "microscope": "mock", "cellpose": False, "output_root": None}
    made = {cmd[-1] for cmd in computer.commands if cmd[1:3] == ["env", "create"]}
    assert "main.yml" in made and "classical.yml" in made and "cellpose.yml" not in made


def test_the_report_says_where_conda_is_and_makes_its_environments(a_setup):
    _code, report, _said, _computer = a_setup("--no-coder", "--microscope", "mock", "--no-cellpose")
    assert report["facts"]["conda"]["root_prefix"] == "/opt/conda"
    assert report["facts"]["conda"]["envs_dirs"] == ["/opt/conda/envs"]


def test_conda_is_found_where_conda_says_and_no_folder_is_guessed(tmp_path, monkeypatch):
    named = tmp_path / "named" / "conda.exe"
    named.parent.mkdir()
    named.write_text("")
    assert main.conda.find_conda({"CONDA_EXE": str(named)}) == str(named)

    # Without CONDA_EXE: the conda the running Python belongs to, by its own `conda info`
    root = tmp_path / "its own conda"
    program = root / ("Scripts/conda.exe" if main.conda.WINDOWS else "bin/conda")
    program.parent.mkdir(parents=True)
    program.write_text("")
    monkeypatch.setattr(main.conda, "_own_root", lambda python: root)
    assert main.conda.find_conda({}) == str(program)

    # A Python without conda, and none on the PATH: nothing, rather than a guess
    monkeypatch.setattr(main.conda, "_own_root", lambda python: None)
    monkeypatch.setattr(main.conda.shutil, "which", lambda name: None)
    assert main.conda.find_conda({}) is None
    assert not hasattr(main.conda, "LIKELY_PLACES")


def test_a_coder_gets_jupyterlab_and_the_notebooks(a_setup, tmp_path):
    code, report, said, _ = a_setup("--coder", "--microscope", "mock", "--no-cellpose")
    assert code == 0, said
    assert any("JupyterLab" in one["what"] for one in report["outcomes"])
    assert list((tmp_path / "local").glob("ZMART notebook.*"))
    assert "the coders' focus pipeline finds focus, end to end" in said
    assert report["facts"]["coder_environment"].endswith("zmart-for-coders")


def test_the_window_saves_its_runs_where_it_was_told(a_setup, tmp_path):
    code, report, said, _ = a_setup("--no-coder", "--microscope", "mock", "--no-cellpose",
                                    "--output-root", "D:/ZMART-data")
    assert code == 0, said
    assert report["answers"]["output_root"] == "D:/ZMART-data"
    start = next((tmp_path / "local").glob("ZMART interface.*")).read_text(encoding="utf-8")
    assert "--output-root D:/ZMART-data" in start


def test_a_setup_that_fails_names_the_part_and_hands_over_to_the_doctor(a_setup):
    code, report, said, _ = a_setup("--yes", broken="environment")
    assert code == 1
    assert "ZMART is NOT ready" in said
    assert "Read .claude/agents/zmart-install-doctor.md and follow it." in said
    failed = [one for one in report["outcomes"] if one["state"] == "did not work"]
    assert failed[0]["what"] == "the environment zmart-for-non-coders"
    assert "CondaHTTPError" in failed[0]["output"]


def test_a_clone_is_moved_to_the_release_unless_it_holds_changes_of_its_own(a_setup):
    code, report, said, computer = a_setup("--no-coder", "--microscope", "mock", "--no-cellpose")
    asked = [" ".join(map(str, cmd)) for cmd in computer.commands]
    assert any("checkout --quiet " + RELEASES.refs["zmart-interface"] in one for one in asked)

    code, report, said, computer = a_setup("--yes", broken="clone")
    assert code == 1
    failed = [one for one in report["outcomes"] if one["state"] == "did not work"]
    assert failed[0]["what"] == "ZMART-interface, next to ZMART Microscopy"
    assert "changes of its own" in failed[0]["found"]
    assert not any("checkout" in " ".join(map(str, cmd)) for cmd in computer.commands)


def test_both_environments_read_an_ome_tiffs_description(a_setup):
    code, report, said, _ = a_setup("--coder", "--microscope", "mock", "--no-cellpose")
    assert code == 0, said
    read = [one["what"] for one in report["outcomes"] if "reads an OME-TIFF" in one["what"]]
    assert read == ["zmart-for-non-coders reads an OME-TIFF's description",
                    "zmart-for-coders reads an OME-TIFF's description"]

    code, report, said, _ = a_setup("--coder", "--microscope", "mock", "--no-cellpose", broken="ome")
    assert code == 1
    failed = [one for one in report["outcomes"] if one["state"] == "did not work"]
    assert [one["what"] for one in failed] == ["zmart-for-coders reads an OME-TIFF's description"]


def test_an_environment_that_is_there_is_brought_up_to_its_file(tmp_path):
    from zmart_setup.record import Record

    record = Record(tmp_path / "local")
    computer = AStandInComputer(record)
    computer.environments[layout.CODER.name] = Path("/opt/conda/envs") / layout.CODER.name
    prefix = blocks.make_the_environment(computer, record, "conda", layout.CODER)
    assert prefix == computer.environments[layout.CODER.name]
    updated = [cmd for cmd in computer.commands if cmd[1:3] == ["env", "update"]]
    assert updated and str(layout.CODER.file) in updated[0]
    assert not [cmd for cmd in computer.commands if cmd[1:3] == ["env", "create"]]


def test_a_step_that_does_not_load_is_named(a_setup):
    code, report, said, _ = a_setup("--yes", broken="step")
    assert code == 1
    failed = [one for one in report["outcomes"] if one["state"] == "did not work"]
    assert any("segment_watershed.py" in one["found"] for one in failed), failed


def test_check_only_installs_nothing_and_remembers_the_answers(a_setup):
    a_setup("--coder", "--microscope", "mock", "--no-cellpose")
    code, report, said, computer = a_setup("--check", broken="environment")
    assert report["answers"]["coder"] is True  # remembered from the setup before
    assert not [cmd for cmd in computer.commands if cmd[1:3] == ["env", "create"]]
    assert "there is no 'zmart-for-non-coders' environment" in said
