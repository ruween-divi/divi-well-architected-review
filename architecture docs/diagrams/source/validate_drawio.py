"""Structural check of the generated .drawio files (well-formed, unique ids, valid parents, edge endpoints exist)."""
import glob, os, sys
from xml.etree import ElementTree as ET
bad = 0
for f in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "*.drawio"))):
    root = ET.parse(f).getroot()
    cells = root.findall(".//mxCell")
    ids = [c.get("id") for c in cells]
    dup = {i for i in ids if ids.count(i) > 1}
    idset = set(ids)
    probs = []
    if dup: probs.append(f"duplicate ids {dup}")
    for c in cells:
        if c.get("parent") and c.get("parent") not in idset: probs.append(f"{c.get('id')}: bad parent {c.get('parent')}")
        for k in ("source", "target"):
            if c.get(k) and c.get(k) not in idset: probs.append(f"{c.get('id')}: bad {k} {c.get(k)}")
    edges = [c for c in cells if c.get("edge") == "1"]
    print(f"{os.path.basename(f)}: {len(cells)} cells, {len(edges)} edges, {'OK' if not probs else probs}")
    bad += bool(probs)
sys.exit(bad)
