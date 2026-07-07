"""Shared test data builders for target-acquisition tests."""


def minimal_calibration(
    *,
    source_slot: int = 1,
    target_slot: int = 2,
    image_to_stage: list[list[float]] | None = None,
) -> dict:
    """Small valid v11 calibration document for tests."""
    source_slot = int(source_slot)
    target_slot = int(target_slot)
    matrix = image_to_stage or [[1.0, 0.0], [0.0, 1.0]]

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
        "schema_version": 11,
        "last_updated": "test",
        "reference_objective_slot": source_slot,
        "image_to_stage": {
            "matrix": matrix,
            "session_id": "test-image-to-stage",
        },
        "objectives": objectives,
    }
