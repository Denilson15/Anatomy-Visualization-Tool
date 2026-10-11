"""
Export the right lower-limb structures used by the knee/thigh prototype.

Outputs (into OUT_DIR):
    meshes.json     -- triangle meshes (bones, muscles, ligaments, attachment patches)
    nerves.json     -- nerve paths as point lists
    landmarks.json  -- bony landmark points snapped to their bone
"""

import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils.bvhtree import BVHTree


BLEND_PATH = sys.argv[1]
OUT_DIR = Path(sys.argv[2])
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Atlas units are converted to centimetres in the output.
SCALE = 100.0


BONES = [
    "Hip bone.r",
    "Sacrum",
    "Femur.r",
    "Patella.r",
    "Tibia.r",
    "Fibula.r",
    "Talus.r",
    "Calcaneus.r",
]

MUSCLES = [
    "Rectus femoris muscle.r",
    "Vastus lateralis muscle.r",
    "Vastus medialis muscle.r",
    "Vastus intermedius muscle.r",
    "Sartorius muscle.r",
    "Gracilis muscle.r",
    "Semitendinosus muscle.r",
    "Semimembranosus muscle.r",
    "Long head of biceps femoris.r",
    "Short head of biceps femoris.r",
    "Popliteus muscle.r",
    "Medial head of gastrocnemius.r",
    "Lateral head of gastrocnemius.r",
    "Calcaneal tendon.r",
]

LIGAMENTS = [
    "Anterior cruciate ligament.r",
    "Posterior cruciate ligament.r",
    "Fibular collateral ligament.r",
    "Superficial part of tibial collateral ligament.r",
    "Deep part of tibial collateral ligament.r",
    "Medial meniscus.r",
    "Lateral meniscus.r",
]

PATCHES = [
    "Rectus femoris muscle.or",
    "Vastus lateralis muscle.or",
    "Vastus medialis muscle.or",
    "Vastus intermedius muscle.or",
    "Quadriceps femoris muscle.er",
    "Patellar ligament.or",
    "Patellar ligament.er",
    "Sartorius muscle.or",
    "Sartorius muscle.er",
    "Gracilis muscle.or",
    "Gracilis muscle.er",
    "Semitendinosus muscle.or",
    "Semitendinosus muscle.er",
    "Semimembranosus muscle.or",
    "Semimembranosus muscle.er",
    "Long head of biceps femoris.or",
    "Short head of biceps femoris.or",
    "Biceps femoris muscle.er",
    "Popliteus muscle.or",
    "Popliteus muscle.er",
    "Medial head of gastrocnemius.or",
    "Lateral head of gastrocnemius.or",
    "Gastrocnemius muscle.er",
    "Triceps surae muscle.er",
]

NERVES = [
    "Femoral nerve.r",
    "Obturator nerve.r",
    "Anterior branch of obturator nerve.r",
    "Posterior branch of obturator nerve.r",
    "Sciatic nerve.r",
    "Tibial nerve.r",
    "Common fibular nerve.r",
]


def world_mesh(obj, depsgraph):
    """Return (positions, triangles) of the evaluated object in world space."""
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.transform(obj.matrix_world)

    positions = []
    for vert in bm.verts:
        positions.extend(round(c * SCALE, 2) for c in vert.co)

    bm.verts.index_update()
    triangles = []
    for face in bm.faces:
        triangles.extend(v.index for v in face.verts)

    bm.free()
    evaluated.to_mesh_clear()
    return positions, triangles


def curve_points(obj):
    """Return the world-space control polyline(s) of a curve object."""
    paths = []
    for spline in obj.data.splines:
        if spline.type == "BEZIER":
            raw = [p.co for p in spline.bezier_points]
        else:
            raw = [p.co.xyz for p in spline.points]

        points = []
        for co in raw:
            world = obj.matrix_world @ co
            points.append([round(c * SCALE, 2) for c in world])

        if len(points) >= 2:
            paths.append(points)
    return paths


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND_PATH, load_ui=False)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects = bpy.data.objects

    missing = []
    meshes = {}

    for kind, names in (
        ("bone", BONES),
        ("muscle", MUSCLES),
        ("ligament", LIGAMENTS),
        ("patch", PATCHES),
    ):
        for name in names:
            obj = objects.get(name)
            if obj is None or obj.type != "MESH":
                missing.append(name)
                continue

            positions, triangles = world_mesh(obj, depsgraph)
            meshes[name] = {
                "kind": kind,
                "positions": positions,
                "indices": triangles,
            }

    nerves = {}
    for name in NERVES:
        obj = objects.get(name)
        if obj is None or obj.type != "CURVE":
            missing.append(name)
            continue
        nerves[name] = curve_points(obj)

    # Landmarks: two-vertex ".j" label meshes; keep the end nearest a bone.
    trees = {}
    for name in BONES:
        obj = objects.get(name)
        if obj is None:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.transform(obj.matrix_world)
        trees[name] = BVHTree.FromBMesh(bm)
        bm.free()
        evaluated.to_mesh_clear()

    landmarks = {}
    for obj in objects:
        if obj.type != "MESH" or not obj.name.endswith(".j"):
            continue
        if len(obj.data.vertices) != 2:
            continue

        best = None
        for vert in obj.data.vertices:
            world = obj.matrix_world @ vert.co
            for bone_name, tree in trees.items():
                hit = tree.find_nearest(world)
                if hit[0] is None:
                    continue
                distance = hit[3]
                if best is None or distance < best[0]:
                    best = (distance, bone_name, hit[0])

        # Keep landmarks lying on (within 1.5 cm of) one of our bones.
        if best is not None and best[0] * SCALE < 1.5:
            landmarks[obj.name[:-2]] = {
                "bone": best[1],
                "point": [round(c * SCALE, 2) for c in best[2]],
            }

    (OUT_DIR / "meshes.json").write_text(json.dumps(meshes, separators=(",", ":")))
    (OUT_DIR / "nerves.json").write_text(json.dumps(nerves, indent=4))
    (OUT_DIR / "landmarks.json").write_text(json.dumps(landmarks, indent=4))

    total_vertices = sum(len(m["positions"]) // 3 for m in meshes.values())
    print("EXPORTED meshes:", len(meshes), "vertices:", total_vertices)
    print("EXPORTED nerves:", len(nerves), "landmarks:", len(landmarks))
    print("MISSING:", missing)


main()
