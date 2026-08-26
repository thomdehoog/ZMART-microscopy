import json, subprocess, time, urllib.request
import numpy as np
import Quartz
from PIL import Image

# Find the ZMART Viewer native window.
wins = Quartz.CGWindowListCopyWindowInfo(
    Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
target = next((w for w in wins
               if (w.get("kCGWindowOwnerName") or "").lower() == "python"
               and w.get("kCGWindowBounds", {}).get("Width", 0) > 800), None)
if target is None:
    raise SystemExit("no ZMART window on screen — is the viewer open?")
wid = target["kCGWindowNumber"]
bounds = target["kCGWindowBounds"]
print(f"window {wid} at {bounds['Width']:.0f}x{bounds['Height']:.0f}")

B = "/Users/thomdehoog/Documents/Projects/ZMART-microscopy-thy1-linked-spiral/zmart-viewer/backend"
req = urllib.request.Request(
    "http://127.0.0.1:8848/api/stores/replay",
    data=json.dumps({"path": B + "/test_stores/test_grid_16",
                     "every": 0.3}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
import threading
threading.Thread(target=lambda: urllib.request.urlopen(req), daemon=True).start()
time.sleep(2.5)

samples = []
for step in range(70):
    subprocess.run(["screencapture", "-x", "-o", "-l", str(wid),
                    "/tmp/native_frame.png"], check=True)
    art = np.asarray(Image.open("/tmp/native_frame.png").convert("L"),
                     dtype=np.float32) / 255.0
    # The picture area: left ~72% of the window, below the top bar.
    h, w = art.shape
    lit = float((art[int(h*0.1):int(h*0.95), :int(w*0.7)] > 0.08).mean())
    samples.append(round(lit, 3))
    time.sleep(0.12)
peak = max(samples)
first = next((i for i, s in enumerate(samples) if s > peak * 0.3), None)
after = samples[first:] if first is not None else []
drops = [(i, after[i-1], after[i]) for i in range(1, len(after))
         if after[i] < after[i-1] * 0.6][:12]
print(f"peak {peak}, drops-after-visible: {len(drops)} {drops}")
print("trace:", samples)
