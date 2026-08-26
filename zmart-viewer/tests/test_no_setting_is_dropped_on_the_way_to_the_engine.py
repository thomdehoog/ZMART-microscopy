"""Every setting the panel describes has to reach the live layer, and none does by itself.

This is a guard against a **class** of fault rather than any one instance of it,
and the class is worth naming because it has now produced three dead controls in a
single afternoon -- the flat opacity slider, the volume gain, and gain again in a
projection. Each one looked perfectly alive: the slider moved, the number beside it
changed, the panel's own state held the new value, and nothing at all happened on
screen.

The shape of the fault is always the same. `scene.js` turns the panel's state into a
plain description of a layer, and `engine.js:applySettings` writes that description
onto the layer neuroglancer is already drawing. Nothing in `applySettings` restores a
whole description; **every field is carried across by a line of its own**. So a field
added to `scene.js` and not to that list is dropped, silently, on every layer that
already exists -- which is every layer the operator ever adjusts. It works on a layer
that has just been built, because building goes through `makeLayer` with the whole
description, and that is precisely what makes it hard to see: switch to the volume and
back and the control appears to work for a moment.

So this test does not check any particular control. It asks the running page what
fields a description actually contains, and requires that each one be **accounted
for**: either known to be carried by hand -- in which case it is proved to be carried,
by moving it on the live layer and watching the next pass put it back -- or listed
below as something settled when the layer is built. A field that is neither fails the
run, with a message saying what to do about it. That is the part that catches the
*next* one.

**Why the proof is a perturbation rather than a comparison.** The obvious test is to
read the description and check the layer agrees with it. That is what would have been
written, and it would have passed while the gain was dead: the description said gain
nought and the engine's own default is nought, so the two agreed and nothing was
reaching the layer. A control is only dead in the direction the operator moves it. So
each field is moved to a value the engine is definitely not already holding, the
perturbation is confirmed to have taken -- vary it and check the input really moved --
and only then is the layer asked to catch up.

Mask layers are not covered here. Nothing the demo serves produces one, and a test
that silently examined nothing would be worse than no test; the fields a mask
description carries are listed below so the accounting still reads as a whole.
"""

from __future__ import annotations

import pytest

# What each field of an image description is called on the live layer: how to read
# it, and how to move it somewhere the engine is certainly not already sitting.
#
# This map is the checklist. It is meant to be edited when a field is added -- that
# is the whole point of it, and the test below refuses to pass until it has been.
# Each entry is a pair of small functions given the *managed* layer, since two of
# these live on the wrapper rather than on the layer itself.
CARRIED_BY_HAND = {
    "visible": (
        "(managed) => managed.visible",
        "(managed) => managed.setVisible(!managed.visible)",
    ),
    "shader": (
        "(managed) => managed.layer.fragmentMain.value",
        # A valid program that is certainly not the one the panel asked for. It
        # still declares `normalized`, so the shader controls beside it stay
        # meaningful while this is in place.
        "(managed) => { managed.layer.fragmentMain.value = "
        "'#uicontrol invlerp normalized\\n"
        "void main() { emitRGBA(vec4(1.0, 0.0, 0.0, 1.0)); }'; }",
    ),
    "shaderControls": (
        "(managed) => JSON.stringify(managed.layer.shaderControlState.toJSON())",
        "(managed) => managed.layer.shaderControlState.restoreState("
        "{ normalized: { range: [11, 12] } })",
    ),
    "opacity": (
        "(managed) => managed.layer.opacity.value",
        "(managed) => { managed.layer.opacity.value = 0.123; }",
    ),
    # How a row meets the rows beneath it: added to them, or covering them.
    # Neuroglancer numbers these DEFAULT 0 and ADDITIVE 1, so this lands on
    # whichever the panel did not ask for.
    "blend": (
        "(managed) => managed.layer.blendMode.value",
        "(managed) => managed.layer.blendMode.restoreState("
        "managed.layer.blendMode.value === 1 ? 'default' : 'additive')",
    ),
    "volumeRendering": (
        "(managed) => managed.layer.volumeRenderingMode.value",
        # Neuroglancer numbers these OFF 0, ON 1, MAX 2, MIN 3, so this lands on
        # something different whichever one the panel chose.
        "(managed) => managed.layer.volumeRenderingMode.restoreState("
        "managed.layer.volumeRenderingMode.value === 3 ? 'max' : 'min')",
    ),
    "volumeRenderingDepthSamples": (
        "(managed) => managed.layer.volumeRenderingDepthSamplesTarget.value",
        # Both of these sit well inside the range the engine will accept, so this
        # cannot fail by being clamped back to where it started.
        "(managed) => { managed.layer.volumeRenderingDepthSamplesTarget.value = "
        "managed.layer.volumeRenderingDepthSamplesTarget.value === 128 ? 256 : 128; }",
    ),
    "volumeRenderingGain": (
        "(managed) => managed.layer.volumeRenderingGain.value",
        "(managed) => { managed.layer.volumeRenderingGain.value = 2.5; }",
    ),
    # A mask is drawn by a different kind of layer and has no brightness to set;
    # how strongly it is painted over the image is all there is. Listed for the
    # accounting rather than exercised -- see the note at the top.
    "selectedAlpha": (
        "(managed) => managed.layer.displayState.selectedAlpha.value",
        "(managed) => { managed.layer.displayState.selectedAlpha.value = 0.123; }",
    ),
    "notSelectedAlpha": (
        "(managed) => managed.layer.displayState.notSelectedAlpha.value",
        "(managed) => { managed.layer.displayState.notSelectedAlpha.value = 0.123; }",
    ),
}

# Fields that are settled when the layer is built and never adjusted afterwards, so
# there is nothing for `applySettings` to carry and nothing here to prove.
#
# Each of these is genuinely fixed for the life of a layer rather than merely
# untested. `type` and `name` identify the layer -- a change in either builds a new
# one. `source` and `frameCounts` are the images the layer reads and are handled by
# `syncSources`, which only ever adds; a position is never quietly removed. And
# `localPosition` pins which channel inside a shared store this row shows, which is
# decided by the acquisition rather than by anything the operator can turn.
SETTLED_WHEN_THE_LAYER_IS_BUILT = {
    "type",
    "name",
    "source",
    "frameCounts",
    "localPosition",
}


def _image_descriptions(page) -> list[dict]:
    """The descriptions the panel last handed the engine, image layers only.

    Read off the running page rather than listed here, because a list written down
    is exactly the thing that goes out of date without saying so.
    """
    return page.evaluate(
        """() => (window.zmartScene || [])
             .filter((spec) => spec.type === 'image')
             .map((spec) => Object.fromEntries(
               Object.entries(spec).filter(([, value]) => value !== undefined),
             ))""",
    )


def _on_layer(page, index: int, body: str):
    """Run one of the small functions above against the index-th image layer."""
    return page.evaluate(
        "(index) => (" + body + ")("
        "  window.zmartViewer.layerManager.managedLayers"
        "    .filter((managed) => managed.layer && managed.layer.type === 'image')[index])",
        index,
    )


def _make_the_panel_speak_again(page, channel: str) -> None:
    """Get the panel to hand the engine a fresh description of the same scene.

    Hiding a channel and showing it again is the smallest thing an operator can do
    that ends where it started while still going all the way round: the panel's own
    state changes, so a new description is built and written onto the layers that
    are already there. Nothing is rebuilt, which is the case that matters -- the
    fault this file guards against only bites a layer that already exists.
    """
    page.click(f"[aria-label='toggle {channel}']")
    page.wait_for_timeout(400)
    page.click(f"[aria-label='toggle {channel}']")
    page.wait_for_timeout(900)


def _channels(page) -> list[str]:
    return page.evaluate("() => window.zmartConfig.layers.map((layer) => layer.name)")


@pytest.fixture(params=["flat", "volume"])
def viewer_in_both_views(request, viewer_page):
    """The viewer in each of its two views, because they describe different fields.

    A flat layer carries an opacity and no projection; a volume carries a
    projection, a sample count and a gain and no opacity. Neither view alone sees
    the whole of what `scene.js` writes, and the fields only one of them has are
    exactly the ones that have been found dead.
    """
    if request.param == "volume":
        viewer_page.click("text=3D")
        viewer_page.wait_for_timeout(4000)
    return viewer_page


def test_every_field_of_a_description_is_accounted_for(viewer_in_both_views):
    """A field nobody has thought about must stop the run, not be ignored.

    This is the half that catches the next dead control rather than the last three.
    """
    described = _image_descriptions(viewer_in_both_views)
    assert described, "no image layer was described, so this test examined nothing"
    fields: set[str] = set()
    for spec in described:
        fields |= set(spec)
    unaccounted = fields - set(CARRIED_BY_HAND) - SETTLED_WHEN_THE_LAYER_IS_BUILT
    assert not unaccounted, (
        f"scene.js now puts {sorted(unaccounted)} into an image description and "
        "this test has never heard of it. That is not a complaint about the "
        "field -- it is the check that engine.js:applySettings was given a line "
        "for it, because nothing there restores a whole description and a field "
        "with no line of its own is dropped in silence on every layer that "
        "already exists. Either add it to CARRIED_BY_HAND with a way to read and "
        "move it, or to SETTLED_WHEN_THE_LAYER_IS_BUILT if it genuinely cannot "
        "change once the layer exists."
    )


def test_every_field_that_is_carried_by_hand_really_arrives(viewer_in_both_views):
    """Move each setting on the live layer, and watch the next pass put it back.

    Failure here means `engine.js` is not carrying that field: the panel says one
    thing, the layer holds another, and the control it belongs to is dead.
    """
    page = viewer_in_both_views
    described = _image_descriptions(page)
    channel = _channels(page)[0]
    carried = [field for field in CARRIED_BY_HAND if field in described[0]]
    assert carried, "the first image layer described no adjustable setting at all"

    for field in carried:
        read, move = CARRIED_BY_HAND[field]
        asked_for = _on_layer(page, 0, read)
        _on_layer(page, 0, move)
        page.wait_for_timeout(300)
        moved = _on_layer(page, 0, read)
        # The check that would have caught all three of the afternoon's wrong
        # diagnoses: confirm the thing being varied is the thing being read,
        # before drawing any conclusion from it not changing.
        assert moved != asked_for, (
            f"{field} did not move when this test moved it, so the rest of this "
            "check would have proved nothing. The way it is read and the way it "
            "is written are probably not the same place."
        )

        _make_the_panel_speak_again(page, channel)
        after = _on_layer(page, 0, read)
        assert after == asked_for, (
            f"the panel described {field} as {asked_for!r} and the live layer "
            f"still holds {moved!r} after being told again, so engine.js is not "
            f"carrying it. Every field is written onto the layer by a line of its "
            f"own in applySettings, and {field} has no line -- which is what a "
            "control wired to nothing looks like from here."
        )
