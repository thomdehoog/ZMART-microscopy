"""Target acquisition's Python stands alone: of the framework it uses only the API.

A workflow is a folder dropped into ``workflows/``. Its Python half may lean
on what the bridge promises every half -- ``framework/bridge/api.py`` -- and
on nothing else of the framework, which could change under it, and on no
other workflow, which might not be there. Inside the folder its modules
import each other by relative paths, so the folder works under any name.
This reads every module of the folder, tests and their fixtures left out,
and refuses anything else.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from zmart_interface.framework.test_the_bridge_knows_no_workflow import imported_by

FOLDER = Path(__file__).resolve().parent
PACKAGE = "target_acquisition"
THE_API = "zmart_interface.framework.bridge.api"


def modules_of_the_workflow() -> list[Path]:
    return sorted(
        path for path in FOLDER.rglob("*.py")
        if not path.name.startswith("test_") and path.name != "conftest.py"
        and "__pycache__" not in path.parts and "fixtures" not in path.parts
    )


def written_out(path: Path) -> list[str]:
    """The interface modules a module names by their full name rather than relatively."""
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and not node.level and (node.module or "").startswith("zmart_interface"):
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names += [alias.name for alias in node.names if alias.name.startswith("zmart_interface")]
    return names


def test_there_are_modules_to_read():
    assert len(modules_of_the_workflow()) > 20


@pytest.mark.parametrize("path", modules_of_the_workflow(), ids=lambda path: path.relative_to(FOLDER).as_posix())
def test_a_module_uses_only_the_api_of_the_framework_and_nothing_of_another_workflow(path):
    names = imported_by(path, FOLDER, PACKAGE)
    reached = [
        name for name in names
        if name.startswith("zmart_interface") and not name.startswith(PACKAGE)
        and not name.startswith(THE_API) and name not in ("zmart_interface", "zmart_interface.framework",
                                                           "zmart_interface.framework.bridge")
    ]
    assert reached == [], f"{path.relative_to(FOLDER)} imports {reached}"


@pytest.mark.parametrize("path", modules_of_the_workflow(), ids=lambda path: path.relative_to(FOLDER).as_posix())
def test_a_module_reaches_its_own_folder_by_relative_paths(path):
    own = [name for name in written_out(path) if name.startswith(PACKAGE)]
    assert own == [], f"{path.relative_to(FOLDER)} names its own folder in full: {own}"
