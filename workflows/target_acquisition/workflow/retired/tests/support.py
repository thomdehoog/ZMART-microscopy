"""Shared test data builders for the retired target-acquisition tests."""


def minimal_calibration(
    *,
    source_slot: int = 1,
    target_slot: int = 2,
) -> dict:
    """A small, valid calibration document for tests.

    It holds two objectives: the source at the origin (0, 0, 0) and the target
    a little away from it. That is all these tests need. The reference objective
    is simply whichever one sits at the origin -- it is derived from the data,
    not stored.
    """
    source_slot = int(source_slot)
    target_slot = int(target_slot)

    objectives = {
        str(source_slot): {
            "name": f"slot {source_slot} source",
            "translation_um": [0.0, 0.0, 0.0],
            "session_id": "test-source",
        }
    }
    if target_slot != source_slot:
        objectives[str(target_slot)] = {
            "name": f"slot {target_slot} target",
            "translation_um": [10.0, -5.0, 2.0],
            "session_id": "test-target",
        }

    return {
        "schema_version": 12,
        "last_updated": "test",
        "objectives": objectives,
    }
