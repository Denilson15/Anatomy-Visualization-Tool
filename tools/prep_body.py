"""
Build the browser assets for the full-body atlas from raw_body.json.

Writes into OUT_DIR:
    body.json           rig, controls, region tree, structure metadata, mesh index
    skeleton.bin        every bone (always loaded first)
    region-<id>.bin     muscles, attachment patches and ligaments for one region
                        (loaded in the background after the skeleton)

Coordinates are converted from Blender (Z-up, -Y anterior) to three.js
(Y-up, +Z anterior), in centimetres. The body's right side is at negative x.

Usage:
    python prep_body.py <raw_body.json> <out_dir>
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyfqmr
from scipy.spatial import cKDTree


RAW = json.loads(Path(sys.argv[1]).read_text())
OUT = Path(sys.argv[2])
NOTES = Path(__file__).resolve().parent.parent / "notes"
OUT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def to_three(points):
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return np.stack([p[:, 0], p[:, 2], -p[:, 1]], axis=1)


def decimate(positions, indices, ratio):
    simplifier = pyfqmr.Simplify()
    simplifier.setMesh(positions, indices.reshape(-1, 3))
    target = max(int(len(indices) // 3 * ratio), 60)
    simplifier.simplify_mesh(target_count=target, aggressiveness=6, preserve_border=True, verbose=0)
    vertices, faces, _ = simplifier.getMesh()
    return np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.uint32).reshape(-1)


def load_mesh(entry):
    positions = to_three(entry["positions"])
    indices = np.asarray(entry["indices"], dtype=np.uint32)
    if entry.get("decimate"):
        positions, indices = decimate(positions, indices, entry["decimate"])
    return positions, indices


def fit_sphere(points):
    a = np.hstack([2 * points, np.ones((len(points), 1))])
    b = (points ** 2).sum(axis=1)
    solution, *_ = np.linalg.lstsq(a, b, rcond=None)
    centre = solution[:3]
    return centre, float(np.sqrt(solution[3] + centre @ centre))


def unit(vector):
    vector = np.asarray(vector, dtype=np.float64)
    return vector / np.linalg.norm(vector)


def rotate(points, pivot, axis, degrees):
    """Rodrigues rotation of points about an axis through pivot."""
    axis = unit(axis)
    theta = np.radians(degrees)
    p = np.atleast_2d(points) - pivot
    rotated = (
        p * np.cos(theta)
        + np.cross(axis, p) * np.sin(theta)
        + np.outer(p @ axis, axis) * (1 - np.cos(theta))
    )
    return rotated + pivot


# ---------------------------------------------------------------------------
# Bones -> segments
# ---------------------------------------------------------------------------

HAND_WORDS = ("Scaphoid", "Lunate", "Triquetrum", "Pisiform", "Trapezium", "Trapezoid",
              "Capitate", "Hamate", "metacarpal", "of hand")
FOOT_WORDS = ("Talus", "Calcaneus", "Navicular", "Cuboid", "cuneiform", "metatarsal", "of foot")
HEAD_WORDS = ("Frontal", "Parietal", "Occipital", "Temporal", "Sphenoid", "Ethmoid", "Maxilla",
              "Mandible", "Zygomatic", "Nasal", "Lacrimal", "Palatine", "Vomer", "concha",
              "incisor", "canine", "premolar", "molar")


def bone_segment(name):
    right = name.endswith(".r")
    left = name.endswith(".l")

    if name.startswith("Vertebra L"):
        return "lumbar"
    if name.startswith("Vertebra T") or "rib" in name or "sternum" in name or "Xiphoid" in name:
        return "thorax"
    if name.startswith("Vertebra C") or name.startswith("Atlas") or name.startswith("Axis") or name.startswith("Hyoid"):
        return "neck"
    if any(word in name for word in HEAD_WORDS):
        return "head"
    if name.startswith(("Hip bone", "Sacrum", "Coccyx")):
        return "pelvis"
    if name.startswith(("Clavicle", "Scapula")):
        return "thorax"

    upper = name.startswith(("Humerus", "Radius", "Ulna")) or any(w in name for w in HAND_WORDS)
    lower = name.startswith(("Femur", "Patella", "Tibia", "Fibula")) or any(w in name for w in FOOT_WORDS)

    if left and upper:
        return "thorax"
    if left and lower:
        return "pelvis"
    if right:
        if name.startswith("Humerus"):
            return "humerus"
        if name.startswith("Ulna"):
            return "ulna"
        if name.startswith("Radius"):
            return "radius"
        if any(w in name for w in HAND_WORDS):
            return "hand"
        if name.startswith("Femur"):
            return "femur"
        if name.startswith("Patella"):
            return "patella"
        if name.startswith(("Tibia", "Fibula")):
            return "tibia"
        if any(w in name for w in FOOT_WORDS):
            return "foot"
    return "head"


SEGMENTS = [
    "pelvis", "lumbar", "thorax", "neck", "head",
    "humerus", "ulna", "radius", "hand",
    "femur", "patella", "tibia", "foot",
]
SEGMENT_INDEX = {name: i for i, name in enumerate(SEGMENTS)}

PARENT = {
    "pelvis": None,
    "lumbar": "pelvis",
    "thorax": "lumbar",
    "neck": "thorax",
    "head": "neck",
    "humerus": "thorax",
    "ulna": "humerus",
    "radius": "ulna",
    "hand": "radius",
    "femur": "pelvis",
    "patella": "femur",
    "tibia": "femur",
    "foot": "tibia",
}


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------

REGION_TREE = {
    "body": {"name": "Full body", "children": ["head-neck", "trunk", "upper-limb", "lower-limb"]},
    "head-neck": {"name": "Head and neck", "parent": "body", "children": ["head", "neck"]},
    "trunk": {"name": "Trunk and spine", "parent": "body", "children": ["back", "thorax-area", "abdomen"]},
    "upper-limb": {"name": "Upper limb", "parent": "body", "children": ["shoulder", "arm", "forearm", "hand-area"]},
    "lower-limb": {"name": "Lower limb", "parent": "body", "children": ["hip-gluteal", "thigh-knee", "leg-ankle", "foot-area"]},
    "head": {"name": "Head", "parent": "head-neck"},
    "neck": {"name": "Neck", "parent": "head-neck"},
    "back": {"name": "Back", "parent": "trunk"},
    "thorax-area": {"name": "Chest wall", "parent": "trunk"},
    "abdomen": {"name": "Abdomen", "parent": "trunk"},
    "shoulder": {"name": "Shoulder", "parent": "upper-limb"},
    "arm": {"name": "Arm and elbow", "parent": "upper-limb"},
    "forearm": {"name": "Forearm and wrist", "parent": "upper-limb"},
    "hand-area": {"name": "Hand", "parent": "upper-limb"},
    "hip-gluteal": {"name": "Hip and gluteal region", "parent": "lower-limb"},
    "thigh-knee": {"name": "Thigh and knee", "parent": "lower-limb"},
    "leg-ankle": {"name": "Leg and ankle", "parent": "lower-limb"},
    "foot-area": {"name": "Foot", "parent": "lower-limb"},
}

# Which file each area's meshes live in.
AREA_REGION = {
    "head": "head-neck", "neck": "head-neck",
    "back": "trunk", "thorax-area": "trunk", "abdomen": "trunk",
    "shoulder": "upper-limb", "arm": "upper-limb", "forearm": "upper-limb", "hand-area": "upper-limb",
    "hip-gluteal": "lower-limb", "thigh-knee": "lower-limb", "leg-ankle": "lower-limb", "foot-area": "lower-limb",
}

AREA_CONTROLS = {
    "head": ["neckFlex", "neckRot"],
    "neck": ["neckFlex", "neckRot"],
    "back": ["trunkFlex", "trunkLat", "trunkRot"],
    "thorax-area": ["trunkFlex", "trunkRot"],
    "abdomen": ["trunkFlex", "trunkLat", "trunkRot"],
    "shoulder": ["shoulderFlex", "shoulderAbd", "shoulderRot"],
    "arm": ["shoulderFlex", "elbowFlex"],
    "forearm": ["elbowFlex", "forearmPro", "wristFlex"],
    "hand-area": ["wristFlex", "wristDev"],
    "hip-gluteal": ["hipFlex", "hipAbd", "hipRot"],
    "thigh-knee": ["hipFlex", "knee"],
    "leg-ankle": ["knee", "ankle"],
    "foot-area": ["ankle"],
}

REGION_CONTROLS = {
    "body": ["trunkFlex", "neckFlex", "shoulderAbd", "elbowFlex", "hipFlex", "knee"],
    "head-neck": ["neckFlex", "neckRot"],
    "trunk": ["trunkFlex", "trunkLat", "trunkRot"],
    "upper-limb": ["shoulderFlex", "shoulderAbd", "shoulderRot", "elbowFlex", "forearmPro", "wristFlex"],
    "lower-limb": ["hipFlex", "hipAbd", "hipRot", "knee", "ankle"],
}

# Bones listed in each area's "Bones" group.
AREA_BONE_SEGMENTS = {
    "head": ["head"], "neck": ["neck"],
    "back": ["lumbar", "thorax"], "thorax-area": ["thorax"], "abdomen": ["lumbar", "pelvis"],
    "shoulder": ["thorax", "humerus"], "arm": ["humerus", "ulna", "radius"],
    "forearm": ["ulna", "radius", "hand"], "hand-area": ["hand"],
    "hip-gluteal": ["pelvis", "femur"], "thigh-knee": ["pelvis", "femur", "patella", "tibia"],
    "leg-ankle": ["tibia", "foot"], "foot-area": ["foot"],
}


TISSUE_WORDS = (
    "retinaculum", "aponeurosis", "Linea alba", "Inguinal ligament", "transverse metatarsal ligament",
    "transverse metacarpal ligament", "Trochlea of", "Intermediate tendon", "Tendinous arch",
    "Iliotibial tract", "Calcaneal tendon", "Tendon of",
)

PELVIC_FLOOR = ("Coccygeus", "Iliococcygeus", "Pubococcygeus", "Pubo-analis")


def is_tissue(name):
    return any(word.lower() in name.lower() for word in TISSUE_WORDS)


def muscle_area(collections, name=""):
    c = set(collections)
    if name.startswith(PELVIC_FLOOR):
        return "abdomen"
    if "Right upper limb" in c or "Muscles of upper limb" in c:
        if "Muscles of hand" in c:
            return "hand-area"
        if c & {"Anterior compartment of forearm", "Posterior compartment of forearm"}:
            return "forearm"
        if c & {"Anterior compartment of arm", "Posterior compartment of arm"}:
            return "arm"
        return "shoulder"
    if "Right lower limb" in c or "Muscles of lower limb" in c:
        if "Muscles of foot" in c:
            return "foot-area"
        if c & {"Anterior compartment of leg", "Posterior compartment of leg", "Lateral compartment of leg"}:
            return "leg-ankle"
        if c & {"Anterior compartment of thigh", "Medial compartment of thigh", "Posterior compartment of thigh"}:
            return "thigh-knee"
        return "hip-gluteal"
    if c & {"Back", "Erector spinae", "Transversospinal muscles", "Hypaxial muscles of back", "Rotatores"}:
        return "back"
    if c & {"Muscles of abdomen", "Abdominal part of muscular system"}:
        return "abdomen"
    if c & {"Head", "Muscles of head", "Facial muscles"}:
        return "head"
    if c & {"Neck", "Muscles of neck", "Suboccipital muscles"}:
        return "neck"
    return "thorax-area"


GROUP_COLLECTIONS = [
    "Rotator cuff muscles", "Deltoid muscle", "Pectoralis major muscle", "Trapezius muscle",
    "Anterior compartment of arm", "Posterior compartment of arm",
    "Anterior compartment of forearm", "Posterior compartment of forearm",
    "Muscles of hand",
    "Superficial gluteal muscles", "Deep gluteal muscles",
    "Anterior compartment of thigh", "Medial compartment of thigh", "Posterior compartment of thigh",
    "Anterior compartment of leg", "Lateral compartment of leg", "Posterior compartment of leg",
    "Muscles of foot",
    "Erector spinae", "Transversospinal muscles", "Hypaxial muscles of back", "Suboccipital muscles",
    "Muscles of abdomen", "Facial muscles", "Muscles of neck",
]

GROUP_NAMES = {
    "Anterior compartment of thigh": "Anterior thigh",
    "Medial compartment of thigh": "Medial thigh",
    "Posterior compartment of thigh": "Hamstrings",
    "Anterior compartment of leg": "Anterior leg",
    "Lateral compartment of leg": "Lateral leg",
    "Posterior compartment of leg": "Calf",
    "Anterior compartment of arm": "Anterior arm",
    "Posterior compartment of arm": "Posterior arm",
    "Anterior compartment of forearm": "Anterior forearm",
    "Posterior compartment of forearm": "Posterior forearm",
    "Superficial gluteal muscles": "Superficial gluteal",
    "Deep gluteal muscles": "Deep gluteal",
    "Rotator cuff muscles": "Rotator cuff",
    "Hypaxial muscles of back": "Back muscles",
}


def muscle_group(collections, area, mesh_name=""):
    if mesh_name.startswith(PELVIC_FLOOR):
        return "Pelvic floor"
    for name in GROUP_COLLECTIONS:
        if name in collections:
            return name
    return f"Other muscles ({REGION_TREE[area]['name'].lower()})"


def principal_ends(points):
    """Indices of the two vertices at either end of the muscle's long axis.

    Used as a fallback line of pull when the atlas has no attachment patch.
    """
    centred = points - points.mean(axis=0)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    projection = centred @ vt[0]
    return [int(np.argmin(projection)), int(np.argmax(projection))]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def display_name(mesh_name):
    name = re.sub(r"\.(r|l)$", "", mesh_name)
    name = name.strip("()")
    name = re.sub(r" muscle$", "", name)
    name = re.sub(r" muscle ", " ", name)
    return name[0].upper() + name[1:]


NERVE_PATTERN = re.compile(r"(nerve|nerve \([IVX]+\))$")


def choose_nerve(collections, nerve_sizes):
    nerves = [c for c in collections if NERVE_PATTERN.search(c)]
    if not nerves:
        return None
    # The most specific nerve is the one with the fewest muscles in it.
    return min(nerves, key=lambda n: nerve_sizes[n])


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def main():
    print("decimating and converting…")

    bones = {}
    for name, entry in RAW["bones"].items():
        positions, indices = load_mesh(entry)
        bones[name] = {"positions": positions, "indices": indices, "segment": bone_segment(name)}

    muscles = {}
    for name, entry in RAW["muscles"].items():
        positions, indices = load_mesh(entry)
        muscles[name] = {"positions": positions, "indices": indices, "collections": entry["collections"]}

    patches = {name: dict(zip(("positions", "indices"), load_mesh(entry))) for name, entry in RAW["patches"].items()}
    ligaments = {name: dict(zip(("positions", "indices"), load_mesh(entry))) for name, entry in RAW["ligaments"].items()}

    landmarks = {}
    for name, info in RAW["landmarks"].items():
        if info["bone"] in bones:
            landmarks[name] = {
                "bone": info["bone"],
                "segment": bones[info["bone"]]["segment"],
                "point": to_three(info["point"])[0],
            }

    def landmark(name):
        return landmarks[name]["point"]

    def bone_points(name):
        return bones[name]["positions"]

    def centroid(name):
        return bone_points(name).mean(axis=0)

    # --- Pivots ------------------------------------------------------------
    pivots = {}
    axes = {}

    femur = bone_points("Femur.r")
    head_point = landmark("Head of femur")
    hip_centre, hip_radius = fit_sphere(femur[np.linalg.norm(femur - head_point, axis=1) < 3.2])
    pivots["femur"] = hip_centre

    knee_axis = unit(landmark("Lateral epicondyle of femur") - landmark("Medial epicondyle of femur"))
    knee_pivot = (landmark("Lateral epicondyle of femur") + landmark("Medial epicondyle of femur")) / 2
    pivots["tibia"] = knee_pivot
    pivots["patella"] = knee_pivot

    ankle_axis = unit(landmark("Lateral malleolus") - landmark("Medial malleolus"))
    ankle_pivot = (landmark("Lateral malleolus") + landmark("Medial malleolus")) / 2
    pivots["foot"] = ankle_pivot

    humerus = bone_points("Humerus.r")
    humeral_head = landmark("Head of humerus")
    shoulder_centre, shoulder_radius = fit_sphere(humerus[np.linalg.norm(humerus - humeral_head, axis=1) < 2.6])
    pivots["humerus"] = shoulder_centre

    lateral_epicondyle_h = landmark("Lateral epicondyle of humerus")
    medial_epicondyle_h = landmark("Medial epicondyle of humerus")
    elbow_axis = unit(lateral_epicondyle_h - medial_epicondyle_h)
    elbow_pivot = (lateral_epicondyle_h + medial_epicondyle_h) / 2
    pivots["ulna"] = elbow_pivot

    radial_head = landmark("Head of radius")
    ulnar_head = landmark("Head of ulna")
    forearm_axis = unit(ulnar_head - radial_head)
    pivots["radius"] = radial_head

    radial_styloid = landmark("Radial styloid process") if "Radial styloid process" in landmarks else landmark("Styloid process of radius")
    ulnar_styloid = landmark("Ulnar styloid process") if "Ulnar styloid process" in landmarks else landmark("Styloid process of ulna")
    wrist_flex_axis = unit(radial_styloid - ulnar_styloid)
    wrist_pivot = centroid("Capitate bone.r")
    pivots["hand"] = wrist_pivot

    sacrum_base = landmark("Base of sacrum")
    l5 = centroid("Vertebra L5")
    t12 = centroid("Vertebra T12")
    l1 = centroid("Vertebra L1")
    c7 = centroid("Vertebra C7")
    t1 = centroid("Vertebra T1")
    atlas = centroid("Atlas (C1)")
    pivots["lumbar"] = (sacrum_base + l5) / 2
    pivots["thorax"] = (t12 + l1) / 2
    pivots["neck"] = (c7 + t1) / 2
    pivots["head"] = atlas
    pivots["pelvis"] = sacrum_base

    side_axis = np.array([1.0, 0.0, 0.0])
    up_axis = np.array([0.0, 1.0, 0.0])
    front_axis = np.array([0.0, 0.0, 1.0])

    humeral_shaft = unit(elbow_pivot - shoulder_centre)
    femoral_shaft = unit(knee_pivot - hip_centre)
    wrist_dev_axis = unit(np.cross(wrist_flex_axis, unit(centroid("Third metacarpal bone.r") - wrist_pivot)))

    # --- Controls ----------------------------------------------------------
    # Each control rotates one or more segments about an axis through the
    # segment's pivot. `share` splits a motion across segments.
    def control(cid, label, pos, neg, lo, hi, parts, test):
        return {"id": cid, "label": label, "positive": pos, "negative": neg,
                "min": lo, "max": hi, "parts": parts, "test": test}

    skull = np.vstack([bone_points(n) for n in ("Frontal bone", "Parietal bone.r", "Parietal bone.l")]).mean(axis=0)
    nose = centroid("Maxilla.r") * 0.5 + centroid("Maxilla.l") * 0.5
    sternum = centroid("Body of sternum")
    hand_tip = centroid("Third metacarpal bone.r")
    toe = centroid("Second metatarsal bone.r")

    controls = [
        control("trunkFlex", "Trunk flexion", "Trunk flexion", "Trunk extension", -25, 80,
                [["lumbar", side_axis, 0.5], ["thorax", side_axis, 0.5]],
                {"point": skull, "dir": front_axis}),
        control("trunkLat", "Side bend", "Lateral flexion to the right", "Lateral flexion to the left", -30, 30,
                [["lumbar", front_axis, 0.5], ["thorax", front_axis, 0.5]],
                {"point": skull, "dir": -side_axis}),
        control("trunkRot", "Trunk rotation", "Trunk rotation to the right", "Trunk rotation to the left", -40, 40,
                [["lumbar", up_axis, 0.35], ["thorax", up_axis, 0.65]],
                {"point": sternum, "dir": -side_axis}),
        control("neckFlex", "Neck flexion", "Neck flexion", "Neck extension", -55, 50,
                [["neck", side_axis, 0.5], ["head", side_axis, 0.5]],
                {"point": skull, "dir": front_axis}),
        control("neckRot", "Neck rotation", "Neck rotation to the right", "Neck rotation to the left", -70, 70,
                [["neck", up_axis, 0.4], ["head", up_axis, 0.6]],
                {"point": nose, "dir": -side_axis}),
        control("shoulderFlex", "Shoulder flexion", "Shoulder flexion", "Shoulder extension", -45, 150,
                [["humerus", side_axis, 1.0]],
                {"point": elbow_pivot, "dir": front_axis}),
        control("shoulderAbd", "Shoulder abduction", "Shoulder abduction", "Shoulder adduction", -10, 150,
                [["humerus", front_axis, 1.0]],
                {"point": elbow_pivot, "dir": -side_axis}),
        control("shoulderRot", "Shoulder rotation", "Shoulder medial rotation", "Shoulder lateral rotation", -60, 70,
                [["humerus", humeral_shaft, 1.0]],
                {"point": lateral_epicondyle_h, "dir": front_axis}),
        control("elbowFlex", "Elbow flexion", "Elbow flexion", "Elbow extension", 0, 145,
                [["ulna", elbow_axis, 1.0]],
                {"point": wrist_pivot, "dir": front_axis}),
        control("forearmPro", "Pronation", "Pronation", "Supination", 0, 160,
                [["radius", forearm_axis, 1.0]],
                {"point": radial_styloid, "dir": side_axis}),
        control("wristFlex", "Wrist flexion", "Wrist flexion", "Wrist extension", -70, 80,
                [["hand", wrist_flex_axis, 1.0]],
                {"point": hand_tip, "dir": front_axis}),
        control("wristDev", "Wrist deviation", "Ulnar deviation", "Radial deviation", -20, 35,
                [["hand", wrist_dev_axis, 1.0]],
                {"point": hand_tip, "dir": side_axis}),
        control("hipFlex", "Hip flexion", "Hip flexion", "Hip extension", -20, 110,
                [["femur", side_axis, 1.0]],
                {"point": knee_pivot, "dir": front_axis}),
        control("hipAbd", "Hip abduction", "Hip abduction", "Hip adduction", -15, 40,
                [["femur", front_axis, 1.0]],
                {"point": knee_pivot, "dir": -side_axis}),
        control("hipRot", "Hip rotation", "Hip medial rotation", "Hip lateral rotation", -40, 40,
                [["femur", femoral_shaft, 1.0]],
                {"point": landmark("Lateral epicondyle of femur"), "dir": front_axis}),
        control("knee", "Knee flexion", "Knee flexion", "Knee extension", 0, 130,
                [["tibia", knee_axis, 1.0], ["patella", knee_axis, 0.55]],
                {"point": ankle_pivot, "dir": -front_axis}),
        control("ankle", "Ankle", "Plantarflexion", "Dorsiflexion", -20, 45,
                [["foot", ankle_axis, 1.0]],
                {"point": toe, "dir": -up_axis}),
    ]

    # Work out each control's sign so that "positive" means the named motion.
    for item in controls:
        segment, axis, _ = item["parts"][0]
        moved = rotate(item["test"]["point"], pivots[segment], axis, 15)[0]
        delta = moved - item["test"]["point"]
        item["sign"] = 1 if delta @ item["test"]["dir"] > 0 else -1

    # --- Skin weights -------------------------------------------------------
    print("computing skin weights…")
    trees = {}
    for segment in SEGMENTS:
        points = [b["positions"][::2] for b in bones.values() if b["segment"] == segment]
        trees[segment] = cKDTree(np.vstack(points))

    def weights_for(points, sigma):
        distances = np.stack([trees[s].query(points)[0] for s in SEGMENTS], axis=1)
        order = np.argsort(distances, axis=1)
        first = order[:, 0]
        second = order[:, 1]
        d0 = distances[np.arange(len(points)), first]
        d1 = distances[np.arange(len(points)), second]
        w1 = np.exp(-((d1 - d0) / sigma) ** 2)
        w0 = 1.0 / (1.0 + w1)
        return np.stack([first, second], axis=1).astype(np.uint8), np.round(w0 * 255).astype(np.uint8)

    bone_trees = {name: cKDTree(b["positions"]) for name, b in bones.items()}

    def nearest_bone(points):
        centre = points.mean(axis=0)
        return min(bone_trees, key=lambda name: bone_trees[name].query(centre)[0])

    def nearest_segment(points):
        distances = [trees[s].query(points)[0].min() for s in SEGMENTS]
        return SEGMENTS[int(np.argmin(distances))]

    # --- Nerves --------------------------------------------------------------
    nerve_sizes = Counter()
    for entry in muscles.values():
        for c in entry["collections"]:
            if NERVE_PATTERN.search(c):
                nerve_sizes[c] += 1

    # --- Pack binary files ---------------------------------------------------
    class Packer:
        def __init__(self):
            self.chunks = []
            self.size = 0

        def add(self, array):
            data = np.ascontiguousarray(array).tobytes()
            offset = self.size
            self.chunks.append(data)
            self.size += len(data)
            pad = (-self.size) % 4
            if pad:
                self.chunks.append(b"\0" * pad)
                self.size += pad
            return offset

        def write(self, path):
            path.write_bytes(b"".join(self.chunks))

    def pack_mesh(packer, positions, indices):
        entry = {"count": int(len(positions))}
        entry["pos"] = packer.add(positions.astype(np.float32))
        if positions.shape[0] < 65535:
            entry["idx"] = packer.add(indices.astype(np.uint16))
            entry["idxType"] = "u16"
        else:
            entry["idx"] = packer.add(indices.astype(np.uint32))
            entry["idxType"] = "u32"
        entry["idxCount"] = int(len(indices))
        return entry

    mesh_index = {}
    region_packers = {region: Packer() for region in ("head-neck", "trunk", "upper-limb", "lower-limb")}

    skeleton = Packer()
    for name, bone in bones.items():
        entry = pack_mesh(skeleton, bone["positions"], bone["indices"])
        entry.update({"file": "skeleton.bin", "kind": "bone", "segment": bone["segment"]})
        mesh_index[name] = entry
    skeleton.write(OUT / "skeleton.bin")


    tissue_meta = {}
    for name in [n for n in muscles if is_tissue(n)]:
        entry = muscles.pop(name)
        segment = nearest_segment(entry["positions"])
        area = {
            "pelvis": "hip-gluteal", "femur": "thigh-knee", "patella": "thigh-knee", "tibia": "leg-ankle",
            "foot": "foot-area", "humerus": "arm", "ulna": "forearm", "radius": "forearm", "hand": "hand-area",
            "head": "head", "neck": "neck", "thorax": "thorax-area", "lumbar": "abdomen",
        }[segment]
        if "Linea alba" in name or "Inguinal" in name:
            area = "abdomen"
        region = AREA_REGION[area]
        packer = region_packers[region]
        mesh = pack_mesh(packer, entry["positions"], entry["indices"])
        segs, weight = weights_for(entry["positions"], 2.5)
        mesh["segs"] = packer.add(segs)
        mesh["w"] = packer.add(weight)
        mesh.update({"file": f"region-{region}.bin", "kind": "tissue"})
        mesh_index[name] = mesh
        tissue_meta[slug(display_name(name))] = {"name": display_name(name), "mesh": name, "area": area}

    muscle_ids = {name: slug(display_name(name)) for name in muscles}

    muscle_meta = {}
    for name, entry in muscles.items():
        area = muscle_area(entry["collections"], name)
        region = AREA_REGION[area]
        packer = region_packers[region]
        mesh = pack_mesh(packer, entry["positions"], entry["indices"])
        segs, weight = weights_for(entry["positions"], 2.5)
        mesh["segs"] = packer.add(segs)
        mesh["w"] = packer.add(weight)
        mesh.update({"file": f"region-{region}.bin", "kind": "muscle"})
        mesh_index[name] = mesh

        group = muscle_group(entry["collections"], area, name)
        muscle_meta[muscle_ids[name]] = {
            "name": display_name(name),
            "mesh": name,
            "area": area,
            "group": group,
            "groupName": GROUP_NAMES.get(group, group),
            "nerve": choose_nerve(entry["collections"], nerve_sizes),
            "nerveTags": sorted(c for c in entry["collections"] if NERVE_PATTERN.search(c)),
            "ends": principal_ends(entry["positions"]),
            "superficial": "Superficial muscles" in entry["collections"],
            "origins": [],
            "insertions": [],
        }

    mesh_to_id = {name: muscle_ids[name] for name in muscles}
    # --- Patches -> muscles -------------------------------------------------
    base_to_muscles = defaultdict(list)
    for name in muscles:
        base_to_muscles[re.sub(r"\.r$", "", name).lower()].append(name)

    COMPOSITE = {
        "quadriceps femoris muscle": ["Rectus femoris muscle.r", "Vastus lateralis muscle.r",
                                      "Vastus medialis muscle.r", "Vastus intermedius muscle.r"],
        "triceps surae muscle": ["Medial head of gastrocnemius.r", "Lateral head of gastrocnemius.r",
                                 "Soleus muscle.r"],
        "gastrocnemius muscle": ["Medial head of gastrocnemius.r", "Lateral head of gastrocnemius.r"],
        "biceps femoris muscle": ["Long head of biceps femoris.r", "Short head of biceps femoris.r"],
        "iliopsoas muscle": ["Psoas major muscle.r", "Iliacus muscle.r"],
        "erector spinae": [m for m in muscles if any(w in m for w in ("Iliocostalis", "Longissimus", "Spinalis"))],
        "common flexor tendon": [
            "Pronator teres muscle.r", "Flexor carpi radialis muscle.r", "Palmaris longus muscle.r",
            "Flexor carpi ulnaris muscle.r", "Flexor digitorum superficialis muscle.r",
        ],
        "common extensor tendon": [
            "Extensor carpi radialis brevis muscle.r", "Extensor digitorum muscle.r",
            "Extensor digiti minimi muscle.r", "Extensor carpi ulnaris muscle.r",
        ],
    }
    # Patches kept without a muscle owner (the authored content uses them).
    STANDALONE = {"Patellar ligament.or", "Patellar ligament.er"}

    patch_owner = {}
    unmatched = []
    for name in patches:
        match = re.match(r"(.*)\.(o|e)\d*r$", name)
        base, role = match.group(1).lower(), "origin" if match.group(2) == "o" else "insertion"
        owners = base_to_muscles.get(base) or [m for m in COMPOSITE.get(base, []) if m in muscles]
        if not owners:
            key = base.replace(" muscle", "")
            owners = [m for m in muscles if key in m.lower()]
        if not owners and name in STANDALONE:
            patch_owner[name] = {"role": role, "muscles": [], "region": "lower-limb"}
            continue
        if not owners:
            unmatched.append(name)
            continue
        patch_owner[name] = {"role": role, "muscles": owners}

    print(f"patches: {len(patch_owner)} matched, {len(unmatched)} unmatched")

    patch_area = {}
    for name, info in patch_owner.items():
        if info["muscles"]:
            region = AREA_REGION[muscle_meta[mesh_to_id[info["muscles"][0]]]["area"]]
        else:
            region = info["region"]
        packer = region_packers[region]
        mesh = pack_mesh(packer, patches[name]["positions"], patches[name]["indices"])
        mesh.update({
            "file": f"region-{region}.bin",
            "kind": "patch",
            "segment": bones[nearest_bone(patches[name]["positions"])]["segment"],
            "role": info["role"],
            "bone": nearest_bone(patches[name]["positions"]),
            "muscles": [mesh_to_id[m] for m in info["muscles"]],
            "centroid": patches[name]["positions"].mean(axis=0).round(2).tolist(),
        })
        mesh_index[name] = mesh
        for muscle in info["muscles"]:
            key = "origins" if info["role"] == "origin" else "insertions"
            muscle_meta[mesh_to_id[muscle]][key].append(name)

    # Ligaments, capsules, discs, labra, menisci and membranes. The written
    # notes say which joint (and so which area and region) each mesh belongs to.
    ligament_area = {}
    for path in sorted(NOTES.glob("ligaments-*.json")):
        notes = json.loads(path.read_text())
        for entry in notes["ligaments"].values():
            area = notes["joints"][entry["joint"]]["area"]
            for mesh_name in entry["meshes"]:
                ligament_area[mesh_name] = area
    unplaced = sorted(set(ligaments) - set(ligament_area))
    assert not unplaced, f"ligament meshes with no notes: {unplaced}"

    for name, entry in ligaments.items():
        region = AREA_REGION[ligament_area[name]]
        packer = region_packers[region]
        mesh = pack_mesh(packer, entry["positions"], entry["indices"])
        if "meniscus" in name or "meniscotibial" in name:
            # The menisci ride on the tibial plateau.
            mesh["segment"] = "tibia"
        else:
            segs, weight = weights_for(entry["positions"], 0.8)
            mesh["segs"] = packer.add(segs)
            mesh["w"] = packer.add(weight)
        mesh.update({
            "file": f"region-{region}.bin",
            "kind": "ligament",
            "centroid": entry["positions"].mean(axis=0).round(2).tolist(),
        })
        mesh_index[name] = mesh

    for region, packer in region_packers.items():
        packer.write(OUT / f"region-{region}.bin")

    # Nerves, as skinned point lists (small enough for JSON).
    nerve_meta = {}
    for name, entry in RAW["nerves"].items():
        paths = []
        for path in entry["paths"]:
            points = to_three(path)
            segs, weight = weights_for(points, 2.0)
            paths.append({
                "points": points.round(2).tolist(),
                "segs": segs.tolist(),
                "w": weight.tolist(),
            })
        nerve_meta[name] = {"paths": paths, "collections": entry["collections"]}

    # --- Region tree with groups --------------------------------------------
    tree = json.loads(json.dumps(REGION_TREE))
    areas = defaultdict(lambda: defaultdict(list))
    for mid, meta in muscle_meta.items():
        areas[meta["area"]][meta["group"]].append(mid)

    for area in AREA_REGION:
        groups = []
        for group, members in sorted(areas[area].items(), key=lambda kv: (kv[0].startswith("Other"), kv[0])):
            gid = f"{area}--{slug(GROUP_NAMES.get(group, group))}"
            tree[gid] = {
                "name": GROUP_NAMES.get(group, group),
                "parent": area,
                "children": sorted(members, key=lambda m: muscle_meta[m]["name"]),
            }
            groups.append(gid)
        bone_gid = f"{area}--bones"
        tree[bone_gid] = {
            "name": "Bones",
            "parent": area,
            "children": sorted(
                slug(display_name(b)) for b, info in bones.items()
                if info["segment"] in AREA_BONE_SEGMENTS[area] and not b.endswith(".l")
                and not any(word in b for word in ("incisor", "canine", "molar", "Costal cartilage"))
            ),
        }
        groups.append(bone_gid)
        tree[area]["children"] = groups
        tree[area]["controls"] = AREA_CONTROLS[area]
        tree[area]["region"] = AREA_REGION[area]

    for region, control_ids in REGION_CONTROLS.items():
        tree[region]["controls"] = control_ids

    bone_meta = {}
    for name, info in bones.items():
        if name.endswith(".l"):
            continue
        bone_meta[slug(display_name(name))] = {
            "name": display_name(name),
            "mesh": name,
            "segment": info["segment"],
        }

    landmark_out = {
        name: {"segment": info["segment"], "bone": info["bone"], "point": info["point"].round(2).tolist()}
        for name, info in landmarks.items()
    }

    body = {
        "units": "cm",
        "segments": SEGMENTS,
        "parents": PARENT,
        "pivots": {k: np.round(v, 3).tolist() for k, v in pivots.items()},
        "controls": [
            {
                "id": c["id"],
                "label": c["label"],
                "positive": c["positive"],
                "negative": c["negative"],
                "min": c["min"],
                "max": c["max"],
                "sign": c["sign"],
                "parts": [[seg, np.round(unit(axis), 5).tolist(), share] for seg, axis, share in c["parts"]],
            }
            for c in controls
        ],
        "tree": tree,
        "muscles": muscle_meta,
        "tissues": tissue_meta,
        "bones": bone_meta,
        "nerves": nerve_meta,
        "landmarks": landmark_out,
        "meshes": mesh_index,
        "files": ["skeleton.bin"] + [f"region-{r}.bin" for r in region_packers],
    }

    (OUT / "body.json").write_text(json.dumps(body, separators=(",", ":")))

    print("hip", hip_centre.round(2), "r", round(hip_radius, 2))
    print("shoulder", shoulder_centre.round(2), "r", round(shoulder_radius, 2))
    print("signs", {c["id"]: c["sign"] for c in controls})
    for path in sorted(OUT.glob("*")):
        print(f"{path.name:28} {path.stat().st_size / 1e6:6.2f} MB")
    print("vertices: bones", sum(len(b["positions"]) for b in bones.values()),
          "muscles", sum(len(m["positions"]) for m in muscles.values()))
    print("unmatched patches (first 30):", unmatched[:30])
    no_nerve = [m["name"] for m in muscle_meta.values() if not m["nerve"]]
    print("muscles without nerve:", len(no_nerve))
    no_patches = [m["name"] for m in muscle_meta.values() if not m["origins"] or not m["insertions"]]
    print("muscles missing origin or insertion patch:", len(no_patches), "of", len(muscle_meta))


main()
