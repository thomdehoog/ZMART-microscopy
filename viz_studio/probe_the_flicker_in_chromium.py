import sys, threading, json, urllib.request
sys.path.insert(0, "/Users/thomdehoog/Documents/Projects/ZMART-microscopy-thy1-linked-spiral/viz_studio/backend")
sys.path.insert(0, "/Users/thomdehoog/Documents/Projects/ZMART-microscopy-thy1-linked-spiral/viz_studio/tests")
from server import make_server
from pixels import fraction_lit
from playwright.sync_api import sync_playwright

B = "/Users/thomdehoog/Documents/Projects/ZMART-microscopy-thy1-linked-spiral/viz_studio/backend"
server = make_server(0, store="demo.zarr")
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1200, "height": 800})
    page.goto(f"http://127.0.0.1:{port}", wait_until="networkidle")
    page.wait_for_timeout(3500)
    # The operator's exact road: sequential tab, the grid, Open.
    page.get_by_role("button", name="open images").click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="open positions sequentially").click()
    page.wait_for_timeout(400)
    page.get_by_label("folder path").fill(B + "/test_stores/test_grid_16")
    page.keyboard.press("Enter")
    page.wait_for_timeout(600)
    page.get_by_role("button", name="open as a live run").click()
    page.get_by_role("dialog", name="load data").wait_for(state="detached")
    # Sample continuously through every landing (16 x ~0.5s each + slack).
    samples = []
    for _ in range(140):
        samples.append(round(fraction_lit(page), 3))
        page.wait_for_timeout(100)
    b.close()
server.shutdown()
peak = max(samples)
settled = next((i for i, s in enumerate(samples) if s > 0.2), None)
after = samples[settled:] if settled is not None else []
drops = [(i, s) for i, s in enumerate(after)
         if i and s < after[i - 1] * 0.5]
print(f"peak {peak}, first-visible at sample {settled}, "
      f"drops-after-visible: {len(drops)} {drops[:10]}")
print("tail:", after[-20:])
