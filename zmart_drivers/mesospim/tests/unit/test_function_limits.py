"""Offline tests for the function-keyed limits module.

What is under test is the contract drivers rely on: the completeness check
(every mutating op has an entry, no typo entries), constraint resolution
(@references, inline bounds, machine overrides), the fail-closed check
semantics, and the provenance record.
"""

import json

import pytest

from mesospim.limits import (
    FunctionLimits,
    LimitsError,
    LimitViolation,
    load,
    parse,
)

OPS = ("set_origin", "set_xyz", "set_state")


def _payload(**overrides):
    payload = {
        "schema_version": 1,
        "source": "defaults",
        "constraints": {
            "stage.x": {"min": 1000, "max": 130000},
            "stage.y": {"min": 1000, "max": 100000},
            "save.format": {"allowed": ["lof", "xlef"]},
        },
        "functions": {
            "set_origin": None,
            "set_xyz": {"x_um": "@stage.x", "y_um": "@stage.y"},
            "set_state": None,
        },
    }
    payload.update(overrides)
    return payload


# -- load / parse validation --------------------------------------------------


class TestParseValidation:
    def test_valid_payload_parses(self):
        limits = parse(_payload(), functions=OPS)
        assert isinstance(limits, FunctionLimits)
        assert limits.source == "defaults"

    def test_unknown_top_level_section_is_ignored(self):
        """A driver may co-locate extra sections (e.g. the leica limits.json
        carries a ``backlash`` block the motion loader reads). The parser reads
        only schema_version/source/constraints/functions and must ignore any
        other top-level key WITHOUT loosening its validation of the sections it
        does read (a poisoned constraint/function still fails)."""
        limits = parse(
            _payload(backlash={"approach": "+X+Y", "overshoot_um": 50}),
            functions=OPS,
        )
        assert isinstance(limits, FunctionLimits)
        # the ignored section does not smuggle past constraint validation
        with pytest.raises(LimitsError, match="finite"):
            parse(
                _payload(
                    backlash={"whatever": float("nan")},
                    constraints={"stage.x": {"min": float("nan"), "max": 1}},
                    functions={"set_origin": None, "set_xyz": None, "set_state": None},
                ),
                functions=OPS,
            )

    def test_wrong_schema_version_rejected(self):
        with pytest.raises(LimitsError, match="schema_version"):
            parse(_payload(schema_version=2), functions=OPS)

    def test_missing_source_rejected(self):
        with pytest.raises(LimitsError, match="source"):
            parse(_payload(source=""), functions=OPS)

    def test_missing_functions_section_rejected(self):
        payload = _payload()
        del payload["functions"]
        with pytest.raises(LimitsError, match="functions"):
            parse(payload, functions=OPS)

    def test_missing_mutating_op_entry_rejected(self):
        payload = _payload()
        del payload["functions"]["set_state"]
        with pytest.raises(LimitsError, match=r"set_state"):
            parse(payload, functions=OPS)

    def test_undeclared_function_entry_rejected(self):
        payload = _payload()
        payload["functions"]["set_xzy"] = None  # typo must fail, not silently no-op
        with pytest.raises(LimitsError, match="set_xzy"):
            parse(payload, functions=OPS)

    def test_unknown_constraint_reference_rejected(self):
        payload = _payload()
        payload["functions"]["set_xyz"]["x_um"] = "@stage.missing"
        with pytest.raises(LimitsError, match="stage.missing"):
            parse(payload, functions=OPS)

    def test_non_reference_string_rejected(self):
        payload = _payload()
        payload["functions"]["set_xyz"]["x_um"] = "stage.x"  # forgot the @
        with pytest.raises(LimitsError, match="'@name'"):
            parse(payload, functions=OPS)

    def test_min_greater_than_max_rejected(self):
        payload = _payload()
        payload["constraints"]["stage.x"] = {"min": 10, "max": 1}
        with pytest.raises(LimitsError, match="min > max"):
            parse(payload, functions=OPS)

    def test_empty_constraint_rejected(self):
        payload = _payload()
        payload["constraints"]["stage.x"] = {}
        with pytest.raises(LimitsError, match="non-empty"):
            parse(payload, functions=OPS)

    def test_constraint_bounding_nothing_rejected(self):
        payload = _payload()
        payload["constraints"]["stage.x"] = {"min": None}
        with pytest.raises(LimitsError, match="bounds nothing"):
            parse(payload, functions=OPS)

    def test_unknown_constraint_key_rejected(self):
        payload = _payload()
        payload["constraints"]["stage.x"] = {"min": 0, "maximum": 5}
        with pytest.raises(LimitsError, match="maximum"):
            parse(payload, functions=OPS)

    def test_empty_allowed_rejected(self):
        payload = _payload()
        payload["constraints"]["save.format"] = {"allowed": []}
        with pytest.raises(LimitsError, match="allowed"):
            parse(payload, functions=OPS)


class TestOverrides:
    def test_override_rebounds_named_constraint(self):
        limits = parse(
            _payload(),
            functions=OPS,
            constraint_overrides={"stage.x": {"min": 2000, "max": 50000}},
        )
        limits.check("set_xyz", {"x_um": 2000})
        with pytest.raises(LimitViolation):
            limits.check("set_xyz", {"x_um": 1500})  # fine per bundled, out per override

    def test_override_for_unknown_constraint_rejected(self):
        with pytest.raises(LimitsError, match="stage.z"):
            parse(
                _payload(),
                functions=OPS,
                constraint_overrides={"stage.z": {"min": 0, "max": 1}},
            )

    def test_invalid_override_rejected(self):
        with pytest.raises(LimitsError, match="min > max"):
            parse(
                _payload(),
                functions=OPS,
                constraint_overrides={"stage.x": {"min": 5, "max": 1}},
            )


# -- runtime checks -----------------------------------------------------------


class TestCheck:
    def test_in_bounds_passes(self):
        limits = parse(_payload(), functions=OPS)
        limits.check("set_xyz", {"x_um": 1000, "y_um": 100000})

    def test_out_of_bounds_raises_with_provenance(self):
        limits = parse(_payload(), functions=OPS)
        with pytest.raises(LimitViolation) as err:
            limits.check("set_xyz", {"x_um": 500})
        message = str(err.value)
        assert "set_xyz" in message
        assert "x_um=500" in message
        assert "stage.x" in message
        assert "source=defaults" in message

    def test_partial_call_checks_only_provided_params(self):
        limits = parse(_payload(), functions=OPS)
        limits.check("set_xyz", {"y_um": 50000})  # x omitted: a partial move

    def test_unbounded_extra_params_ignored(self):
        limits = parse(_payload(), functions=OPS)
        limits.check("set_xyz", {"x_um": 5000, "note": "unconstrained rider"})

    def test_null_entry_is_reviewed_unlimited(self):
        limits = parse(_payload(), functions=OPS)
        limits.check("set_state", {"job": "anything", "power": 1e9})

    def test_undeclared_function_is_an_error_not_a_pass(self):
        limits = parse(_payload(), functions=OPS)
        with pytest.raises(LimitsError, match="acquire"):
            limits.check("acquire", {})

    def test_allowed_values_enforced(self):
        payload = _payload()
        payload["functions"]["set_state"] = {"format": "@save.format"}
        limits = parse(payload, functions=OPS)
        limits.check("set_state", {"format": "lof"})
        with pytest.raises(LimitViolation, match="not one of"):
            limits.check("set_state", {"format": "tiff"})

    def test_non_numeric_value_against_range_raises(self):
        limits = parse(_payload(), functions=OPS)
        with pytest.raises(LimitViolation, match="not numeric"):
            limits.check("set_xyz", {"x_um": "fast"})

    def test_inline_constraint_carries_function_scoped_name(self):
        payload = _payload()
        payload["functions"]["set_xyz"]["z_um"] = {"min": -200, "max": 200}
        limits = parse(payload, functions=OPS)
        with pytest.raises(LimitViolation, match="set_xyz.z_um"):
            limits.check("set_xyz", {"z_um": 300})

    def test_open_ended_bound(self):
        payload = _payload()
        payload["constraints"]["stage.x"] = {"min": 0}
        limits = parse(payload, functions=OPS)
        limits.check("set_xyz", {"x_um": 1e12})
        with pytest.raises(LimitViolation):
            limits.check("set_xyz", {"x_um": -1})


# -- file loading and provenance ----------------------------------------------


class TestLoadAndDescribe:
    def test_load_reads_file_and_records_path(self, tmp_path):
        path = tmp_path / "function_limits.json"
        path.write_text(json.dumps(_payload()), encoding="utf-8")
        limits = load(path, functions=OPS)
        assert limits.path == path
        assert limits.is_fallback is False
        with pytest.raises(LimitViolation, match=str(path)):
            limits.check("set_xyz", {"x_um": 0})

    def test_describe_reports_provenance(self, tmp_path):
        path = tmp_path / "function_limits.json"
        path.write_text(json.dumps(_payload()), encoding="utf-8")
        limits = load(path, functions=OPS, is_fallback=True)
        assert limits.describe() == {
            "schema_version": 1,
            "source": "defaults",
            "path": str(path),
            "is_fallback": True,
        }

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load(tmp_path / "nope.json", functions=OPS)
