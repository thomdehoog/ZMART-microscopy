"""Every action procedure the v4 flow calls must exist on the Leica adapter.

The end-to-end flow test runs against the controller's mock driver, and the
mock can quietly support procedures the real adapter does not. This guard
closes that gap without hardware: it collects every
``run_procedure({"name": ...})`` call in the notebook and in the active
workflow package, then asks the real Leica adapter (over the driver's mock
CAM client) which procedures it advertises, and requires the first set to be
contained in the second.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

_TARGET_ACQ = Path(__file__).resolve().parents[1]
_DRIVER_HELPERS = (
    _TARGET_ACQ.parents[1]
    / "zmart_drivers"
    / "leica"
    / "stellaris5_y42h93"
    / "navigator_expert"
    / "tests"
    / "helpers"
)
if str(_DRIVER_HELPERS) not in sys.path:
    sys.path.insert(0, str(_DRIVER_HELPERS))


def _name_in_dict(node: ast.AST) -> str | None:
    """The ``"name"`` value of a dict literal like ``{"name": "autofocus"}``."""
    if not isinstance(node, ast.Dict):
        return None
    for key, value in zip(node.keys, node.values, strict=True):
        if (
            isinstance(key, ast.Constant)
            and key.value == "name"
            and isinstance(value, ast.Constant)
        ):
            return value.value
    return None


def _procedure_names_in(tree: ast.AST) -> set[str]:
    """The ``{"name": ...}`` values that reach ``run_procedure`` calls.

    Handles both a dict literal passed directly and the common two-step
    pattern (``procedure = {"name": ...}`` then ``run_procedure(procedure)``)
    by remembering what each simple variable was assigned.
    """
    assigned: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            name = _name_in_dict(node.value)
            if isinstance(target, ast.Name) and name is not None:
                assigned[target.id] = name

    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if called != "run_procedure" or not node.args:
            continue
        arg = node.args[0]
        name = _name_in_dict(arg)
        if name is not None:
            names.add(name)
        elif isinstance(arg, ast.Name) and arg.id in assigned:
            names.add(assigned[arg.id])
    return names


def _flow_procedure_names() -> set[str]:
    """Every procedure name the notebooks or the workflow package call."""
    names: set[str] = set()
    for notebook_name in ("zmart_microscopy_v4.ipynb", "zmart_microscopy_v4_react.ipynb"):
        notebook = json.loads((_TARGET_ACQ / notebook_name).read_text(encoding="utf-8"))
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                names |= _procedure_names_in(ast.parse("".join(cell["source"])))
    for module in (_TARGET_ACQ / "workflow").rglob("*.py"):
        names |= _procedure_names_in(ast.parse(module.read_text(encoding="utf-8")))
    return names


@pytest.fixture(autouse=True)
def _leave_the_controller_registry_untouched():
    """Importing the Leica adapter registers it with the controller.

    That registration must not leak into other test modules (the controller's
    own suite picks ``get_instruments()[0]`` expecting its mock), so the
    registry is restored to whatever it held before this test ran.
    """
    from zmart_controller import registry

    before = dict(registry.REGISTRY)
    yield
    registry.REGISTRY.clear()
    registry.REGISTRY.update(before)


def test_flow_procedures_exist_on_the_leica_adapter():
    from mock_lasx_api import MockLasxClient
    from navigator_expert.zmart_adapter import zmart_adapter as adapter

    handle = adapter.ZmartHandle(
        client=MockLasxClient(latency=0.0), connection={}, hash6="guard0"
    )
    advertised = set(adapter.get_procedures(handle))

    used = _flow_procedure_names()
    # Sanity: the collector actually saw the flow's procedure calls, so an
    # empty set can never masquerade as a pass.
    assert "autofocus" in used

    missing = used - advertised
    assert not missing, (
        f"the notebook/workflow call procedures the Leica adapter does not "
        f"advertise: {sorted(missing)} (adapter offers {sorted(advertised)})"
    )
