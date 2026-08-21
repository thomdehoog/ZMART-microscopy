"""What the web page needs from the microscope controller, written down.

The page never talks to a microscope directly. Everything it does goes through
``zmart_controller``'s public ``Session``, and through the ``workflow.*``
functions the notebooks use. That is what lets one page drive a Leica today
and something else tomorrow without being rewritten.

The tests here guard that arrangement from both sides. They record exactly
which parts of a session the page leans on, so that renaming or removing one
during a controller refactor fails here — with a list of what the page still
expects — instead of failing at the microscope. And they check that the page
has not quietly reached past the controller to a driver.

Nothing in this file changes the controller or the drivers; it only reads
them. If a test here fails, the question to ask is whether the page should be
following the controller's new shape, or whether the controller has dropped
something the page still legitimately needs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytest.importorskip("anywidget")

from zmart_controller.layer import Session  # noqa: E402

_WEBAPP = Path(__file__).resolve().parents[1] / "workflow" / "webapp"

#: Everything the page asks a live session to do, and which step needs it.
#: This is the whole of the page's demand on a microscope.
_SESSION_CALLS_THE_PAGE_MAKES = {
    "set_origin": "step 2 — make the stage's current place the zero point",
    "get_state": "steps 3a and 3b — remember which job is selected",
    "set_state": "step 4 — restore the overview job before reading positions",
    "get_info": "step 4 — the run folder, the tile positions, the focus points",
    "disconnect": "step 9 — release the microscope",
}

#: Parts of ``get_info()`` and ``get_state()`` the page reads by name. These
#: are as much a part of the contract as the method names themselves.
_INFO_KEYS_THE_PAGE_READS = ("output_root", "tile_positions", "focus_positions")
_STATE_KEYS_THE_PAGE_READS = ("changeable",)


def _session_calls() -> set[str]:
    """Just the call names, without the reasons."""
    return set(_SESSION_CALLS_THE_PAGE_MAKES)


def test_the_controller_still_offers_everything_the_page_asks_of_it():
    """Every session call the page makes must exist on the real Session.

    This is the list to look at first when a controller refactor breaks the
    page: it is the complete set of things the run flow asks a microscope to
    do, and nothing more.
    """
    missing = sorted(name for name in _session_calls() if not hasattr(Session, name))
    assert not missing, (
        f"the controller no longer offers {missing}, which the web page calls; "
        "either the page should follow the new shape or the controller has "
        "dropped something it still needs"
    )


def test_the_page_asks_for_nothing_beyond_the_public_session():
    """The page must not depend on private controller internals.

    A name beginning with an underscore is the controller's own business and
    may change at any time. If the page needed one, that would be a sign the
    public surface is missing something — worth adding there rather than
    reaching around it.
    """
    private = sorted(name for name in _session_calls() if name.startswith("_"))
    assert not private, f"the page reaches into controller internals: {private}"


def test_the_page_never_reaches_past_the_controller_to_a_driver():
    """Only the controller knows about vendors; the page must not.

    The one driver-aware moment in the whole interface is the launcher
    importing the workflow bootstrap, which registers the Leica adapter. Every
    operation after that goes through the controller's public session. If a
    driver import appeared inside the page itself, swapping microscopes would
    mean rewriting the page.
    """
    offenders = []
    for path in sorted(_WEBAPP.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.startswith("zmart_drivers"):
                    offenders.append(f"{path.name}:{node.lineno} imports {name}")
    assert not offenders, "the page imported a driver directly: " + "; ".join(offenders)


def test_the_simulated_microscope_answers_the_same_calls_as_a_real_one():
    """Demo mode must exercise the same surface, or it proves nothing.

    The whole point of the demo is that a run behaves as it would on the
    microscope. If the simulation offered a different set of calls, a step
    could pass in demo and fail the moment it met real hardware.
    """
    from workflow._simulation import SimulatedSession

    missing = sorted(
        name for name in _session_calls() if not hasattr(SimulatedSession, name)
    )
    assert not missing, (
        f"the simulated microscope cannot answer {missing}, so demo mode no "
        "longer proves the live path works"
    )


def test_the_pieces_of_a_session_the_page_reads_by_name_are_still_there(tmp_path):
    """The page reads particular fields out of the microscope's answers.

    ``get_info()`` supplies where the run saves, where the overview tiles are,
    and where the focus points are; ``get_state()`` carries the selected job
    under ``changeable``. Renaming any of them would break the page just as
    surely as removing a method, so they are named here too.
    """
    from workflow._simulation import SimulatedSession

    session = SimulatedSession(tmp_path / "run")
    try:
        info = session.get_info()
        for key in _INFO_KEYS_THE_PAGE_READS:
            assert key in info, f"get_info() no longer carries {key!r}"

        state = session.get_state()
        for key in _STATE_KEYS_THE_PAGE_READS:
            assert key in state, f"get_state() no longer carries {key!r}"
        assert "job" in state["changeable"], "the selected job is how the two jobs are told apart"
    finally:
        session.disconnect()


def test_choosing_a_job_is_only_ever_asked_of_the_simulation():
    """Selecting a job belongs to LAS X, not to the controller.

    On a real microscope the operator picks the job in LAS X and the page only
    reads back what was selected; the real session has no ``select_job`` at
    all. The simulation offers one so the demo can stand in for that hand
    movement, and the flow must ask for it only when it is simulating.
    """
    assert not hasattr(Session, "select_job"), (
        "the real session grew a select_job; the page's demo-only guard around "
        "it should be revisited"
    )

    source = (_WEBAPP / "_flow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.split("\n")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not (isinstance(function, ast.Attribute) and function.attr == "select_job"):
            continue
        # Every such call must sit under a plain `if self.demo:` test.
        enclosing = "\n".join(lines[max(0, node.lineno - 3) : node.lineno])
        assert "if self.demo" in enclosing, (
            f"_flow.py:{node.lineno} selects a job outside demo mode, which a "
            "real session cannot do"
        )
