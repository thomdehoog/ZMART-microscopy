"""Every piece of JavaScript this project generates must at least parse.

The page and the widgets are written as JavaScript inside Python strings. That
is a deliberate choice — it keeps everything offline, with no build step and
nothing fetched from the internet — but it costs one safety net that a normal
JavaScript project gets for free: nothing checks the code is even valid until
a browser tries to run it.

That matters here more than it would elsewhere. A stray bracket does not fail
a Python test, does not fail a linter, and does not fail on import. It reaches
the microscope PC, and the first thing to notice is an operator looking at a
page that will not start, in the middle of a session.

So these tests hand each generated piece to Node and ask only "does this
parse?". They do not run it and they cannot tell you it behaves correctly —
the real-browser tests in ``test_webapp_browser.py`` do that. This is the
cheap check that catches the mistake most easily made and most expensive to
discover late.

If Node is not installed the tests skip rather than fail: the canonical Conda
environment has it, and a contributor without it should not be blocked. That
does mean the gate is only as good as the environments it runs in — worth
remembering if a broken page ever gets through.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("anywidget")

from workflow import react as wreact  # noqa: E402
from workflow.webapp._page import page_html  # noqa: E402

_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="Node is not installed here")

#: Every widget whose browser code is generated. Named individually so a
#: failure says which panel of the interface is broken.
_WIDGETS = {
    "overview map": wreact.OverviewViewerReact,
    "focus picker": wreact.FocusPickerReact,
    "cell explorer": wreact.TargetExplorerReact,
    "acquisition gallery": wreact.AcquisitionGalleryReact,
    "run checklist": wreact.RunStatusReact,
}


def _check_parses(source: str, label: str, tmp_path: Path, module: bool = True) -> None:
    """Ask Node whether this source parses, and quote it if it does not."""
    suffix = ".mjs" if module else ".js"
    path = tmp_path / f"{label.replace(' ', '_')}{suffix}"
    path.write_text(source, encoding="utf-8")
    finished = subprocess.run(  # noqa: S603 -- our own file, our own interpreter
        [_NODE, "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert finished.returncode == 0, (
        f"the generated JavaScript for the {label} does not parse, so the page "
        f"would not start in a browser:\n{finished.stderr.strip()}"
    )


def _page_script(html: str) -> str:
    """The page's own script, lifted out of the HTML around it."""
    opening = html.index("<script type=\"module\">") + len("<script type=\"module\">")
    closing = html.index("</script>", opening)
    return html[opening:closing]


@_needs_node
@pytest.mark.parametrize("label", sorted(_WIDGETS))
def test_each_widget_the_operator_sees_parses(label, tmp_path):
    """One failure here names the panel that would not draw."""
    _check_parses(_WIDGETS[label]._esm, label, tmp_path)


@_needs_node
def test_the_page_itself_parses(tmp_path):
    """If this fails, the whole interface would come up blank."""
    _check_parses(_page_script(page_html()), "page", tmp_path)


@_needs_node
def test_the_shared_widget_groundwork_parses(tmp_path):
    """The React runtime and the hooks every widget is built on."""
    _check_parses(wreact._support.REACT_PRELUDE, "shared groundwork", tmp_path)


#: Ways a page or a module can actually go and get something. A web address
#: written inside ordinary text is not one of them — React's minified build
#: quotes a documentation link in an error message, and SVG markup names the
#: drawing standard by its address without ever visiting it.
_WAYS_OF_FETCHING = (
    'src="http',
    "src='http",
    'href="http',
    "href='http",
    'from "http',
    "from 'http",
    'import("http',
    'fetch("http',
    "@import url(http",
    "esm.sh",
    "unpkg.com",
    "jsdelivr",
    "//cdn.",
)


def _fetches_from_the_internet(source: str) -> list[str]:
    return [way for way in _WAYS_OF_FETCHING if way in source]


def test_the_page_carries_exactly_one_script_and_keeps_it_offline():
    """The page must stay self-contained, whether or not Node is here.

    Everything the page needs travels with it: no fonts, no scripts and no
    styles come from the internet, exactly as the notebooks promise. A
    microscope PC may well have no route out, and an interface that quietly
    depended on one would fail where it matters most.

    This check needs no Node, so it holds even where the parsing gate skips.
    """
    html = page_html()
    assert html.count("<script") == 1, "the page should carry one script, inline"
    opening_tag = html.split("<script", 1)[1].split(">", 1)[0]
    assert "src=" not in opening_tag, "the page's script must be inline, not fetched"
    assert not _fetches_from_the_internet(html), (
        f"the page reaches out to the internet: {_fetches_from_the_internet(html)}"
    )


def test_every_widget_keeps_its_react_with_it():
    """Widgets bring their own React rather than fetching one."""
    for label, widget in _WIDGETS.items():
        esm = widget._esm
        assert "react.production.min.js" in esm, f"the {label} lost its vendored React"
        reaching = _fetches_from_the_internet(esm)
        assert not reaching, f"the {label} fetches from the internet: {reaching}"
