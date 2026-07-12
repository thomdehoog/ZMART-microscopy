"""
Table-driven confirm descriptor tests.
======================================
Stage-4 collapse safety net. These tests pin the relationship between the
``confirm_specs.CONFIRM_SPECS`` descriptor table and the thin
``confirmations._confirm_<name>`` wrappers that are generated from it, so the
two cannot silently drift:

  * the table covers *exactly* the set of collapsed settings (no missing /
    no extra rows, every row has its wrapper, no bespoke confirm leaked in);
  * each row's comparator kind matches the public wrapper's signature (a
    tolerance comparator has a ``tolerance`` knob, an exact one has none),
    and the wrapper tolerance defaults are pinned to their exact values;
  * the generic ``_confirm_readback`` confirms a matching readback and stays
    unconfirmed (with a warning) on a non-matching one, per descriptor.

Offline: ``_readback`` is monkeypatched, so no hardware/API is touched.
"""

import inspect

import pytest
from navigator_expert.commands import confirm_specs, confirmations

CONFIRM_SPECS = confirm_specs.CONFIRM_SPECS


# The canonical set of settings that Stage 4 collapsed onto the generic poll
# loop. Hardcoded on purpose: if a row is added or removed from CONFIRM_SPECS
# without updating this set, the completeness test fails.
EXPECTED_COLLAPSED = {
    "scan_field_rotation",
    "pinhole_airy",
    "detector_gain",
    "laser_intensity",
    "filter_wheel_spectrum",
    "scan_speed",
    "scan_resonant",
    "scan_mode",
    "sequential_mode",
    "frame_accumulation",
    "frame_average",
    "line_accumulation",
    "line_average",
    "laser_shutter",
    "filter_wheel_slot",
    "z_stack_step_size",
}

# Confirms deliberately left bespoke — they must NOT appear in the table
# (each has extra behaviour the generic can't express byte-identically).
BESPOKE_CONFIRMS = {
    "zoom",  # last_actual carried into the timeout message
    "image_format",  # "W x H" string target + special log/timeout text
    "z_stack_size",  # step-quantised candidate matching
    "z_stack_definition",  # step-quantised candidate matching
    "move_z",  # z-mode key + delta in the debug line
    "move_xy",  # get_xy reader, last_position in the result dict
    "objective",  # mechanical turret, name-vs-slot labelling
    "acquire",  # two-phase scan-status polling
}

# Per-spec sample readbacks. ``ch(actual)`` builds a readback dict that places
# ``actual`` exactly where the descriptor's extractor reads it. ``match`` is a
# value that confirms (within the wrapper's default tolerance for tolerance
# specs); ``miss`` is clearly outside.
SAMPLES = {
    "scan_field_rotation": dict(
        params={},
        target=45.0,
        match=45.2,  # |0.2| < 0.5
        miss=46.0,  # |1.0| >= 0.5
        ch=lambda a: {"scanFieldRotation": {"value": a}},
    ),
    "pinhole_airy": dict(
        params={"si": 0},
        target=1.0,
        match=1.02,  # |0.02| < 0.05
        miss=0.5,
        ch=lambda a: {"activeSettings": [{"pinholeAiry": {"value": a}}]},
    ),
    "detector_gain": dict(
        params={"si": 0, "beam_route": "BR1"},
        target=750.0,
        match=750.5,  # |0.5| < 1.0
        miss=700.0,
        ch=lambda a: {
            "activeSettings": [{"activeDetectors": [{"_beamRoute": "BR1", "gain": {"value": a}}]}]
        },
    ),
    "laser_intensity": dict(
        params={"si": 0, "beam_route": "BR1", "line_index": 0},
        target=0.5,
        match=0.502,  # |0.002| < 0.005
        miss=0.6,
        ch=lambda a: {
            "activeSettings": [
                {
                    "activeLaserLines": [
                        {"_beamRoute": "BR1", "_lineIndex": 0, "intensity": {"value": a}}
                    ]
                }
            ]
        },
    ),
    "filter_wheel_spectrum": dict(
        params={"si": 0, "beam_route": "BR1", "fw_type": "FW"},
        target=525,
        match=525.4,  # |0.4| < 1
        miss=560,
        ch=lambda a: {
            "activeSettings": [
                {"filterWheels": [{"_beamRoute": "BR1", "type": "FW", "spectrumPosition": a}]}
            ]
        },
    ),
    "scan_speed": dict(
        params={},
        target=600,
        match=600,
        miss=400,
        ch=lambda a: {"scanSpeed": {"value": a}},
    ),
    "scan_resonant": dict(
        params={},
        target=True,
        match=True,
        miss=False,
        ch=lambda a: {"scanSpeed": {"isResonant": a}},
    ),
    "scan_mode": dict(
        params={},
        target="xyz",
        match="xyz",
        miss="xy",
        ch=lambda a: {"scanMode": a},
    ),
    "sequential_mode": dict(
        params={},
        target="Line",
        match="Line",
        miss="Frame",
        ch=lambda a: {"sequentialMode": a},
    ),
    "z_stack_step_size": dict(
        params={},
        target=2.0,
        match=2.2,  # |0.2| < 0.5
        miss=3.0,
        ch=lambda a: {"stack": {"stepSize": a}},
    ),
    "frame_accumulation": dict(
        params={"si": 0},
        target=4,
        match=4,
        miss=2,
        ch=lambda a: {"activeSettings": [{"frameAccumulation": a}]},
    ),
    "frame_average": dict(
        params={"si": 0},
        target=2,
        match=2,
        miss=3,
        ch=lambda a: {"activeSettings": [{"frameAverage": a}]},
    ),
    "line_accumulation": dict(
        params={"si": 0},
        target=3,
        match=3,
        miss=1,
        ch=lambda a: {"activeSettings": [{"lineAccumulation": a}]},
    ),
    "line_average": dict(
        params={"si": 0},
        target=8,
        match=8,
        miss=4,
        ch=lambda a: {"activeSettings": [{"lineAverage": a}]},
    ),
    "laser_shutter": dict(
        params={"si": 0, "beam_route": "BR1"},
        target=True,
        match=True,
        miss=False,
        ch=lambda a: {
            "activeSettings": [{"activeLaserLines": [{"_beamRoute": "BR1", "shutterOpen": a}]}]
        },
    ),
    "filter_wheel_slot": dict(
        params={"si": 0, "beam_route": "BR1", "fw_type": "FW"},
        target=3,
        match=3,
        miss=5,
        ch=lambda a: {
            "activeSettings": [
                {"filterWheels": [{"_beamRoute": "BR1", "type": "FW", "filterIndex": a}]}
            ]
        },
    ),
}


# =============================================================================
# Completeness: the table covers exactly the collapsed settings
# =============================================================================


def test_table_covers_exactly_collapsed_settings():
    assert set(CONFIRM_SPECS) == EXPECTED_COLLAPSED


def test_samples_cover_every_spec():
    # The behavioural tests below would silently skip a new row otherwise.
    assert set(SAMPLES) == set(CONFIRM_SPECS)


def test_every_spec_has_its_wrapper():
    for name in CONFIRM_SPECS:
        wrapper = getattr(confirmations, f"_confirm_{name}", None)
        assert callable(wrapper), f"missing wrapper _confirm_{name}"


def test_bespoke_confirms_absent_from_table():
    for name in BESPOKE_CONFIRMS:
        assert name not in CONFIRM_SPECS, f"{name} should stay bespoke"


def test_comparator_is_one_of_the_two_known_kinds():
    for name, spec in CONFIRM_SPECS.items():
        assert spec.compare in (confirm_specs._cmp_exact, confirm_specs._cmp_tolerance), name


def _wrapper_default_tolerance(name):
    """Return the ``tolerance`` default from a wrapper's signature (None if absent).

    The wrapper signature is the single home of each setting's default
    tolerance; the descriptor table deliberately carries none.
    """
    params = inspect.signature(getattr(confirmations, f"_confirm_{name}")).parameters
    param = params.get("tolerance")
    return None if param is None else param.default


def test_tolerance_knob_matches_comparator_kind():
    """Tolerance comparators have a tolerance knob; exact comparators have none."""
    for name, spec in CONFIRM_SPECS.items():
        params = inspect.signature(getattr(confirmations, f"_confirm_{name}")).parameters
        if spec.compare is confirm_specs._cmp_tolerance:
            assert "tolerance" in params, name
        else:
            assert "tolerance" not in params, name


def test_expected_tolerances_are_exact_values():
    """Pin the wrapper tolerance defaults so a profile/wrapper drift is caught here."""
    assert _wrapper_default_tolerance("scan_field_rotation") == 0.5
    assert _wrapper_default_tolerance("pinhole_airy") == 0.05
    assert _wrapper_default_tolerance("detector_gain") == 1.0
    assert _wrapper_default_tolerance("laser_intensity") == 0.005
    assert _wrapper_default_tolerance("filter_wheel_spectrum") == 1
    assert _wrapper_default_tolerance("z_stack_step_size") == 0.5


# =============================================================================
# Behaviour: generic confirm with each descriptor (mocked readback)
# =============================================================================


def _readback_returning(value):
    return lambda client, job_name: value


@pytest.mark.parametrize("name", sorted(CONFIRM_SPECS))
def test_generic_confirms_matching_readback(name, monkeypatch):
    s = SAMPLES[name]
    spec = CONFIRM_SPECS[name]
    monkeypatch.setattr(confirmations, "_readback", _readback_returning(s["ch"](s["match"])))

    result = confirmations._confirm_readback(
        object(),
        "JOB",
        s["target"],
        extract=lambda ch: spec.extract(ch, s["params"]),
        label=spec.label,
        compare=spec.compare,
        errors=spec.errors,
        tolerance=_wrapper_default_tolerance(name),
        poll_window=1.0,
        poll_interval=0.001,
    )
    # Confirmed immediately on the first poll: no logs accumulated.
    assert result == {"success": True, "logs": []}


@pytest.mark.parametrize("name", sorted(CONFIRM_SPECS))
def test_generic_rejects_non_matching_readback(name, monkeypatch):
    s = SAMPLES[name]
    spec = CONFIRM_SPECS[name]
    monkeypatch.setattr(confirmations, "_readback", _readback_returning(s["ch"](s["miss"])))

    result = confirmations._confirm_readback(
        object(),
        "JOB",
        s["target"],
        extract=lambda ch: spec.extract(ch, s["params"]),
        label=spec.label,
        compare=spec.compare,
        errors=spec.errors,
        tolerance=_wrapper_default_tolerance(name),
        poll_window=0.02,
        poll_interval=0.001,
    )
    assert result["success"] is False
    # Exactly one warning entry, naming the setting and the timeout.
    assert len(result["logs"]) == 1
    entry = result["logs"][0]
    assert entry["level"] == "warning"
    assert spec.label in entry["msg"]
    assert "timeout" in entry["msg"]


# =============================================================================
# Behaviour: the public wrappers drive the generic end to end
# =============================================================================


@pytest.mark.parametrize("name", sorted(CONFIRM_SPECS))
def test_public_wrapper_confirms_match_and_rejects_miss(name, monkeypatch):
    """Exercise the real ``_confirm_<name>`` wrapper, default tolerance and all."""
    s = SAMPLES[name]
    wrapper = getattr(confirmations, f"_confirm_{name}")

    monkeypatch.setattr(confirmations, "_readback", _readback_returning(s["ch"](s["match"])))
    ok = wrapper(
        object(), "JOB", target=s["target"], poll_window=1.0, poll_interval=0.001, **s["params"]
    )
    assert ok == {"success": True, "logs": []}

    monkeypatch.setattr(confirmations, "_readback", _readback_returning(s["ch"](s["miss"])))
    bad = wrapper(
        object(), "JOB", target=s["target"], poll_window=0.02, poll_interval=0.001, **s["params"]
    )
    assert bad["success"] is False
    assert bad["logs"][0]["level"] == "warning"


def test_extraction_error_is_swallowed_until_timeout(monkeypatch):
    """A malformed readback is caught (not raised) and the window times out."""
    spec = CONFIRM_SPECS["scan_speed"]
    monkeypatch.setattr(confirmations, "_readback", _readback_returning({"wrong": "shape"}))

    result = confirmations._confirm_readback(
        object(),
        "JOB",
        600,
        extract=lambda ch: spec.extract(ch, {}),
        label=spec.label,
        compare=spec.compare,
        errors=spec.errors,
        poll_window=0.02,
        poll_interval=0.001,
    )
    assert result["success"] is False
    assert result["logs"][0]["level"] == "warning"
