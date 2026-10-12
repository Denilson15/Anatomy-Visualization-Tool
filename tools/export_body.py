"""
Export the full body from the Z-Anatomy Blender file.

Bones: both sides. Muscles, attachment patches and nerves: right side and
midline (the left side is mirrored in the browser). Meshes are decimated to
keep the download phone-friendly.

Output (OUT_DIR/raw_body.json):
    {
        "bones":     { name: {positions, indices, collections} },
        "muscles":   { name: {positions, indices, collections} },
        "patches":   { name: {positions, indices} },
        "ligaments": { name: {positions, indices, collections} },
        "nerves":    { name: {paths, collections} },
        "landmarks": { name: {bone, point} }
    }

Usage:
    python export_body.py <blend> <out_dir>
"""

import json
import re
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils.bvhtree import BVHTree


BLEND_PATH = sys.argv[1]
OUT_DIR = Path(sys.argv[2])
OUT_DIR.mkdir(parents=True, exist_ok=True)

SCALE = 100.0  # metres -> centimetres

BONE_RATIO = 0.35
MUSCLE_RATIO = 0.3
MIN_VERTICES_TO_DECIMATE = 400

SKIP_BONE_WORDS = [
    "Sinus", "Skeletal system", "Incus", "Malleus", "Stapes", "cells of ethmoid",
    "Arytenoid", "Corniculate", "Cricoid", "Thyroid cartilage", "nasal septal",
    "alar cartilage", "Sesamoid",
]

SKIP_MUSCLE_COLLECTIONS = {
    "Laryngeal muscles",
    "Pharyngeal muscles",
    "Oculomotor nerve (III)",
    "Digestive system",
}

LIGAMENT_RATIO = 0.4

# Joint structures that are not exported: a label group, and a growth cartilage
# that is bone in an adult.
SKIP_JOINT_NAMES = {"Joints.g", "Triradiate cartilage.r"}
LABEL_SUFFIXES = (".j", ".g", ".i", ".t")

PATCH_PATTERN = re.compile(r"\.(o|e)\d*r$")


def collections_of(obj):
    return sorted(c.name for c in obj.users_collection)


def mesh_data(obj, depsgraph, ratio=None):
    """World-space triangle mesh read straight from the mesh data (no evaluation).

    Reading obj.data with foreach_get keeps memory flat; evaluating every
    object in this 7,000-object scene exhausts memory.
    """
    mesh = obj.data
    mesh.calc_loop_triangles()

    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)

    matrix = np.array(obj.matrix_world, dtype=np.float64)
    world = co @ matrix[:3, :3].T + matrix[:3, 3]

    tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
    mesh.loop_triangles.foreach_get("vertices", tris)

    entry = {
        "positions": np.round(world * SCALE, 2).reshape(-1).tolist(),
        "indices": tris.tolist(),
    }
    if ratio and count >= MIN_VERTICES_TO_DECIMATE:
        entry["decimate"] = ratio
    return entry


def curve_paths(obj):
    paths = []
    for spline in obj.data.splines:
        if spline.type == "BEZIER":
            raw = [p.co for p in spline.bezier_points]
        else:
            raw = [p.co.xyz for p in spline.points]
        points = [[round(c * SCALE, 2) for c in (obj.matrix_world @ co)] for co in raw]
        if len(points) >= 2:
            paths.append(points)
    return paths


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND_PATH, load_ui=False)
    depsgraph = None

    out = {
        "bones": {},
        "muscles": {},
        "patches": {},
        "ligaments": {},
        "nerves": {},
        "landmarks": {},
    }

    objects = list(bpy.data.objects)

    for obj in objects:
        if obj.type != "MESH":
            continue
        names = collections_of(obj)

        if "1: Skeletal system" in names and len(obj.data.vertices) > 50:
            if any(word in obj.name for word in SKIP_BONE_WORDS):
                continue
            entry = mesh_data(obj, depsgraph, BONE_RATIO)
            entry["collections"] = names
            out["bones"][obj.name] = entry

        elif "Muscles" in names and "4: Muscular system" in names:
            if obj.name.endswith(".l") or SKIP_MUSCLE_COLLECTIONS & set(names):
                continue
            if len(obj.data.vertices) < 30:
                continue
            entry = mesh_data(obj, depsgraph, MUSCLE_RATIO)
            entry["collections"] = names
            out["muscles"][obj.name] = entry

        elif "2: Muscular insertions" in names and PATCH_PATTERN.search(obj.name):
            out["patches"][obj.name] = mesh_data(obj, depsgraph)

        elif "3: Joints" in names:
            # Every ligament, capsule, disc, labrum, meniscus and membrane:
            # right side and midline only, like the muscles.
            if obj.name.endswith(".l") or obj.name.endswith(LABEL_SUFFIXES):
                continue
            if obj.name in SKIP_JOINT_NAMES or len(obj.data.vertices) < 3:
                continue
            entry = mesh_data(obj, depsgraph, LIGAMENT_RATIO)
            entry["collections"] = names
            out["ligaments"][obj.name] = entry

    for obj in objects:
        if obj.type != "CURVE":
            continue
        names = collections_of(obj)
        if "Peripheral nervous system" not in names or obj.name.endswith(".l"):
            continue
        paths = curve_paths(obj)
        if paths:
            out["nerves"][obj.name] = {"paths": paths, "collections": names}

    # Landmarks: the end of each two-vertex ".j" label line that sits on a bone.
    trees = {}
    for name in out["bones"]:
        obj = bpy.data.objects[name]
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.transform(obj.matrix_world)
        trees[name] = BVHTree.FromBMesh(bm)
        bm.free()

    for obj in objects:
        if obj.type != "MESH" or not obj.name.endswith(".j") or len(obj.data.vertices) != 2:
            continue
        best = None
        for vert in obj.data.vertices:
            world = obj.matrix_world @ vert.co
            for bone, tree in trees.items():
                hit = tree.find_nearest(world, 0.02)
                if hit[0] is not None and (best is None or hit[3] < best[0]):
                    best = (hit[3], bone, hit[0])
        if best is not None and best[0] * SCALE < 1.5:
            out["landmarks"][obj.name[:-2]] = {
                "bone": best[1],
                "point": [round(c * SCALE, 2) for c in best[2]],
            }

    (OUT_DIR / "raw_body.json").write_text(json.dumps(out, separators=(",", ":")))

    for key in ("bones", "muscles", "patches", "ligaments", "nerves", "landmarks"):
        items = out[key]
        vertices = sum(len(v.get("positions", [])) // 3 for v in items.values())
        print(f"EXPORTED {key}: {len(items)} items, {vertices} vertices")


main()
