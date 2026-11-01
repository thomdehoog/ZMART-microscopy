"""The page draws with the ZMART viewer's drawing rules, not with copies of them.

The shader programs that turn a stored value into a colour, and the edits that
keep an image's transparency in neuroglancer, are the viewer's. This page used
to keep copies, aligned by hand, and they drifted. Now the build takes them
from the installed viewer (``tools/the-installed-viewer.mjs``), and these tests keep
a copy from coming back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import zmart_viewer

import zmart_interface

#: The checkout of the ZMART interface whose build makes the page: where the
#: installed interface was installed from (``pip install -e``). Its build tools
#: are checked here. This workflow may sit in another repository, so the
#: checkout is found through the interface, not beside this file.
CHECKOUT = Path(zmart_interface.__file__).resolve().parents[1]
#: The viewer's declarations of its drawing code, as committed here for the type checker.
DECLARATIONS = Path(__file__).resolve().parent / "engines" / "zmart-viewer-drawing"
#: The neuroglancer engine, written in JavaScript or, once converted, TypeScript.
ENGINE = next(
    path for path in (Path(__file__).resolve().parent / "engines" / "neuroglancer-under").glob("viewer.*")
    if path.suffix in (".js", ".ts")
)

#: The checks of the build's own files need the interface's checkout, which an
#: interface installed from GitHub does not have.
needs_the_checkout = pytest.mark.skipif(
    not (CHECKOUT / "tools" / "the-installed-viewer.mjs").is_file(),
    reason="the ZMART interface is installed as a package here, not from a checkout",
)


@needs_the_checkout
def test_the_installed_viewer_offers_what_the_build_reads():
    drawing = Path(zmart_viewer.__file__).parent / "drawing"
    shared = re.search(r"THE_SHARED_DRAWING_FILES = \[(.*?)\];",
                       (CHECKOUT / "tools/the-installed-viewer.mjs").read_text(encoding="utf-8"), re.S)
    assert shared, "tools/the-installed-viewer.mjs names no shared drawing files"
    names = re.findall(r'"([^"]+)"', shared[1])
    assert "primitives/viewer.ts" in names, names
    for name in names:
        assert (drawing / name).is_file(), f"the installed viewer has no {name}"


def test_the_engine_keeps_no_shader_program_of_its_own():
    source = ENGINE.read_text(encoding="utf-8")
    assert 'from "zmart-viewer/drawing/programs.js"' in source
    assert "#uicontrol" not in source.replace(
        "#uicontrol invlerp covered", ""  # the coverage mask is this page's own
    ), "a shader program is written out here again; take it from the viewer's programs.js"


@needs_the_checkout
def test_the_patch_keeps_only_what_the_viewer_does_not_offer():
    patch = (CHECKOUT / "patches/neuroglancer+2.41.2.patch").read_text(encoding="utf-8")
    changed = [line.split(" b/", 1)[1] for line in patch.splitlines() if line.startswith("diff --git ")]
    assert changed == ["node_modules/neuroglancer/lib/chunk_manager/frontend.js"], changed
    assert "transparentBackground" not in patch


@needs_the_checkout
def test_the_installed_viewer_is_the_pinned_one():
    """The page is built with the viewer release ``pyproject.toml`` names, and no other.

    The build takes the viewer's drawing files from the installed viewer, so a
    different viewer builds a different page. The build itself stops when they
    differ (``tools/the-installed-viewer.mjs``); this says so before the build is run.
    """
    pinned = re.search(
        r'"zmart-viewer @ git\+https://github\.com/ZMB-UZH/ZMART-viewer@v([^"]+)"',
        (CHECKOUT / "pyproject.toml").read_text(encoding="utf-8"),
    )
    assert pinned, "pyproject.toml does not pin zmart-viewer to a release tag"
    assert zmart_viewer.__version__ == pinned[1], (
        f"the installed viewer is {zmart_viewer.__version__}, the pinned one {pinned[1]}"
    )


def test_the_committed_declarations_are_the_installed_viewers():
    """The checker reads the viewer's drawing code by a copy of the declarations it writes.

    The type checker runs where no viewer is installed, so the interface keeps
    the viewer's declarations (``drawing/declarations``) committed, and the
    build takes the code itself from the installed viewer. This holds the two
    equal, as the pin holds the versions: a viewer that changes what its drawing
    code offers is a different copy here, written on purpose.
    """
    installed = Path(zmart_viewer.__file__).parent / "drawing" / "declarations"

    def files(folder: Path) -> dict[str, str]:
        return {
            path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(folder.rglob("*.d.ts"))
        }

    ours, theirs = files(DECLARATIONS), files(installed)
    assert sorted(ours) == sorted(theirs), (
        "the committed declarations name other files than the installed viewer's; "
        f"copy {installed} to {DECLARATIONS}"
    )
    differ = [name for name in ours if ours[name] != theirs[name]]
    assert not differ, f"these differ from the installed viewer's, copy them again: {differ}"
