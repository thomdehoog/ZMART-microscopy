"""CLI runner for the object_analysis workflow."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = ROOT / "workflows"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(WORKFLOWS_DIR))

from engine import Engine  # noqa: E402


WORKFLOW_DIR = Path(__file__).resolve().parent
CLASSICAL_YAML = WORKFLOW_DIR / "pipelines" / "object_analysis.yaml"


def _image_size_px(path: Path, channel_axis=None) -> list[int]:
    """The (nx, ny) of a position, from its own metadata.

    ``channel_axis`` is accepted and ignored: an image says what its axes
    are, and this used to have to guess from the shape.
    """
    import sys

    sys.path.insert(0, str(WORKFLOW_DIR / "steps"))
    from detect_objects import load_plane

    _, metadata = load_plane(path)
    axes, shape = metadata["axes"], metadata["shape"]
    return [int(shape[axes.index("x")]), int(shape[axes.index("y")])]


def _parse_pair(text: str) -> list[float]:
    values = [float(part.strip()) for part in text.split(",")]
    if len(values) != 2:
        raise argparse.ArgumentTypeError("expected two comma-separated values")
    return values


def _parse_matrix(text: str) -> list[list[float]]:
    values = [float(part.strip()) for part in text.split(",")]
    if len(values) != 4:
        raise argparse.ArgumentTypeError(
            "expected four comma-separated values, e.g. 1,0,0,1"
        )
    return [[values[0], values[1]], [values[2], values[3]]]


def _parse_channels(text: str) -> list[int] | None:
    text = text.strip()
    if text.lower() in {"", "none", "auto"}:
        return None
    values = [int(part.strip()) for part in text.split(",")]
    if len(values) > 3:
        raise argparse.ArgumentTypeError("expected at most three channels")
    if any(value < 0 for value in values):
        raise argparse.ArgumentTypeError("channels must be non-negative")
    return values


def _parse_tile_id(text: str) -> list:
    parts = [part.strip() for part in text.split(",")]
    out = []
    for part in parts:
        try:
            out.append(int(part))
        except ValueError:
            out.append(part)
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Run object-centered analysis on one image tile."
    )
    parser.add_argument("image_path", help="Path to a TIFF tile.")
    parser.add_argument("--tile-id", default="R0,0,0")
    parser.add_argument("--stage-xy-um", type=_parse_pair, default=[0.0, 0.0])
    parser.add_argument("--zwide-um", type=float, default=0.0)
    parser.add_argument("--pixel-size-um", type=_parse_pair, default=[1.0, 1.0])
    parser.add_argument(
        "--image-to-stage",
        type=_parse_matrix,
        default=[[1.0, 0.0], [0.0, 1.0]],
        help="2x2 image-to-stage matrix as a,b,c,d (default: identity).",
    )
    parser.add_argument(
        "--channels",
        type=_parse_channels,
        default=None,
        help="Comma-separated channel indices for 2D+channels input; "
        "default auto keeps up to three channels.",
    )
    parser.add_argument(
        "--channel-axis",
        type=int,
        choices=(-1, 0, 2),
        default=None,
        help="Channel axis for 3D TIFF input: 0 for (C,H,W), -1 or 2 for "
        "(H,W,C). Required when orientation is ambiguous.",
    )
    parser.add_argument("--gpu", action="store_true", default=False)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    image_path = Path(args.image_path)
    payload = {
        "image_path": str(image_path),
        "tile_id": _parse_tile_id(args.tile_id),
        "tile_stage_xy_um": args.stage_xy_um,
        "tile_zwide_um": args.zwide_um,
        "source_pixel_size_um": args.pixel_size_um,
        "source_image_size_px": _image_size_px(image_path, args.channel_axis),
        "image_to_stage": args.image_to_stage,
        "channels": args.channels,
        "channel_axis": args.channel_axis,
        "gpu": args.gpu,
    }
    if args.output_dir:
        payload["output_dir"] = args.output_dir

    with Engine() as engine:
        engine.register("object_analysis", str(CLASSICAL_YAML))
        engine.submit("object_analysis", payload)

        while True:
            results = engine.results("object_analysis")
            if results:
                break
            status = engine.status("object_analysis")
            if status["failed"]:
                failure = status["failures"][0]
                raise RuntimeError(f"{failure['step']}: {failure['error']}")
            time.sleep(0.2)

    tile = results[0]["object_analysis"]
    print(f"Objects detected: {tile['objects']['n_objects']}")


if __name__ == "__main__":
    main()
