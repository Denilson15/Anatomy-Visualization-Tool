"""
Merge the written notes into the app's content files and check them.

Reads:
    notes/base.json, notes/<region>.json, notes/ligaments-<region>.json,
    notes/movements.json, notes/nerves.json
    app/body.json (generated from the atlas)

Writes:
    app/anatomy.json      merged notes for the app
    app/attachments.json  corrected origin/insertion patches per muscle
    notes/attachment-report.md  what was swapped or dropped, for reviewers

The attachment correction compares each atlas patch with the bones the notes
name for that muscle's origin and insertion:
    patch on an origin bone only     -> origin
    patch on an insertion bone only  -> insertion
    patch on both                    -> keeps the atlas's label
    patch on neither                 -> dropped (atlas error)

Usage:
    python build_content.py <project_dir>
"""

import json
import sys
from pathlib import Path


ROOT = Path(sys.argv[1])
NOTES = ROOT / "notes"
APP = ROOT / "app"

REGION_FILES = ["lower-limb.json", "upper-limb.json", "trunk.json", "head-neck.json"]

body = json.loads((APP / "body.json").read_text())
base = json.loads((NOTES / "base.json").read_text())
movements = json.loads((NOTES / "movements.json").read_text())["movements"]
nerves = json.loads((NOTES / "nerves.json").read_text())["nerves"]

groups = {}
muscles = {}
for name in REGION_FILES:
    data = json.loads((NOTES / name).read_text())
    groups.update(data["groups"])
    muscles.update(data["muscles"])

joints = {}
ligaments = {}
for name in REGION_FILES:
    data = json.loads((NOTES / f"ligaments-{name}").read_text())
    for joint_id in data["joints"]:
        assert joint_id not in joints, f"joint '{joint_id}' defined twice"
    for ligament_id in data["ligaments"]:
        assert ligament_id not in ligaments, f"ligament '{ligament_id}' defined twice"
    joints.update(data["joints"])
    ligaments.update(data["ligaments"])

errors = []
warnings = []

# --- Coverage --------------------------------------------------------------
atlas_ids = set(body["muscles"])
noted_ids = set(muscles)
for missing in sorted(atlas_ids - noted_ids):
    errors.append(f"no notes for atlas muscle '{missing}'")
for extra in sorted(noted_ids - atlas_ids):
    errors.append(f"notes for unknown muscle '{extra}'")

membership = {}
for group_id, group in groups.items():
    for child in group["children"]:
        if child in membership:
            errors.append(f"'{child}' is in both '{membership[child]}' and '{group_id}'")
        membership[child] = group_id
        if child not in muscles:
            errors.append(f"group '{group_id}' lists unknown muscle '{child}'")
for muscle_id in noted_ids - set(membership):
    errors.append(f"'{muscle_id}' is not in any group")

# --- Fields, nerves, actions -----------------------------------------------
control_ids = {control["id"] for control in body["controls"]}
REQUIRED = ["origin", "originShort", "originBones", "insertion", "insertionShort",
            "insertionBones", "nerve", "roots", "actions", "actionText"]

for muscle_id, muscle in muscles.items():
    for field in REQUIRED:
        if field not in muscle:
            errors.append(f"'{muscle_id}' is missing '{field}'")
    for nerve in [muscle.get("nerve")] + muscle.get("alsoNerves", []):
        if nerve not in nerves:
            errors.append(f"'{muscle_id}' names unknown nerve '{nerve}'")
    for action in muscle.get("actions", []):
        if ":" in action:
            control, sign = action.split(":")
            if control not in control_ids or sign not in "+-":
                errors.append(f"'{muscle_id}' has unknown rigged action '{action}'")
        if action not in movements:
            errors.append(f"'{muscle_id}' action '{action}' has no movement entry")

for nerve_id, nerve in nerves.items():
    parent = nerve.get("parent")
    if parent and parent not in nerves:
        errors.append(f"nerve '{nerve_id}' has unknown parent '{parent}'")

for movement_id, movement in movements.items():
    if ":" in movement_id:
        control = movement_id.split(":")[0]
        if control not in control_ids:
            errors.append(f"movement '{movement_id}' names unknown control")
    elif "name" not in movement or "areas" not in movement:
        errors.append(f"movement '{movement_id}' needs a name and areas")
    for muscle_id in movement["prime"] + movement["assist"]:
        if muscle_id not in muscles:
            errors.append(f"movement '{movement_id}' lists unknown muscle '{muscle_id}'")
        elif movement_id not in muscles[muscle_id]["actions"]:
            warnings.append(f"'{muscle_id}' acts in '{movement_id}' but does not list it")

for muscle_id, muscle in muscles.items():
    for action in muscle.get("actions", []):
        movement = movements.get(action)
        if movement and muscle_id not in movement["prime"] + movement["assist"]:
            warnings.append(f"'{muscle_id}' lists '{action}' but the movement does not include it")

# --- Joints and ligaments --------------------------------------------------
LIGAMENT_KINDS = {"ligament", "capsule", "disc", "labrum", "meniscus", "membrane", "fat-pad"}
LIGAMENT_REQUIRED = ["name", "kind", "joint", "meshes", "attachmentText", "function"]
area_ids = {node for node, info in body["tree"].items() if info.get("region")}

for joint_id, joint in joints.items():
    for field in ("name", "area", "type", "summary"):
        if field not in joint:
            errors.append(f"joint '{joint_id}' is missing '{field}'")
    if joint.get("area") not in area_ids:
        errors.append(f"joint '{joint_id}' names unknown area '{joint.get('area')}'")

mesh_owner = {}
for ligament_id, ligament in ligaments.items():
    for field in LIGAMENT_REQUIRED:
        if field not in ligament:
            errors.append(f"ligament '{ligament_id}' is missing '{field}'")
    if ligament.get("kind") not in LIGAMENT_KINDS:
        errors.append(f"ligament '{ligament_id}' has unknown kind '{ligament.get('kind')}'")
    if ligament.get("joint") not in joints:
        errors.append(f"ligament '{ligament_id}' names unknown joint '{ligament.get('joint')}'")
    for mesh_name in ligament.get("meshes", []):
        if body["meshes"].get(mesh_name, {}).get("kind") != "ligament":
            errors.append(f"ligament '{ligament_id}' names unknown mesh '{mesh_name}'")
        if mesh_name in mesh_owner:
            errors.append(f"mesh '{mesh_name}' is in both '{mesh_owner[mesh_name]}' and '{ligament_id}'")
        mesh_owner[mesh_name] = ligament_id
    for site in ligament.get("between", []):
        if site not in base["sites"]:
            errors.append(f"ligament '{ligament_id}' names unknown site '{site}'")
    for rule in ligament.get("taut", []):
        if rule["control"] not in control_ids:
            errors.append(f"ligament '{ligament_id}' taut rule names unknown control '{rule['control']}'")
        angles = [point[0] for point in rule["points"]]
        if angles != sorted(angles) or not all(0 <= point[1] <= 1 for point in rule["points"]):
            errors.append(f"ligament '{ligament_id}' taut points must be sorted with values 0-1")
        if "tautText" not in ligament:
            errors.append(f"ligament '{ligament_id}' has a taut rule but no tautText")

for mesh_name, mesh in body["meshes"].items():
    if mesh["kind"] == "ligament" and mesh_name not in mesh_owner:
        errors.append(f"atlas structure '{mesh_name}' has no ligament notes")

# --- Attachment correction -------------------------------------------------
meshes = body["meshes"]


def on_bones(patch, keywords):
    bone = meshes[patch]["bone"].lower()
    return any(keyword.lower() in bone for keyword in keywords)


attachments = {}
report = ["# Atlas attachment corrections", "",
          "Each atlas origin/insertion patch was checked against the bones named in the notes.", ""]
counts = {"kept": 0, "swapped": 0, "dropped": 0}

for muscle_id, muscle in sorted(muscles.items()):
    atlas = body["muscles"][muscle_id]
    labelled = [(patch, "origin") for patch in atlas["origins"]] + \
               [(patch, "insertion") for patch in atlas["insertions"]]
    result = {"origin": [], "insertion": []}
    lines = []

    for patch, atlas_role in labelled:
        is_origin = on_bones(patch, muscle["originBones"])
        is_insertion = on_bones(patch, muscle["insertionBones"])
        if is_origin and is_insertion:
            role = atlas_role
        elif is_origin:
            role = "origin"
        elif is_insertion:
            role = "insertion"
        else:
            role = None

        bone = meshes[patch]["bone"]
        if role is None:
            counts["dropped"] += 1
            lines.append(f"- dropped `{patch}` (atlas: {atlas_role}, on {bone})")
        elif role != atlas_role:
            counts["swapped"] += 1
            lines.append(f"- relabelled `{patch}` from {atlas_role} to {role} (on {bone})")
            result[role].append(patch)
        else:
            counts["kept"] += 1
            result[role].append(patch)

    attachments[muscle_id] = result
    if lines:
        report.append(f"## {muscle.get('name', muscle_id)}")
        report.extend(lines)
        report.append("")

report.insert(4, f"Kept {counts['kept']}, relabelled {counts['swapped']}, dropped {counts['dropped']}.")
report.insert(5, "")

# --- Write -----------------------------------------------------------------
content = {key: value for key, value in base.items() if key not in ("ligaments", "structures")}
content["joints"] = joints
content["ligaments"] = ligaments
content["groups"] = groups
content["muscles"] = muscles
content["movements"] = movements
content["nerves"] = nerves

(APP / "anatomy.json").write_text(json.dumps(content, indent=4, ensure_ascii=False) + "\n")
(APP / "attachments.json").write_text(json.dumps(attachments, indent=4) + "\n")
(NOTES / "attachment-report.md").write_text("\n".join(report) + "\n")

print(f"muscles {len(muscles)}, groups {len(groups)}, movements {len(movements)}, nerves {len(nerves)}")
modelled = sum(1 for ligament in ligaments.values() if ligament["meshes"] or ligament.get("between"))
print(f"joints {len(joints)}, ligaments {len(ligaments)} ({modelled} in 3D, {len(mesh_owner)} meshes)")
print(f"attachments: kept {counts['kept']}, relabelled {counts['swapped']}, dropped {counts['dropped']}")
both = sum(1 for a in attachments.values() if a["origin"] and a["insertion"])
print(f"muscles with both attachments marked: {both} of {len(attachments)}")
print(f"{len(warnings)} consistency warnings")
for warning in warnings[:60]:
    print("  ~", warning)
if errors:
    print(f"{len(errors)} ERRORS")
    for error in errors:
        print("  !", error)
    sys.exit(1)
