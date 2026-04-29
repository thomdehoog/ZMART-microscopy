"""Dump the XML tree structure of the HiRes job in the PythonInspect LRP."""
import xml.etree.ElementTree as ET
from pathlib import Path

tdir = Path.home() / "AppData/Roaming/Leica Microsystems/LAS X/MatrixScreener6/User_0/ScanningTemplates"
tree = ET.parse(tdir / "{ScanningTemplate}_PythonInspect.lrp")
root = tree.getroot()

def pt(e, d=0):
    ka = {k: e.get(k) for k in ("Name","BlockName","UserSettingName","RoiType","ROISetType") if e.get(k)}
    n = len(list(e))
    a = " ".join(f"{k}={v}" for k,v in ka.items())
    if a: a = " " + a
    print("  "*d + f"{e.tag}{a} [{n}]")
    for c in e:
        pt(c, d+1)

for block in root.findall("LDM_Block_Sequence_Block"):
    seq = block.find(".//LDM_Block_Sequential")
    if seq is not None and seq.get("BlockName") == "HiRes":
        pt(block)
