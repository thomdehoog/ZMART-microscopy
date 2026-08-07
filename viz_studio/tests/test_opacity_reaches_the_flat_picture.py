"""Turning a channel down has to change the flat picture, and it did not.

The fault, measured on 6 August 2026 before anything was changed. With one channel
open the opacity slider moved, the number beside it moved, `layer.opacity` in the
engine held the new value -- and the picture was **18.61 grey levels at every
setting from 1.0 down to 0.1**. Not nearly the same: the same, to two decimal
places, because nothing about the drawing had changed at all.

Why, and it is neuroglancer's design rather than a bug in it. The bottom-most image
in a slice view is drawn with blending switched **off**
(`sliceview/volume/image_renderlayer.js:setGLBlendMode` -- `renderLayerNum > 0`), so
its alpha never blends with anything. The one place alpha is read afterwards is the
composite, which asks `sampledColor.a == 0.0` and paints the background where that
is true (`sliceview/frontend.js`, `SliceViewRenderHelper`). Alpha is therefore a
yes-or-no test for "was this imaged", and an opacity of 0.4 is just as much a yes as
1.0. **Anything that reaches the picture only through the alpha cannot dim the
bottom row**, whichever route it took to get there.

That rules out both of the fixes originally proposed, and each was measured rather
than argued:

Each cell is a mean over the middle of the panel, at opacity 1.0, 0.5 and 0.1. The
second column turns the *upper* of two channels down and reads the two colours
apart, so "top" is that channel's own brightness and "below" is how much of the
channel underneath comes through.

| what was tried | one channel: top | two channels: top | two channels: below |
| --- | --- | --- | --- |
| as it shipped | 18.61 / 18.61 / 18.61 | 7.02 / 3.50 / 0.68 | 0.90 / 9.75 / 16.84 |
| populate the shader's opacity control, into the alpha | 18.61 / 18.61 / 18.61 | 7.02 / 3.50 / 0.68 | 0.90 / 9.75 / 16.84 |
| `emitRGB`, letting `layer.opacity` be the alpha | 18.61 / 18.61 / 18.61 | 7.02 / 3.50 / 0.68 | **0.00** / 9.30 / 16.76 |
| opacity into the colour *only* | **18.61 / 9.30 / 1.85** | 7.02 / 3.50 / 0.68 | **0.90 / 0.90 / 0.90** |
| **opacity into the colour and the alpha** | **18.61 / 9.30 / 1.85** | 7.02 / 1.74 / 0.05 | 0.90 / 9.75 / 16.84 |

Read the "one channel" column downwards: both of the fixes originally proposed
leave it at 18.61 at all three settings, which is the same number rather than a
similar one, so neither of them touches the picture at all. Then read the last
column: `emitRGB` loses the coverage alpha and blacks out the row beneath at full
opacity, and putting opacity only in the colour leaves that row at 0.90 whatever
the slider is doing -- the upper channel fades to black over it instead of
revealing it. Only the last row does both jobs, and it is what is now in
`scene.js`.

**What the fix costs, stated plainly because it is a real cost.** On a row that is
*not* the bottom one, opacity now arrives twice -- once dimming the colour and once
as the alpha the engine blends with -- so such a row fades as opacity squared. At a
half it reads 1.74 where it used to read 3.50. The endpoints are exact and the
crossfade is monotonic, and what is underneath comes through exactly as before
(0.90 → 9.75 → 16.84, unchanged in the table above). No single shader can serve both
regimes: the bottom row can only be dimmed through its colour, and a row above it
can only reveal what is beneath through its alpha, and asking for both at once is
what produces the square. A control that works everywhere with a bend in it beats
one that does nothing at all on the commonest case there is -- a run with one
channel open.
"""

from __future__ import annotations

from pixels import image_middle

# How far down to turn a channel. Far enough that no threshold argument is needed
# and not so far that the picture is gone before the measurement.
TURNED_DOWN = 0.3


def _channels(page) -> list[str]:
    return page.evaluate("() => window.zmartConfig.layers.map((layer) => layer.name)")


def _set_range(page, label: str, value: float) -> None:
    page.locator(f"[aria-label='{label}']").evaluate(
        """(element, value) => {
          // React installs its own value setter on the element to track a
          // controlled input, so writing through the platform setter is what makes
          // the event that follows look like a real thumb being dragged.
          const setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, 'value'
          ).set;
          setter.call(element, String(value));
          element.dispatchEvent(new Event('input', { bubbles: true }));
        }""",
        value,
    )
    page.wait_for_timeout(1200)


def _choose(page, channel: str) -> None:
    """Pick a channel out, so the one shared block of controls acts on it."""
    page.locator(f"[aria-label='toggle {channel}']").locator("xpath=../..").click()
    page.wait_for_timeout(300)


def _brightness(page) -> float:
    return float(image_middle(page).mean())


def test_turning_the_only_channel_down_fades_the_picture(viewer_page):
    """The commonest case there is, and the one that was completely dead.

    Everything but one channel is hidden first, which is not a contrivance: it is
    what an overview scan looks like, and it is exactly the arrangement in which
    neuroglancer draws with blending off and the alpha stops meaning anything.
    """
    page = viewer_page
    channels = _channels(page)
    for hidden in channels[1:]:
        page.click(f"[aria-label='toggle {hidden}']")
    page.wait_for_timeout(1500)

    _choose(page, channels[0])
    _set_range(page, f"opacity {channels[0]}", 1.0)
    full = _brightness(page)
    _set_range(page, f"opacity {channels[0]}", TURNED_DOWN)
    turned_down = _brightness(page)

    assert full > 2.0, (
        f"the picture is only {full:.2f} grey levels bright at full opacity, so "
        "this compared two pictures of nothing"
    )
    assert turned_down < full * 0.6, (
        f"turning the only open channel down to {TURNED_DOWN} left the picture at "
        f"{turned_down:.2f} grey levels against {full:.2f} at full -- the slider "
        "is not reaching the drawing. The bottom-most image is drawn with "
        "blending off, so an opacity that travels only in the alpha is discarded; "
        "it has to reach the colour."
    )


def test_turning_a_channel_down_still_lets_the_one_beneath_show_through(viewer_page):
    """The property the fix must not cost, since one shader serves both regimes.

    Dimming the colour is what makes the bottom row work. Done on its own it would
    make every row above simply fade to black over whatever is beneath, which is
    the opposite of what an operator asks an opacity slider for. The alpha has to
    go on saying how much of what is underneath to let through, and this is the
    check that it does.
    """
    page = viewer_page
    channels = _channels(page)
    for hidden in channels[2:]:
        page.click(f"[aria-label='toggle {hidden}']")
    page.wait_for_timeout(1500)

    upper = channels[1]
    _choose(page, upper)
    _set_range(page, f"opacity {upper}", 1.0)
    covered = image_middle(page)
    _set_range(page, f"opacity {upper}", 0.1)
    revealed = image_middle(page)

    # The channels are drawn in different colours, so what the row underneath
    # contributes can be read off the picture without hiding anything: the band
    # the upper row does not paint in belongs to the lower one alone.
    beneath = [band for band in range(3)
               if revealed[:, :, band].mean() > covered[:, :, band].mean() + 1.0]
    assert beneath, (
        "turning the upper channel down did not brighten any colour band, so "
        "nothing of the channel beneath it came through -- the alpha has stopped "
        "saying how much to let past and the upper row is simply fading to black "
        f"over it (covered {covered.mean():.2f}, revealed {revealed.mean():.2f})"
    )
