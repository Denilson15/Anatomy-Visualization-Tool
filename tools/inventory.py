"""
Summarise the atlas: every mesh in the skeletal and muscular systems with
vertex counts and collections, written as JSON for later scripts.

Usage:
    python inventory.py <blend> <out.json>
"""

import json
import sys

import bpy


BLEND_PATH = sys.argv[1]
OUT_PATH = sys.argv[2]

bpy.ops.wm.open_mainfile(filepath=BLEND_PATH, load_ui=False)

records = []
for obj in bpy.data.objects:
    if obj.type not in {"MESH", "CURVE"}:
        continue

    collections = sorted(c.name for c in obj.users_collection)
    vertex_count = len(obj.data.vertices) if obj.type == "MESH" else 0

    records.append({
        "name": obj.name,
        "type": obj.type,
        "vertices": vertex_count,
        "collections": collections,
        "parent": obj.parent.name if obj.parent else None,
    })

# Collection tree, so regions and compartments can be read off it.
tree = {}
for collection in bpy.data.collections:
    tree[collection.name] = sorted(child.name for child in collection.children)

with open(OUT_PATH, "w") as handle:
    json.dump({"objects": records, "collections": tree}, handle, indent=4)

print("objects:", len(records), "collections:", len(tree))
