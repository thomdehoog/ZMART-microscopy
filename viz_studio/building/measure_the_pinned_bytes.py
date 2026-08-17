"""Stage 0, instrument 3: what the pin would hold, in bytes, before it holds it.

The composer pins every pyramid level holding at most ``PINNED_SHARE`` of the
full-resolution voxels, plus the coarsest level unconditionally, decoded and
deliberately unevictable (`composer.py`, ``pinned_levels``). On a flat survey
that geometry bounds the pin near half a percent of a picture that is itself
modest. In depth the picture is terabytes and the same geometry is an
out-of-memory — both reviews said so by arithmetic, and this instrument makes
the arithmetic a number anyone can re-run, per canvas shape, for both pyramid
shapes, against the RAM of the machine it runs on.

Run it with no arguments for the standard scenarios, or pass
``height width depth`` in voxels for a canvas of your own.
"""

from __future__ import annotations

import sys

from composer import PIECE, PINNED_SHARE

BYTES_PER_VOXEL = 2  # uint16, the profile's number type


def levels_of(height: int, width: int, depth: int, *, z_halves: bool,
              hold_z_levels: int = 0) -> list[tuple[int, int, int]]:
    """The pyramid's per-level shapes, coarsening until one piece holds y and x.

    y and x halve every level (ceiling, the pinned rounding rule); z halves
    only where the shape says so — never, always, or held for the first
    ``hold_z_levels`` levels and halved after (the Thy1 shape).
    """
    shapes = [(depth, height, width)]
    level = 0
    while max(shapes[-1][1], shapes[-1][2]) > PIECE:
        deep, tall, wide = shapes[-1]
        level += 1
        halve_z = z_halves and level > hold_z_levels
        shapes.append((
            -(-deep // 2) if halve_z else deep,
            -(-tall // 2),
            -(-wide // 2),
        ))
    return shapes


def pinned_bytes(shapes: list[tuple[int, int, int]]) -> tuple[int, list[int]]:
    """The composer's own rule: share-selected levels plus the coarsest."""
    full = shapes[0][0] * shapes[0][1] * shapes[0][2]
    pinned = {len(shapes) - 1}
    for level, (deep, tall, wide) in enumerate(shapes):
        if deep * tall * wide <= PINNED_SHARE * full:
            pinned.add(level)
    total = sum(shapes[level][0] * shapes[level][1] * shapes[level][2]
                for level in pinned) * BYTES_PER_VOXEL
    return total, sorted(pinned)


def machine_ram_bytes() -> int:
    with open("/proc/meminfo", encoding="ascii") as told:
        for line in told:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    return 0


def report(name: str, height: int, width: int, depth: int) -> None:
    ram = machine_ram_bytes()
    print(f"\n== {name}: canvas {height} x {width} x {depth} deep, "
          f"{height * width * depth * BYTES_PER_VOXEL / 1e9:.1f} GB at "
          f"full resolution ==")
    for label, z_halves, hold in (("z never halves", False, 0),
                                  ("z always halves", True, 0),
                                  ("z held 3 then halves (Thy1 shape)", True, 3)):
        shapes = levels_of(height, width, depth, z_halves=z_halves,
                           hold_z_levels=hold)
        total, pinned = pinned_bytes(shapes)
        verdict = "OK" if total < ram * 0.25 else (
            "TIGHT" if total < ram * 0.6 else "OUT OF MEMORY IN PRACTICE")
        print(f"  {label:36s} {len(shapes)} levels, pins {pinned}, "
              f"pinned {total / 1e9:6.2f} GB  -> {verdict} "
              f"(machine has {ram / 1e9:.1f} GB)")


def main() -> int:
    if len(sys.argv) == 4:
        height, width, depth = (int(one) for one in sys.argv[1:4])
        report("your canvas", height, width, depth)
        return 0
    # A flat survey the ladder already measured, for scale sanity.
    report("40 x 40 flat survey (frame 1152, ~10% overlap)",
           40 * 1040 + 112, 40 * 1040 + 112, 1)
    # The motivating evening: 49 Thy1 blocks.
    report("49 Thy1 blocks (7 x 7 of 1264 x 1480 x 291, ~10% overlap)",
           7 * 1138 + 126, 7 * 1332 + 148, 291)
    # The reviews' arithmetic case: 4,096 Thy1-shaped positions.
    report("4,096 Thy1-shaped positions (64 x 64)",
           64 * 1138 + 126, 64 * 1332 + 148, 291)
    return 0


if __name__ == "__main__":
    sys.exit(main())
