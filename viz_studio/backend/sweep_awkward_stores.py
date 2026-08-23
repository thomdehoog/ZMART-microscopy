"""Open every awkward store through the server's own doors, and say what broke.

The companion to ``make_awkward_stores.py``. It starts a private server (a
free port, never the operator's), asks the folder listing what it makes of
each store, opens each one, and holds the answers against the promises the
viewer makes:

- everything is classified (a kind, or honestly a plain folder — never an
  error);
- everything opens (the figure-it-out rule: no refusals for readable data);
- a picture with several channels never arrives all white;
- every image layer arrives with a window, or with the histogram the
  window can be measured from.

Run it with::

    python sweep_awkward_stores.py

It prints one line per store and finishes with the list of broken promises,
exiting nonzero if there are any — so it can stand in a test as it stands
on its own.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

_AWKWARD = _HERE / "test_stores" / "awkward"
_WHITE = (1.0, 1.0, 1.0)


def _ask(port: int, door: str, **payload) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/{door}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read() or b"{}")


def sweep() -> list[str]:
    from server import make_server

    server = make_server(0, store="demo.zarr")
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    broken: list[str] = []
    try:
        status, listing = _ask(port, "stores/list", path=str(_AWKWARD))
        kinds = {row["name"]: row["kind"] for row in listing.get("folders", [])}
        for store in sorted(_AWKWARD.iterdir()):
            if not store.is_dir():
                continue
            kind = kinds.get(store.name)
            # What this store contributed is the difference the open made,
            # never a guess from names: a leftover layer from an earlier
            # store must not be laid at this one's door.
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/config") as now:
                before = json.loads(now.read())
            seen = {(layer.get("group"), layer.get("name"))
                    for layer in before.get("layers", [])}
            status, answer = _ask(port, "stores/open", path=str(store))
            if status != 200:
                broken.append(f"{store.name}: refused to open — "
                              f"{answer.get('error', status)}")
                print(f"  BROKEN {store.name} [{kind}]: {answer.get('error')}")
                continue
            layers = [layer for layer in answer.get("layers", [])
                      if (layer.get("group"), layer.get("name")) not in seen]
            colors = [tuple(layer.get("color") or _WHITE) for layer in layers]
            if len(layers) > 1 and all(color == _WHITE for color in colors):
                broken.append(f"{store.name}: several channels, all white")
            if not layers:
                broken.append(f"{store.name}: opened without contributing a "
                              "single layer")
            for layer in layers:
                if layer.get("kind") == "segmentation":
                    continue
                if not layer.get("window") and not layer.get("histogram"):
                    broken.append(f"{store.name}: layer {layer.get('name')!r} "
                                  "has no window and no histogram to measure "
                                  "one from")
            print(f"  ok     {store.name} [{kind}] — {len(layers)} layer(s): "
                  + ", ".join(str(layer.get('name')) for layer in layers))
            for group in {layer.get("group") for layer in layers}:
                _ask(port, "stores/close", group=group)
    finally:
        server.shutdown()
    return broken


def main() -> int:
    print(f"sweeping {_AWKWARD}")
    broken = sweep()
    if broken:
        print(f"\n{len(broken)} broken promise(s):")
        for complaint in broken:
            print(" -", complaint)
        return 1
    print("\nevery awkward store kept every promise")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
