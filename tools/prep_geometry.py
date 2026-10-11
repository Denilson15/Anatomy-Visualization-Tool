"""
Turn the raw atlas export into the browser asset `geometry.json`.

Steps:
    1. Convert coordinates from Blender (Z-up, -Y anterior, cm)
       to three.js (Y-up, +Z anterior, cm).
    2. Find the joint pivots: hip centre (sphere fit of the femoral head)
       and the knee flexion axis (through both femoral epicondyles).
    3. Assign every mesh to rig segments:
           bones and attachment patches -> one rigid segment
           muscles, ligaments, nerves   -> per-vertex skin weights
    4. Pack vertex data as base64 typed arrays to keep the file small.

Usage:
    python prep_geometry.py <export_dir> <out_file>
"""

import base64
import json
import sys
from pathlib import Path

import numpy as np


EXPORT_DIR = Path(sys.argv[1])
OUT_FILE = Path(sys.argv[2])

SEGMENTS = ["pelvis", "femur", "patella", "tibia"]

SEGMENT_BONES = {
    "pelvis": ["Hip bone.r", "Sacrum"],
    "femur": ["Femur.r"],
    "patella": ["Patella.r"],
    "tibia": ["Tibia.r", "Fibula.r", "Talus.r", "Calcaneus.r"],
}

# Width (cm) of the soft blend between neighbouring segments.
SKIN_SIGMA = {
    "muscle": 2.5,
    "ligament": 0.8,
    "nerve": 2.0,
}

# Structures that must ride on a single segment regardless of distance.
RIGID_OVERRIDES = {
    "Medial meniscus.r": "tibia",
    "Lateral meniscus.r": "tibia",
}


def to_three(points):
    """Blender (x, y, z) -> three.js (x, z, -y)."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return np.stack([points[:, 0], points[:, 2], -points[:, 1]], axis=1)


def b64(array):
    return base64.b64encode(np.ascontiguousarray(array).tobytes()).decode("ascii")


def fit_sphere(points):
    """Least-squares sphere fit. Returns (centre, radius)."""
    a = np.hstack([2 * points, np.ones((len(points), 1))])
    b = (points ** 2).sum(axis=1)
    solution, *_ = np.linalg.lstsq(a, b, rcond=None)
    centre = solution[:3]
    radius = np.sqrt(solution[3] + centre @ centre)
    return centre, radius


def min_distances(points, cloud, chunk=4000):
    """Distance from each point to its nearest neighbour in `cloud`."""
    result = np.empty(len(points))
    for start in range(0, len(points), chunk):
        block = points[start:start + chunk]
        diff = block[:, None, :] - cloud[None, :, :]
        result[start:start + chunk] = np.sqrt((diff ** 2).sum(axis=2)).min(axis=1)
    return result


def skin_weights(points, segment_clouds, sigma):
    """Soft per-vertex weights over all segments, quantised to uint8."""
    distances = np.stack(
        [min_distances(points, segment_clouds[s]) for s in SEGMENTS],
        axis=1,
    )
    nearest = distances.min(axis=1, keepdims=True)
    raw = np.exp(-((distances - nearest) / sigma) ** 2)
    raw /= raw.sum(axis=1, keepdims=True)

    quantised = np.round(raw * 255).astype(np.int32)
    # Make each row sum to exactly 255 by fixing the largest entry.
    error = 255 - quantised.sum(axis=1)
    quantised[np.arange(len(quantised)), raw.argmax(axis=1)] += error
    return quantised.astype(np.uint8)


def main():
    meshes = json.loads((EXPORT_DIR / "meshes.json").read_text())
    nerves = json.loads((EXPORT_DIR / "nerves.json").read_text())
    landmarks = json.loads((EXPORT_DIR / "landmarks.json").read_text())

    positions = {
        name: to_three(mesh["positions"]).astype(np.float32)
        for name, mesh in meshes.items()
    }

    # Point clouds per segment (subsampled for speed).
    segment_clouds = {}
    bone_segment = {}
    for segment, bones in SEGMENT_BONES.items():
        clouds = []
        for bone in bones:
            if bone in positions:
                clouds.append(positions[bone][::2])
                bone_segment[bone] = segment
        segment_clouds[segment] = np.vstack(clouds).astype(np.float64)

    # --- Joint pivots -------------------------------------------------------
    def landmark(name):
        return to_three(landmarks[name]["point"])[0]

    head_point = landmark("Head of femur")
    femur = positions["Femur.r"].astype(np.float64)
    near_head = femur[np.linalg.norm(femur - head_point, axis=1) < 3.2]
    hip_centre, hip_radius = fit_sphere(near_head)

    medial_epicondyle = landmark("Medial epicondyle of femur")
    lateral_epicondyle = landmark("Lateral epicondyle of femur")
    knee_axis = lateral_epicondyle - medial_epicondyle
    knee_axis /= np.linalg.norm(knee_axis)
    knee_pivot = (medial_epicondyle + lateral_epicondyle) / 2

    # Ankle point used to check rotation directions in the browser.
    ankle = (landmark("Medial malleolus") + landmark("Lateral malleolus")) / 2

    print(f"hip centre {hip_centre.round(2)} radius {hip_radius:.2f} from {len(near_head)} pts")
    print(f"knee pivot {knee_pivot.round(2)} axis {knee_axis.round(3)}")

    # --- Meshes -------------------------------------------------------------
    out_meshes = {}
    for name, mesh in meshes.items():
        points = positions[name]
        kind = mesh["kind"]
        indices = np.asarray(mesh["indices"], dtype=np.uint32)
        index_type = "u16" if indices.max() < 65535 else "u32"
        if index_type == "u16":
            indices = indices.astype(np.uint16)

        entry = {
            "kind": kind,
            "count": int(len(points)),
            "positions": b64(points),
            "indexType": index_type,
            "indices": b64(indices),
        }

        if kind == "bone":
            entry["segment"] = bone_segment[name]
        elif kind == "patch" or name in RIGID_OVERRIDES:
            if name in RIGID_OVERRIDES:
                entry["segment"] = RIGID_OVERRIDES[name]
            else:
                centroid = points.mean(axis=0, keepdims=True).astype(np.float64)
                distances = [
                    min_distances(centroid, segment_clouds[s])[0] for s in SEGMENTS
                ]
                entry["segment"] = SEGMENTS[int(np.argmin(distances))]
        else:
            weights = skin_weights(points.astype(np.float64), segment_clouds, SKIN_SIGMA[kind])
            entry["weights"] = b64(weights)

        out_meshes[name] = entry

    # --- Nerves -------------------------------------------------------------
    out_nerves = {}
    for name, paths in nerves.items():
        out_paths = []
        for path in paths:
            points = to_three(path)
            weights = skin_weights(points, segment_clouds, SKIN_SIGMA["nerve"])
            out_paths.append({
                "points": points.round(2).tolist(),
                "weights": weights.tolist(),
            })
        out_nerves[name] = out_paths

    # --- Landmarks ----------------------------------------------------------
    out_landmarks = {}
    for name, info in landmarks.items():
        if info["bone"] not in bone_segment:
            continue
        out_landmarks[name] = {
            "bone": info["bone"],
            "segment": bone_segment[info["bone"]],
            "point": to_three(info["point"])[0].round(2).tolist(),
        }

    result = {
        "units": "cm",
        "segments": SEGMENTS,
        "rig": {
            "hip": {
                "pivot": hip_centre.round(3).tolist(),
            },
            "knee": {
                "pivot": knee_pivot.round(3).tolist(),
                "axis": knee_axis.round(5).tolist(),
            },
            "ankle": ankle.round(2).tolist(),
        },
        "meshes": out_meshes,
        "nerves": out_nerves,
        "landmarks": out_landmarks,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(result, separators=(",", ":")))
    print(f"wrote {OUT_FILE} ({OUT_FILE.stat().st_size / 1e6:.2f} MB)")


main()
