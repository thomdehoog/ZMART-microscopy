"""Which renderer drew the picture, and saying so out loud.

Every frame measurement in this repository until 6 August 2026 forced software
drawing -- `--use-gl=angle --use-angle=swiftshader` -- so that a machine with a
graphics card and one without could be compared. That is right for a regression
guard and wrong for telling anybody what their own machine does, and because the
flags were buried in a list of launch arguments, a whole afternoon of numbers was
quoted as "this machine" when it meant "a CPU rasteriser on this machine".

So the card is now the default and software is the fallback, and which one was
used is reported rather than assumed. The reporting is the point: a measurement
that quietly falls back to software looks exactly like one that did not, and the
figures differ by more than tenfold.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from measure_the_frame_rate_of_a_linked_view import (  # noqa: E402
    BROWSER_ARGS,
    SOFTWARE_ARGS,
    is_drawn_in_software,
)

# Real strings, taken from this machine on 6 August 2026.
A_CARD = "ANGLE (NVIDIA, NVIDIA T400 4GB (0x00001FF2) Direct3D11 vs_5_0 ps_5_0, D3D11)"
SWIFTSHADER = ("ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) "
               "(0x0000C0DE)), SwiftShader driver)")


def test_a_real_card_is_not_called_software():
    assert not is_drawn_in_software(A_CARD)


def test_swiftshader_is_recognised():
    assert is_drawn_in_software(SWIFTSHADER)


def test_the_other_software_renderers_are_recognised():
    """Mesa's and Windows' own, which appear on machines with no usable driver."""
    assert is_drawn_in_software("Mesa/X.org, llvmpipe (LLVM 15.0.7, 256 bits)")
    assert is_drawn_in_software("Microsoft Basic Render Driver")
    assert is_drawn_in_software("Software Rasterizer")


def test_it_does_not_depend_on_how_the_driver_capitalised_itself():
    assert is_drawn_in_software("SWIFTSHADER DEVICE")
    assert is_drawn_in_software("LLVMpipe")


def test_a_renderer_that_will_not_say_is_not_claimed_to_be_software():
    """Some browsers mask this. Unknown must not be reported as a known answer.

    Saying "software" here would be a guess dressed as a measurement, and saying
    it of a machine that has a card would send somebody looking for a fault that
    is not there. The raw string is printed either way, so a reader can see that
    the question went unanswered.
    """
    assert not is_drawn_in_software("(masked)")
    assert not is_drawn_in_software("")


def test_the_default_arguments_do_not_force_software():
    """The change itself, pinned. These flags are what hid the fallback before."""
    assert "--use-angle=swiftshader" not in BROWSER_ARGS
    assert "--use-gl=angle" not in BROWSER_ARGS


def test_the_fallback_still_asks_for_software_explicitly():
    assert "--use-angle=swiftshader" in SOFTWARE_ARGS


def test_both_sets_keep_the_frame_rate_uncapped():
    """Whichever draws, the ceiling stays off, or the frames measure the clock."""
    for args in (BROWSER_ARGS, SOFTWARE_ARGS):
        assert "--disable-gpu-vsync" in args
        assert "--disable-frame-rate-limit" in args
