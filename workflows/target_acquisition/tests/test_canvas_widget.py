"""The layered canvas: one view, many layers, and where the sample shows through.

The canvas exists so that everything drawn about a slide — the imagery, the
carrier it sits in, the scan fields, the focus points, a heat map — shares one
view and can never drift apart. These tests hold that promise to account, and
guard the arrangement that lets a different image engine be plugged in
underneath later instead of everything above it being rewritten.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

pytest.importorskip("anywidget")

from workflow import react as wreact  # noqa: E402


def _canvas():
    """A canvas shaped like a real one: an engine slot, fields, focus points."""
    return wreact.canvas(
        [
            {"kind": "engine", "id": "engine", "label": "image engine"},
            {
                "kind": "shapes",
                "id": "carrier",
                "label": "carrier",
                "shapes": [{"bounds": [0, 0, 100, 60], "stroke": "#888"}],
            },
            {
                "kind": "shapes",
                "id": "fields",
                "label": "scan fields",
                "interactive": True,
                "shapes": [
                    {"bounds": [0, 0, 20, 20]},
                    {"bounds": [20, 0, 20, 20]},
                    {"bounds": [40, 0, 20, 20]},
                ],
            },
            {
                "kind": "points",
                "id": "focus",
                "label": "focus points",
                "dimmable": False,
                "interactive": True,
                "points": [{"x": 10.0, "y": 10.0}],
            },
        ]
    )


def test_every_layer_is_given_the_three_choices_it_has_to_make():
    """A caller says what a layer is; the rest is filled in sensibly."""
    canvas = _canvas()
    by_id = {layer["id"]: layer for layer in canvas.layers}

    assert set(by_id) == {"engine", "carrier", "fields", "focus"}
    for layer in canvas.layers:
        assert {"visible", "opacity", "dimmable", "interactive"} <= set(layer)
        assert layer["visible"] is True


def test_the_bottom_layer_never_follows_the_shared_fade():
    """The thing being looked at is not one of the things drawn over it.

    An image engine drawing with the graphics card cannot be made
    see-through, and the imagery is what the fade exists to reveal. Both
    follow from the same rule rather than being special cases.
    """
    canvas = _canvas()
    by_id = {layer["id"]: layer for layer in canvas.layers}
    assert by_id["engine"]["dimmable"] is False

    pictures = wreact.canvas([{"kind": "images", "id": "tiles"}])
    assert pictures.layers[0]["dimmable"] is False

    # ...while the things drawn over the top do follow it by default.
    assert by_id["carrier"]["dimmable"] is True
    assert by_id["fields"]["dimmable"] is True


def test_hand_worked_layers_can_opt_out_of_the_fade():
    """Fading to see the sample must not fade what you are placing on it."""
    canvas = _canvas()
    focus = next(la for la in canvas.layers if la["id"] == "focus")
    assert focus["dimmable"] is False, "focus points would vanish as you dimmed to see the sample"
    assert focus["interactive"] is True, "focus points have to be clickable"


def test_fading_and_being_clickable_are_separate_questions():
    """Readable and clickable are different axes, deliberately.

    A heat map is there to be read, not clicked. If making it legible also
    made it accept clicks, it would silently swallow every attempt to place a
    focus point underneath it.
    """
    canvas = wreact.canvas(
        [{"kind": "shapes", "id": "heat", "opacity": 0.6, "dimmable": True, "interactive": False}]
    )
    heat = canvas.layers[0]
    assert heat["dimmable"] is True and heat["interactive"] is False


def test_a_layer_can_be_switched_off_and_on_again():
    """Off means not drawn at all, so it costs nothing and swallows nothing."""
    canvas = _canvas()
    canvas.show_layer("carrier", False)
    assert next(la for la in canvas.layers if la["id"] == "carrier")["visible"] is False

    canvas._route_message(None, {"type": "toggle", "id": "carrier"}, None)
    assert next(la for la in canvas.layers if la["id"] == "carrier")["visible"] is True

    # Switching one layer must leave every other layer exactly as it was.
    assert [la["visible"] for la in canvas.layers] == [True, True, True, True]


def test_the_shared_dial_stays_between_nothing_and_solid():
    """The dial is a proportion, and anything else is refused rather than used."""
    canvas = _canvas()
    canvas._route_message(None, {"type": "dim", "value": 0.4}, None)
    assert canvas.dim == pytest.approx(0.4)

    canvas._route_message(None, {"type": "dim", "value": 5.0}, None)
    assert canvas.dim == 1.0
    canvas._route_message(None, {"type": "dim", "value": -2.0}, None)
    assert canvas.dim == 0.0

    canvas.dim = 0.5
    for rubbish in ("half", None, float("nan"), float("inf")):
        canvas._route_message(None, {"type": "dim", "value": rubbish}, None)
        assert canvas.dim == pytest.approx(0.5), f"{rubbish!r} moved the dial"


def test_the_dial_and_the_map_are_separate_controls():
    """One fades everything that follows it; the other says where.

    They are meant to be used together — dim the whole overlay to judge the
    imagery, and cut a window where a particular thing needs looking at — so
    setting one must never disturb the other.
    """
    canvas = _canvas()
    canvas.dim = 0.3
    canvas.see_through([{"shape": "rect", "bounds": [0, 0, 20, 20], "opacity": 0.0}])
    assert canvas.dim == pytest.approx(0.3), "opening a window moved the shared dial"
    assert canvas.opacity_map["kind"] == "regions"

    canvas.dim = 1.0
    assert canvas.opacity_map["kind"] == "regions", "the dial erased the window"


def test_the_window_is_given_on_the_sample_not_on_the_screen():
    """A see-through area must stay over the same piece of sample.

    Panning and zooming move the view, not the sample. If the window were
    given in screen pixels it would slide across the slide like a hole cut in
    the screen, which is useless for looking at one particular well.
    """
    canvas = _canvas()
    canvas.see_through([{"shape": "rect", "bounds": [40.0, 0.0, 20.0, 20.0], "opacity": 0.0}])
    before = canvas.opacity_map["regions"][0]["bounds"]

    canvas.look_at(500.0, -300.0, scale=4.0)
    assert canvas.camera["cx"] == 500.0 and canvas.camera["cy"] == -300.0
    assert canvas.camera["scale"] == 4.0
    assert canvas.opacity_map["regions"][0]["bounds"] == before, (
        "moving the view moved the window, so it is in screen coordinates"
    )


def test_showing_the_sample_through_chosen_scan_fields():
    """The usual request is "let me see under these fields", not a drawn box."""
    canvas = _canvas()
    canvas.see_through_fields("fields", [0, 2], opacity=0.0)

    regions = canvas.opacity_map["regions"]
    assert [r["bounds"] for r in regions] == [[0, 0, 20, 20], [40, 0, 20, 20]]
    assert all(r["opacity"] == 0.0 for r in regions)
    assert canvas.opacity_map["outside"] == 1.0


def test_showing_the_sample_through_every_field_at_once():
    """Leaving the choice out means all of them."""
    canvas = _canvas()
    canvas.see_through_fields("fields", opacity=0.25, outside=0.9)
    regions = canvas.opacity_map["regions"]
    assert len(regions) == 3
    assert all(r["opacity"] == 0.25 for r in regions)
    assert canvas.opacity_map["outside"] == 0.9


def test_asking_for_fields_that_are_not_there_is_refused():
    """A field number that does not exist is a mistake worth hearing about."""
    canvas = _canvas()
    with pytest.raises(ValueError, match="no field 9"):
        canvas.see_through_fields("fields", [9])
    with pytest.raises(ValueError, match="no 'nowhere' layer"):
        canvas.see_through_fields("nowhere")


def test_making_everything_solid_again():
    """Clearing the window is one call, not a fiddle with regions."""
    canvas = _canvas()
    canvas.see_through_fields("fields")
    canvas.see_through(None)
    assert canvas.opacity_map == {"kind": "none"}


def test_a_new_layer_can_be_slid_into_the_stack():
    """Order is what makes a stack; a heat map may need to sit under the points."""
    canvas = _canvas()
    canvas.add_layer({"kind": "shapes", "id": "heat", "opacity": 0.5}, above="fields")
    order = [layer["id"] for layer in canvas.layers]
    assert order == ["engine", "carrier", "fields", "heat", "focus"]

    canvas.add_layer({"kind": "shapes", "id": "notes"})
    assert [layer["id"] for layer in canvas.layers][-1] == "notes"


def test_a_watching_view_cannot_move_everyone_elses_picture():
    """The view is shared, so a locked view must not drag it about.

    Every open view shows the same camera. If a watching view could pan, it
    would pan the operator's picture out from under them mid-run.
    """
    canvas = _canvas()
    canvas.look_at(10.0, 20.0)
    canvas.make_read_only()

    canvas.camera = {"cx": 999.0, "cy": 999.0, "scale": 50.0}
    assert canvas.camera["cx"] == 10.0, "a locked view moved the shared picture"


def test_a_message_the_canvas_does_not_know_is_said_out_loud():
    canvas = _canvas()
    canvas._route_message(None, {"type": "fly_to_the_moon"}, None)
    assert "unknown message" in canvas.status


def test_a_window_reaches_all_the_way_down_by_default():
    """A window exists to reveal the imagery, not the next layer down.

    Cutting a hole in one layer alone would show whatever is drawn beneath
    it — the scan fields, the heat map — rather than the sample. So by
    default the window goes through everything above the bottom layer at
    once, and what shows through is the picture.
    """
    canvas = _canvas()
    assert canvas.window_reaches == "all"

    esm = wreact.CanvasReact._esm
    # The bottom layer is what the window reveals, so it is never cut.
    assert 'windowReaches === "all" ? (layer.id || 0) !== baseId' in esm
    assert "cutsThrough(layer) && mask" in esm


def test_a_window_can_be_told_to_leave_chosen_layers_alone():
    """Sometimes something should stay over the window on purpose.

    The carrier outline is the usual case: keeping it solid inside the window
    means the operator can still see which well they are looking at while the
    sample shows through everything else.
    """
    canvas = _canvas()
    canvas.window_reaches = "chosen"
    canvas.set_layer("carrier", windowed=False)

    carrier = next(la for la in canvas.layers if la["id"] == "carrier")
    assert carrier["windowed"] is False
    assert carrier["dimmable"] is True, (
        "keeping a layer out of the window should not also take it out of the dial"
    )


def test_following_the_dial_and_being_cut_by_the_window_are_separate():
    """Two questions, usually the same answer, occasionally not."""
    canvas = wreact.canvas(
        [
            {"kind": "images", "id": "tiles"},
            {"kind": "shapes", "id": "outline", "dimmable": True, "windowed": False},
        ]
    )
    outline = canvas.layers[1]
    assert outline["dimmable"] is True and outline["windowed"] is False

    # Left unsaid, a layer is cut by the window exactly when it follows the dial.
    plain = wreact.canvas([{"kind": "shapes", "id": "heat"}]).layers[0]
    assert plain["windowed"] == plain["dimmable"] is True


def test_a_window_can_only_make_a_layer_fainter_never_more_solid():
    """The dial, the layer's own setting and the window multiply together.

    Each of the three can only take solidity away, so no combination of them
    can make a layer more solid than the operator asked for. This falls out of
    putting the layer's own setting and the window on the same element, where
    the browser multiplies them — worth pinning, because separating them later
    would quietly let a window make something darker than its own setting.
    """
    esm = wreact.CanvasReact._esm
    layer_element = esm[esm.index("shown.map((layer, i) =>") : esm.index("h(LayerBody")]
    assert "opacity: solidity(layer, dim)" in layer_element
    assert "cutsThrough(layer) && mask" in layer_element, (
        "the window must sit on the same element as the opacity, so they multiply"
    )

    # And solidity itself is bounded, whatever the traits say.
    assert "Math.max(0, Math.min(1, own * shared))" in esm


def test_the_window_applies_to_a_whole_layer_not_region_by_region():
    """A layer either follows the window or does not; the map says where.

    Keeping "which areas" in the map and "which layers" on the layer means an
    operator adds a well to the window once, and every layer that follows the
    window opens over it — rather than having to repeat the same region on
    each layer in turn.
    """
    canvas = _canvas()
    canvas.see_through_fields("fields", [0, 1])
    assert len(canvas.opacity_map["regions"]) == 2

    # The regions live on the canvas, once. Layers carry only the yes-or-no.
    for layer in canvas.layers:
        assert "regions" not in layer
        assert isinstance(layer["windowed"], bool)
