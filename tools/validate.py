"""
Check that anatomy.json is complete and that every reference resolves.

Usage:
    python validate.py <app_dir>
"""

import json
import sys
from pathlib import Path


APP = Path(sys.argv[1])
data = json.loads((APP / "anatomy.json").read_text())
geometry = json.loads((APP / "geometry.json").read_text())

meshes = geometry["meshes"]
nerve_curves = geometry["nerves"]
landmarks = geometry["landmarks"]

errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


ids = set()
for section in ("muscles", "ligaments", "structures", "bones"):
    ids.update(data[section])

for node_id, node in data["tree"].items():
    for child in node.get("children", []):
        check(
            child in data["tree"] or child in ids,
            f"tree '{node_id}': unknown child '{child}'",
        )

for site_id, site in data["sites"].items():
    check(site["bone"] in data["bones"], f"site '{site_id}': unknown bone")
    for patch in site["patches"]:
        check(patch in meshes, f"site '{site_id}': missing patch mesh '{patch}'")
    if not site["patches"]:
        check(
            site.get("landmark") in landmarks,
            f"site '{site_id}': no patches and no valid landmark",
        )

required_muscle_fields = [
    "name", "mesh", "origin", "originText", "insertion",
    "insertionText", "nerve", "roots", "actions",
]
for muscle_id, muscle in data["muscles"].items():
    for field in required_muscle_fields:
        check(muscle.get(field), f"muscle '{muscle_id}': missing '{field}'")
    check(muscle["mesh"] in meshes, f"muscle '{muscle_id}': missing mesh")
    for site in muscle["origin"] + muscle["insertion"] + muscle.get("via", []):
        check(site in data["sites"], f"muscle '{muscle_id}': unknown site '{site}'")
    check(muscle["nerve"] in data["nerves"], f"muscle '{muscle_id}': unknown nerve")
    for action in muscle["actions"]:
        check(action in data["movements"], f"muscle '{muscle_id}': unknown action '{action}'")

for ligament_id, ligament in data["ligaments"].items():
    for mesh in [ligament.get("mesh")] + ligament.get("extraMeshes", []):
        if mesh:
            check(mesh in meshes, f"ligament '{ligament_id}': missing mesh '{mesh}'")
    for site in ligament.get("between", []):
        check(site in data["sites"], f"ligament '{ligament_id}': unknown site '{site}'")
    for name in ligament["attachments"]:
        check(name in landmarks, f"ligament '{ligament_id}': unknown landmark '{name}'")

for nerve_id, nerve in data["nerves"].items():
    for curve in nerve["curves"]:
        check(curve in nerve_curves, f"nerve '{nerve_id}': missing curve '{curve}'")

for movement_id, movement in data["movements"].items():
    for muscle in movement["prime"] + movement["assist"]:
        check(muscle in data["muscles"], f"movement '{movement_id}': unknown muscle '{muscle}'")

# Every muscle listed as acting in a movement should list that movement too.
for movement_id, movement in data["movements"].items():
    for muscle in movement["prime"] + movement["assist"]:
        if muscle in data["muscles"]:
            check(
                movement_id in data["muscles"][muscle]["actions"],
                f"'{muscle}' is in movement '{movement_id}' but not in its actions",
            )

if errors:
    print(f"{len(errors)} problem(s):")
    for error in errors:
        print("  -", error)
    sys.exit(1)

print(
    "OK:",
    len(data["muscles"]), "muscles,",
    len(data["ligaments"]), "ligaments,",
    len(data["sites"]), "sites,",
    len(data["nerves"]), "nerves,",
    len(data["movements"]), "movements",
)
