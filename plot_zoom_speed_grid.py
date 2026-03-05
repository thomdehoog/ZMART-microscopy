"""
Plot the zoom x speed compatibility grid from test results.
"""

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np

# Data from the hardware test
ZOOMS = [0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, 40.0, 48.0]
SPEEDS = [10, 50, 100, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2400, 2600]

# Actual zoom readback for each (zoom, speed) combination
# None means OK (no adjustment)
actual_zoom = {
    (0.75, 800): 1.275, (0.75, 1000): 2.25, (0.75, 1200): 4.5,
    (0.75, 1400): 4.5, (0.75, 1600): 6.0, (0.75, 1800): 7.5,
    (0.75, 2000): 16.0, (0.75, 2400): 16.0, (0.75, 2600): 16.0,
    (1.0, 800): 1.275, (1.0, 1000): 2.25, (1.0, 1200): 4.5,
    (1.0, 1400): 4.5, (1.0, 1600): 6.0, (1.0, 1800): 7.5,
    (1.0, 2000): 16.0, (1.0, 2400): 16.0, (1.0, 2600): 16.0,
    (1.5, 1000): 2.25, (1.5, 1200): 4.5, (1.5, 1400): 4.5,
    (1.5, 1600): 6.0, (1.5, 1800): 7.5, (1.5, 2000): 16.0,
    (1.5, 2400): 16.0, (1.5, 2600): 16.0,
    (2.0, 1000): 2.25, (2.0, 1200): 4.5, (2.0, 1400): 4.5,
    (2.0, 1600): 6.0, (2.0, 1800): 7.5, (2.0, 2000): 16.0,
    (2.0, 2400): 16.0, (2.0, 2600): 16.0,
    (3.0, 1200): 4.5, (3.0, 1400): 4.5, (3.0, 1600): 6.0,
    (3.0, 1800): 7.5, (3.0, 2000): 16.0, (3.0, 2400): 16.0,
    (3.0, 2600): 16.0,
    (5.0, 1600): 6.0, (5.0, 1800): 7.5, (5.0, 2000): 16.0,
    (5.0, 2400): 16.0, (5.0, 2600): 16.0,
    (7.0, 1800): 7.5, (7.0, 2000): 16.0, (7.0, 2400): 16.0,
    (7.0, 2600): 16.0,
    (10.0, 2000): 16.0, (10.0, 2400): 16.0, (10.0, 2600): 16.0,
    (15.0, 2000): 16.0, (15.0, 2400): 16.0, (15.0, 2600): 16.0,
}

# Build grid: 0 = OK, 1 = silently adjusted
nz = len(ZOOMS)
ns = len(SPEEDS)
grid = np.zeros((nz, ns))

for i, z in enumerate(ZOOMS):
    for j, s in enumerate(SPEEDS):
        if (z, s) in actual_zoom:
            grid[i, j] = 1

# ---- Plot 1: OK vs adjusted heatmap ----
fig, ax = plt.subplots(figsize=(14, 7))

cmap = mcolors.ListedColormap(["#2ecc71", "#e74c3c"])
bounds = [-0.5, 0.5, 1.5]
norm = mcolors.BoundaryNorm(bounds, cmap.N)

im = ax.imshow(grid, cmap=cmap, norm=norm, aspect="auto",
               interpolation="nearest")

ax.set_xticks(range(ns))
ax.set_xticklabels(SPEEDS, fontsize=9)
ax.set_yticks(range(nz))
ax.set_yticklabels([f"{z:.2f}" if z < 1 else f"{z:.1f}" if z != int(z) else str(int(z))
                     for z in ZOOMS], fontsize=9)
ax.set_xlabel("Scan Speed", fontsize=12)
ax.set_ylabel("Zoom", fontsize=12)
ax.set_title("LAS X Zoom x Speed Compatibility (STELLARIS)\n"
             "Green = OK  |  Red = Zoom silently adjusted by LAS X",
             fontsize=13)

# Annotate adjusted cells with the actual zoom LAS X applied
for i, z in enumerate(ZOOMS):
    for j, s in enumerate(SPEEDS):
        if (z, s) in actual_zoom:
            val = actual_zoom[(z, s)]
            label = f"{val:.1f}" if val != int(val) else str(int(val))
            ax.text(j, i, label, ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold")
        else:
            ax.text(j, i, "OK", ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold")

# Draw the boundary line between OK and adjusted
# Find the boundary: for each speed, find the minimum zoom that is OK
boundary_zooms = []
for j, s in enumerate(SPEEDS):
    min_ok_zoom = None
    for i, z in enumerate(ZOOMS):
        if (z, s) not in actual_zoom:
            min_ok_zoom = z
            break
    boundary_zooms.append((j, i if min_ok_zoom else nz))

# Draw staircase boundary
for k in range(len(boundary_zooms) - 1):
    j1, i1 = boundary_zooms[k]
    j2, i2 = boundary_zooms[k + 1]
    if i1 != i2:
        ax.plot([j1 + 0.5, j1 + 0.5], [i1 - 0.5, i2 - 0.5],
                color="white", linewidth=2, linestyle="--")
    ax.plot([j1 - 0.5 if k == 0 else j1 + 0.5, j2 + 0.5 if k == len(boundary_zooms) - 2 else j1 + 0.5],
            [i1 - 0.5, i1 - 0.5] if i1 == i2 else [i2 - 0.5, i2 - 0.5],
            color="white", linewidth=2, linestyle="--")

plt.tight_layout()
plt.savefig("Z:/zmbstaff/10374/Protocols_Notes/thom/notes/repositories/"
            "driver_v6/zoom_speed_grid.png", dpi=150)
print("Saved zoom_speed_grid.png")

# ---- Plot 2: Minimum zoom required per speed ----
fig2, ax2 = plt.subplots(figsize=(12, 5))

min_zoom_for_speed = []
for s in SPEEDS:
    min_z = 0.75  # lowest tested
    for z in ZOOMS:
        if (z, s) not in actual_zoom:
            min_z = z
            break
    else:
        min_z = 20.0  # all were adjusted
    min_zoom_for_speed.append(min_z)

ax2.step(SPEEDS, min_zoom_for_speed, where="mid", linewidth=2.5,
         color="#2c3e50", marker="o", markersize=6)
ax2.fill_between(SPEEDS, min_zoom_for_speed, step="mid",
                 alpha=0.15, color="#2c3e50")
ax2.set_xlabel("Scan Speed", fontsize=12)
ax2.set_ylabel("Minimum Zoom (no adjustment)", fontsize=12)
ax2.set_title("LAS X Minimum Zoom Required per Scan Speed (STELLARIS)",
              fontsize=13)
ax2.set_xticks(SPEEDS)
ax2.set_xticklabels(SPEEDS, fontsize=9, rotation=45)
ax2.grid(True, alpha=0.3)
ax2.set_ylim(0, 22)

# Annotate the step values
prev = None
for s, z in zip(SPEEDS, min_zoom_for_speed):
    if z != prev:
        ax2.annotate(f"{z}", (s, z), textcoords="offset points",
                     xytext=(0, 12), ha="center", fontsize=9,
                     fontweight="bold", color="#c0392b")
        prev = z

plt.tight_layout()
plt.savefig("Z:/zmbstaff/10374/Protocols_Notes/thom/notes/repositories/"
            "driver_v6/zoom_speed_min_zoom.png", dpi=150)
print("Saved zoom_speed_min_zoom.png")

plt.show()
