"""REVIEW EVIDENCE: do the two independent validators agree, document for document?"""
import json, sys, copy
sys.path.insert(0, "<path to ZMART-microscopy>")
sys.path.insert(0, "<path to zmart-viewer>")
from application.parts.storage.acquisition_description import (
    validate_acquisition_description as micro)
from zmart_viewer.acquisition import validate_acquisition_description as viewer

def base(**over):
    ch = {"key": "488", "index": 0, "label": "GFP", "color": "00ff00",
          "range": {"min": 0, "max": 65535},
          "displayWindow": {"start": 300, "end": 4200},
          "windowProvenance": {"method": "preset", "resolvedFrom": "acquisition-record"}}
    ch.update(over)
    return {"schema": "zmart-acquisition-display/1", "acquisitionType": "overview",
            "channels": [ch]}

def two(a, b):
    return {"schema": "zmart-acquisition-display/1", "acquisitionType": "overview",
            "channels": [a, b]}

C = lambda **o: dict({"key": "488", "index": 0, "label": "GFP",
                      "range": {"min": 0, "max": 65535}}, **o)

CASES = {
  "plain": base(),
  "unknown top-level key": dict(base(), somethingNew=1),
  "unknown channel key": base(somethingNew=1),
  "unknown provenance key": base(windowProvenance={"method": "preset",
        "resolvedFrom": "acquisition-record", "somethingNew": 1}),
  "index as float 0.0": base(index=0.0),
  "index as bool True": base(index=True),
  "start as bool": base(displayWindow={"start": False, "end": 4200}),
  "range min bool": base(range={"min": False, "max": 65535}),
  "NaN in range": base(range={"min": float("nan"), "max": 65535}),
  "Infinity in window": base(displayWindow={"start": 300, "end": float("inf")}),
  "colour lowercase": base(color="00ff00"),
  "colour 7 digits": base(color="00ff000"),
  "colour with #": base(color="#00ff0"),
  "key whitespace only": base(key="   "),
  "label whitespace padded": base(label="  GFP  "),
  "duplicate key": two(C(key="488", index=0), C(key="488", index=1)),
  "duplicate index": two(C(key="488", index=0), C(key="561", index=0)),
  "shuffled indices": two(C(key="561", index=1), C(key="488", index=0)),
  "indices 1..2": two(C(key="488", index=1), C(key="561", index=2)),
  "window without range": {"schema": "zmart-acquisition-display/1",
        "acquisitionType": "overview", "channels": [
        {"key": "488", "index": 0, "label": "GFP",
         "displayWindow": {"start": 300, "end": 4200},
         "windowProvenance": {"method": "p", "resolvedFrom": "r"}}]},
  "range equal min max": base(range={"min": 5, "max": 5}),
  "sampleCount negative": base(windowProvenance={"method": "p", "resolvedFrom": "r",
        "sampleCount": -1}),
  "algorithm non-string": base(windowProvenance={"method": "p", "resolvedFrom": "r",
        "algorithm": 7}),
  "channels not a list": {"schema": "zmart-acquisition-display/1",
        "acquisitionType": "overview", "channels": {"0": C()}},
}

print(f"{'case':<28} {'microscopy':<12} {'viewer':<12} agree")
bad = 0
for name, doc in CASES.items():
    n = len(doc.get("channels") or []) if isinstance(doc.get("channels"), list) else 1
    out = []
    for fn in (micro, viewer):
        try:
            out.append(("accept", json.dumps(fn(copy.deepcopy(doc),
                        acquisition_type="overview", channel_count=n), sort_keys=True)))
        except Exception as e:
            out.append(("reject", type(e).__name__))
    same = out[0][0] == out[1][0] and (out[0][0] == "reject" or out[0][1] == out[1][1])
    if not same:
        bad += 1
    print(f"{name:<28} {out[0][0]:<12} {out[1][0]:<12} {'yes' if same else 'NO'}")
    if not same and out[0][0] == "accept":
        print(f"    micro : {out[0][1]}")
        print(f"    viewer: {out[1][1]}")
print(f"\n{len(CASES)} cases, {bad} disagreement(s)")
