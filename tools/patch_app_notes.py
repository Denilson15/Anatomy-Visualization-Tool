"""
One-off refactor of app2/app.js: switch every muscle to the written notes.

Replaces whole top-level functions by name, deletes the ones that only served
atlas-only muscles, and fails loudly if any expected function is missing.
"""

import re
import sys
from pathlib import Path


PATH = Path(sys.argv[1])
source = PATH.read_text(encoding="utf-8")


def span(name):
    match = re.search(rf"^(async )?function {re.escape(name)}\(", source, re.M)
    if not match:
        raise SystemExit(f"function {name} not found")
    end = source.index("\n}\n", match.start()) + 3
    return match.start(), end


def replace(name, code):
    global source
    start, end = span(name)
    source = source[:start] + code.strip("\n") + "\n" + source[end:]


def delete(name):
    global source
    start, end = span(name)
    source = source[:start] + source[end:]


def replace_text(old, new):
    global source
    if source.count(old) != 1:
        raise SystemExit(f"expected one match for: {old[:60]}")
    source = source.replace(old, new)


# --------------------------------------------------------------------------
replace("setupEntities", r'''
function setupEntities() {
    const { body, content } = state;

    // Regions and areas come from the atlas; the groups inside them come from the notes.
    for (const [id, node] of Object.entries(body.tree)) {
        if (id.includes("--") && !id.endsWith("--bones")) {
            continue;
        }
        tree[id] = JSON.parse(JSON.stringify(node));
    }
    const groupOrder = Object.keys(content.groups);
    for (const area of Object.keys(tree).filter((id) => tree[id].region)) {
        const bonesGroup = tree[area].children.find((child) => child.endsWith("--bones"));
        tree[area].children = [
            ...groupOrder.filter((gid) => content.groups[gid].area === area),
            ...(area === "thigh-knee" ? ["knee-joint"] : []),
            ...(bonesGroup ? [bonesGroup] : []),
        ];
    }
    for (const [gid, group] of Object.entries(content.groups)) {
        tree[gid] = { name: group.name, parent: group.area, children: group.children, summary: group.summary };
    }
    tree["knee-joint"] = {
        name: "Knee ligaments",
        parent: "thigh-knee",
        summary: "The ligaments that hold the femur and tibia together, and the menisci that sit between them.",
        children: [...Object.keys(content.ligaments), ...Object.keys(content.structures)],
    };

    const groupOf = {};
    for (const [gid, group] of Object.entries(content.groups)) {
        for (const child of group.children) {
            groupOf[child] = gid;
        }
    }

    for (const [id, atlas] of Object.entries(body.muscles)) {
        const notes = content.muscles[id] ?? null;
        const group = content.groups[groupOf[id]] ?? null;
        entities.muscles[id] = {
            ...atlas,
            id,
            notes,
            name: notes?.name ?? atlas.name,
            area: group?.area ?? atlas.area,
            groupId: groupOf[id] ?? null,
            groupName: group?.name ?? atlas.groupName,
            origins: state.attachments[id]?.origin ?? [],
            insertions: state.attachments[id]?.insertion ?? [],
        };
        ownedMeshes[id] = [atlas.mesh];
    }

    for (const [id, tissue] of Object.entries(body.tissues)) {
        entities.tissues[id] = { ...tissue, id };
        ownedMeshes[id] = [tissue.mesh];
    }

    for (const [id, bone] of Object.entries(body.bones)) {
        entities.bones[id] = { ...bone, id };
        ownedMeshes[id] = [bone.mesh];
        const left = bone.mesh.replace(/\.r$/, ".l");
        if (left !== bone.mesh && body.meshes[left]) {
            ownedMeshes[id].push(left);
        }
    }

    for (const [id, ligament] of Object.entries(content.ligaments)) {
        entities.ligaments[id] = { ...ligament, id };
        ownedMeshes[id] = [ligament.mesh, ...(ligament.extraMeshes ?? [])].filter(Boolean);
    }

    for (const [id, structure] of Object.entries(content.structures)) {
        entities.structures[id] = { ...structure, id };
        ownedMeshes[id] = [structure.mesh];
    }

    for (const [id, site] of Object.entries(content.sites)) {
        entities.sites[id] = { ...site, id };
        for (const patch of site.patches) {
            patchSite[patch] = id;
        }
    }

    // Which muscles use each attachment patch, and in which role.
    for (const muscle of Object.values(entities.muscles)) {
        for (const patch of muscle.origins) {
            (patchUsers[patch] ||= []).push({ muscle: muscle.id, role: "origin" });
        }
        for (const patch of muscle.insertions) {
            (patchUsers[patch] ||= []).push({ muscle: muscle.id, role: "insertion" });
        }
    }

    segmentOrder = body.segments;
    segmentIndex = Object.fromEntries(segmentOrder.map((name, i) => [name, i]));
    const bones = [];
    for (let i = 0; i < segmentOrder.length; i++) {
        segmentMatrices.push(new THREE.Matrix4());
        segmentVersions.push(0);
        const bone = new THREE.Bone();
        bone.matrixAutoUpdate = false;
        bone.matrixWorldAutoUpdate = false;
        bones.push(bone);
    }
    sharedSkeleton = new THREE.Skeleton(bones, bones.map(() => new THREE.Matrix4()));

    for (const control of body.controls) {
        state.pose[control.id] = 0;
    }
}
''')

replace_text("/** patch mesh name -> authored site id */\nconst patchSite = {};",
             "/** patch mesh name -> authored site id */\nconst patchSite = {};\n\n/** patch mesh name -> [{ muscle, role }] after atlas corrections */\nconst patchUsers = {};")

replace_text("/** authored content id -> generated muscle id */\nconst authoredToMuscle = {};\n", "")

# Patches now come from the corrected attachments; the atlas's own role labels are not used.
replace("musclePatches", r'''
function musclePatches(muscle, role) {
    return role === "origin" ? muscle.origins : muscle.insertions;
}
''')

replace("patchesFor", r'''
function patchesFor(selection) {
    if (selection.type === "site") {
        return entities.sites[selection.id].patches;
    }
    if (selection.type === "patch") {
        const site = patchSite[selection.id];
        return site ? entities.sites[site].patches : [selection.id];
    }
    const bone = entities.bones[selection.id];
    return Object.keys(patchUsers).filter((patch) => state.body.meshes[patch]?.bone === bone.mesh);
}
''')

# --------------------------------------------------------------------------
replace("cordPath", r'''
/** Which end of the muscle's long axis is its origin, judged from the bones the notes name. */
function originEndIndex(muscle) {
    if (muscle.originEnd !== undefined) {
        return muscle.originEnd;
    }
    const part = parts[muscle.mesh];
    const notes = muscle.notes;
    if (!part || !notes) {
        return 0;
    }
    const ends = muscle.ends.map((v) => new THREE.Vector3(part.base[v * 3], part.base[v * 3 + 1], part.base[v * 3 + 2]));
    const distanceTo = (keywords, point) => {
        let best = Infinity;
        for (const bone of Object.values(parts)) {
            if (bone.kind !== "bone" || bone.name.endsWith(".l")) {
                continue;
            }
            const name = bone.name.toLowerCase();
            if (!keywords.some((keyword) => name.includes(keyword.toLowerCase()))) {
                continue;
            }
            const base = bone.base;
            for (let i = 0; i < base.length; i += 18) {
                const dx = base[i] - point.x;
                const dy = base[i + 1] - point.y;
                const dz = base[i + 2] - point.z;
                best = Math.min(best, dx * dx + dy * dy + dz * dz);
            }
        }
        return Math.sqrt(best);
    };
    const keep = distanceTo(notes.originBones, ends[0]) + distanceTo(notes.insertionBones, ends[1]);
    const swap = distanceTo(notes.originBones, ends[1]) + distanceTo(notes.insertionBones, ends[0]);
    muscle.originEnd = Number.isFinite(keep) && Number.isFinite(swap) && swap < keep ? 1 : 0;
    return muscle.originEnd;
}

/**
 * Line of pull for a muscle, origin first. Uses the corrected attachment
 * patches; where the atlas has none, falls back to the ends of the muscle's
 * long axis and marks the result approximate.
 */
function cordPath(muscleId, matrices = segmentMatrices) {
    const muscle = entities.muscles[muscleId];
    const notes = muscle.notes ?? {};

    let origin = averagePoints(muscle.origins.map((patch) => patchPoint(patch, matrices)));
    if (!origin && notes.originLandmark) {
        origin = landmarkPoint(notes.originLandmark, matrices);
    }
    let insertion = notes.pullEnd
        ? patchPoint(notes.pullEnd, matrices)
        : averagePoints(muscle.insertions.map((patch) => patchPoint(patch, matrices)));

    let approximate = false;
    if (!origin || !insertion) {
        const part = parts[muscle.mesh];
        if (!part) {
            return null;
        }
        approximate = true;
        const ends = muscle.ends.map((v) => skinVertex(part, v, matrices));
        if (!origin && !insertion) {
            const first = originEndIndex(muscle);
            origin = ends[first];
            insertion = ends[1 - first];
        } else if (!origin) {
            origin = ends[0].distanceTo(insertion) > ends[1].distanceTo(insertion) ? ends[0] : ends[1];
        } else {
            insertion = ends[0].distanceTo(origin) > ends[1].distanceTo(origin) ? ends[0] : ends[1];
        }
    }

    const via = (notes.pullVia ?? []).map((patch) => patchPoint(patch, matrices)).filter(Boolean);
    return { points: [origin, ...via, insertion], approximate };
}
''')

# --------------------------------------------------------------------------
delete("authoredNerveByName")

replace("muscleNerves", r'''
function nerveChain(nerveId) {
    const chain = [];
    let current = nerveId;
    while (current && state.content.nerves[current]) {
        chain.push(current);
        current = state.content.nerves[current].parent;
    }
    return chain;
}

/** Nerve ids that supply a muscle, including the trunks they branch from. */
function muscleNerves(muscle) {
    const notes = muscle.notes;
    if (!notes) {
        return [];
    }
    const ids = new Set();
    for (const nerve of [notes.nerve, ...(notes.alsoNerves ?? [])]) {
        nerveChain(nerve).forEach((id) => ids.add(id));
    }
    return [...ids];
}
''')

replace("nerveCurves", r'''
function nerveCurves(nerveId) {
    let current = nerveId;
    while (current) {
        const prefixes = state.content.nerves[current]?.atlas ?? [];
        const curves = Object.keys(state.body.nerves).filter((curve) => prefixes.some((prefix) => curve.startsWith(prefix)));
        if (curves.length) {
            return curves;
        }
        current = state.content.nerves[current]?.parent;
    }
    return [];
}
''')

# --------------------------------------------------------------------------
delete("authoredMovementFor")
delete("estimateMovers")
replace_text('''/* Twisting motions depend on muscles that wrap around bone, which a straight
 * origin-to-insertion line cannot represent, so no estimate is offered. */
const ROTATION_CONTROLS = new Set(["trunkRot", "neckRot", "shoulderRot", "forearmPro", "hipRot"]);
''', "")

replace("movementById", r'''
function movementById(id) {
    const notes = state.content.movements[id];
    if (id.includes(":")) {
        const control = id.split(":")[0];
        const generated = generatedMovements([control]).find((movement) => movement.id === id);
        return generated ? { ...notes, ...generated } : null;
    }
    return notes ? { id, ...notes } : null;
}
''')

replace("movementsInScope", r'''
function movementsInScope() {
    const list = generatedMovements(scopeControls()).map((movement) => movementById(movement.id));
    const areas = areasUnder(scopeNode());
    for (const [id, movement] of Object.entries(state.content.movements)) {
        if (id.includes(":")) {
            continue;
        }
        if (!areas || movement.areas.some((area) => areas.includes(area))) {
            list.push({ id, ...movement });
        }
    }
    return list;
}
''')

replace("movementMovers", r'''
function movementMovers(movementId) {
    const movement = movementById(movementId);
    return {
        prime: movement?.prime ?? [],
        assist: movement?.assist ?? [],
        note: movement?.note ?? null,
    };
}
''')

# --------------------------------------------------------------------------
replace("describeChild", r'''
function describeChild(id) {
    if (entities.muscles[id]) {
        const notes = entities.muscles[id].notes;
        return notes ? `${state.content.nerves[notes.nerve].name} · ${notes.roots}` : "";
    }
    if (entities.ligaments[id]) return entities.ligaments[id].function;
    if (entities.structures[id]) return "Fibrocartilage pad between femur and tibia";
    if (entities.bones[id]) return "";
    if (tree[id]) {
        if (tree[id].controls || REGION_IDS.includes(id)) {
            return `${musclesInScope(id).length} muscles`;
        }
        if (tree[id].summary) return tree[id].summary;
        const count = tree[id].children?.length ?? 0;
        return `${count} item${count === 1 ? "" : "s"}`;
    }
    return "";
}
''')

replace("card", r'''
function card(id) {
    const description = describeChild(id);
    return `
        <button class="card" type="button" data-open="${escapeHtml(id)}">
            <span class="nm">${escapeHtml(entityName(id))}</span>
            ${description ? `<span class="ds">${linkTerms(description)}</span>` : ""}
        </button>`;
}
''')
delete("hasAuthoredNotes")

replace_text('''            <p class="note">The right side is the one you study; the left side mirrors it for context. Written notes exist for the thigh and knee so far. Everywhere else you see the atlas's 3D data: attachments, layers and lines of pull, with nerve tags still to be checked.</p>`;''',
             '''            <p class="note">The right side is the one you study; the left side mirrors it for context. Every muscle has draft notes (origin, insertion, nerve, roots, actions) that still need checking against your textbook.</p>`;''')

replace("nerveLabel", r'''
function nerveLabel(muscle) {
    const notes = muscle.notes;
    if (!notes) {
        return "";
    }
    return notes.nerveNote ?? state.content.nerves[notes.nerve].name;
}
''')

delete("estimatedActions")
delete("renderGeneratedMuscle")

replace("renderAuthoredMuscle", r'''
function renderMusclePane(muscle) {
    const notes = muscle.notes;
    if (!notes) {
        return `<div class="eyebrow">${escapeHtml(muscle.groupName)}</div><h2>${escapeHtml(muscle.name)}</h2><p class="lede">No notes yet.</p>`;
    }
    const seen = new Set();
    const nerveIds = [notes.nerve, ...(notes.alsoNerves ?? [])];
    const nerveChips = nerveIds
        .map((id) => `<button class="chip" type="button" data-nerve="${escapeHtml(id)}">${escapeHtml(state.content.nerves[id].name)}</button>`)
        .join("");

    const actions = notes.actions
        .map((actionId) => {
            const movement = movementById(actionId);
            if (!movement) {
                return "";
            }
            const prime = movement.prime?.includes(muscle.id);
            const rig = movement.rig ?? null;
            const attrs = rig
                ? `data-play-control="${escapeHtml(JSON.stringify(rig))}"`
                : `data-show-movement="${escapeHtml(actionId)}"`;
            return `<button class="chip${prime ? " prime" : ""}" type="button" ${attrs}>${rig ? '<span class="play" aria-hidden="true">▶</span>' : ""}${escapeHtml(movement.name)}</button>`;
        })
        .join("");

    const unmarked = (role) => `<span class="lede">Not marked on this model; its line of pull is approximate.</span>`;

    return `
        <div class="eyebrow">${escapeHtml(muscle.groupName)} <span class="badge draft">Draft · unreviewed</span></div>
        <h2>${escapeHtml(muscle.name)}</h2>
        <dl class="facts">
            <div class="fact">
                <dt><i class="key ring" style="--k: var(--origin)"></i>Origin</dt>
                <dd><span>${linkTerms(notes.origin, seen)}</span>${muscle.origins.length || notes.originLandmark ? "" : unmarked("origin")}</dd>
            </div>
            <div class="fact">
                <dt><i class="key" style="--k: var(--insertion)"></i>Insertion</dt>
                <dd><span>${linkTerms(notes.insertion, seen)}</span>${muscle.insertions.length || notes.pullEnd ? "" : unmarked("insertion")}</dd>
            </div>
            <div class="fact">
                <dt><i class="key" style="--k: var(--nerve)"></i>Nerve</dt>
                <dd>
                    <div class="chips">${nerveChips}<span class="roots">${escapeHtml(notes.roots)}</span></div>
                    ${notes.nerveNote ? `<span class="lede">${escapeHtml(notes.nerveNote)}</span>` : ""}
                </dd>
            </div>
            <div class="fact">
                <dt>Actions</dt>
                <dd>
                    <span>${linkTerms(notes.actionText, seen)}</span>
                    ${actions ? `<div class="chips">${actions}</div>` : ""}
                </dd>
            </div>
        </dl>
        ${lengthMeter()}
        ${notes.note ? `<p class="note">${linkTerms(notes.note, seen)}</p>` : ""}
        <div class="actions-row">
            <button class="btn ghost" type="button" data-quiz-on="${escapeHtml(muscle.id)}">Quiz me on ${escapeHtml(muscle.name)}</button>
        </div>`;
}
''')

replace_text('''        const muscle = entities.muscles[selection.id];
        html = muscle.authored ? renderAuthoredMuscle(muscle) : renderGeneratedMuscle(muscle);''',
             '''        html = renderMusclePane(entities.muscles[selection.id]);''')

replace("attachmentsBlock", r'''
function attachmentsBlock(patches) {
    const starts = new Set();
    const ends = new Set();
    for (const patch of patches) {
        for (const { muscle, role } of patchUsers[patch] ?? []) {
            (role === "origin" ? starts : ends).add(muscle);
        }
    }
    const list = (ids) => [...ids].map((id) => chip(id)).join("");
    let html = `<dl class="facts">`;
    if (starts.size) {
        html += `<div class="fact"><dt><i class="key ring" style="--k: var(--origin)"></i>Starts here</dt><dd><div class="chips">${list(starts)}</div></dd></div>`;
    }
    if (ends.size) {
        html += `<div class="fact"><dt><i class="key" style="--k: var(--insertion)"></i>Ends here</dt><dd><div class="chips">${list(ends)}</div></dd></div>`;
    }
    if (!starts.size && !ends.size) {
        html += `<div class="fact"><dt>Note</dt><dd>Part of the patellar ligament attachment.</dd></div>`;
    }
    return html + `</dl>`;
}
''')

replace("patchTitle", r'''
function patchTitle(patch) {
    const site = patchSite[patch];
    if (site) {
        return entities.sites[site].name;
    }
    const user = patchUsers[patch]?.[0];
    if (user) {
        const notes = entities.muscles[user.muscle].notes;
        if (notes) {
            return user.role === "origin" ? notes.originShort : notes.insertionShort;
        }
    }
    const info = state.body.meshes[patch];
    const near = nearestLandmark(new THREE.Vector3(...info.centroid), info.bone);
    return near ?? "Attachment";
}
''')

# --------------------------------------------------------------------------
replace_text('''    if (selection?.type === "muscle") {
        const muscle = entities.muscles[selection.id];
        if (muscle.authored) {
            const origin = muscle.authored.origin[0];
            const last = muscle.authored.insertion[muscle.authored.insertion.length - 1];
            add(entities.sites[origin].name, "Origin", "var(--origin)", () => sitePoint(origin));
            add(entities.sites[last].name, "Insertion", "var(--insertion)", () => sitePoint(last));
            return;
        }
        if (muscle.origins.length) {
            add("Origin", patchDescription(muscle.origins), "var(--origin)",
                () => averagePoints(muscle.origins.map((p) => patchPoint(p))));
        }
        if (muscle.insertions.length) {
            add("Insertion", patchDescription(muscle.insertions), "var(--insertion)",
                () => averagePoints(muscle.insertions.map((p) => patchPoint(p))));
        }
        return;
    }''',
'''    if (selection?.type === "muscle") {
        const muscle = entities.muscles[selection.id];
        const notes = muscle.notes;
        if (!notes) {
            return;
        }
        const path = () => cordPath(muscle.id);
        const approximate = (role) => role === "origin"
            ? !muscle.origins.length && !notes.originLandmark
            : !muscle.insertions.length && !notes.pullEnd;
        add(notes.originShort, approximate("origin") ? "Origin · approximate position" : "Origin", "var(--origin)",
            () => path()?.points[0] ?? null);
        add(notes.insertionShort, approximate("insertion") ? "Insertion · approximate position" : "Insertion", "var(--insertion)",
            () => path()?.points.at(-1) ?? null);
        return;
    }''')

# --------------------------------------------------------------------------
replace("musclesForNerve", r'''
function musclesForNerve(nerveId) {
    return Object.values(entities.muscles)
        .filter((muscle) => muscleNerves(muscle).includes(nerveId))
        .map((muscle) => muscle.id);
}
''')

replace("nervesInScope", r'''
function nervesInScope() {
    const ids = new Set();
    for (const id of musclesInScope(scopeNode())) {
        muscleNerves(entities.muscles[id]).forEach((nerve) => ids.add(nerve));
    }
    return [...ids].sort((a, b) => state.content.nerves[a].name.localeCompare(state.content.nerves[b].name));
}
''')

replace("renderNerves", r'''
function renderNerves() {
    const ids = nervesInScope();
    const current = state.nerve.name;
    const nerves = state.content.nerves;
    let html = `
        <div class="eyebrow">Nerve mode</div>
        <h2>Which nerve runs what?</h2>
        <p class="lede">Pick a nerve to light up its path (where the atlas has one) and every muscle it supplies.</p>
        <div>`;
    for (const id of ids) {
        const parent = nerves[id].parent;
        html += `
            <button class="listbtn" type="button" data-select-nerve="${escapeHtml(id)}" aria-current="${current === id}">
                <span>${escapeHtml(nerves[id].name)}${parent && ids.includes(parent) ? ` <span class="lede">· branch of ${escapeHtml(nerves[parent].name)}</span>` : ""}</span>
                <span class="roots">${escapeHtml(nerves[id].roots)}</span>
            </button>`;
    }
    html += `</div>`;

    if (current && nerves[current]) {
        const nerve = nerves[current];
        const supplied = musclesForNerve(current);
        html += `
            <h3>${escapeHtml(nerve.name)} <span class="badge draft">Draft · unreviewed</span></h3>
            ${nerve.note ? `<p class="lede">${linkTerms(nerve.note)}</p>` : ""}
            <div class="chips">${supplied.map((id) => chip(id)).join("") || '<span class="lede">No muscles in the model.</span>'}</div>
            <label class="switch" for="injury-toggle">
                <input type="checkbox" id="injury-toggle" ${state.nerve.injury ? "checked" : ""}>
                Show what is lost if this nerve is injured
            </label>
            ${state.nerve.injury ? `<p class="note">${linkTerms(nerve.injury)}</p>` : ""}`;
    }
    paneNerves.innerHTML = html;
}
''')

# --------------------------------------------------------------------------
replace("renderMovements", r'''
function renderMovements() {
    const list = movementsInScope();
    const current = state.movement;
    const rigged = list.filter((movement) => movement.id.includes(":"));
    const other = list.filter((movement) => !movement.id.includes(":"));

    const row = (movement) => `
        <button class="listbtn" type="button" data-select-movement="${escapeHtml(movement.id)}" aria-current="${current === movement.id}">
            <span>${escapeHtml(movement.name)}</span>
            <span class="roots">${movement.rig ? "▶" : ""}</span>
        </button>`;

    let html = `
        <div class="eyebrow">Movement mode</div>
        <h2>What produces each motion?</h2>
        <p class="lede">Pick a motion. Prime movers turn red, helpers pink, and joints marked ▶ play the motion on the model.</p>`;
    if (rigged.length) {
        html += `<h3>Joints in this area</h3><div>${rigged.map(row).join("")}</div>`;
    }
    if (other.length) {
        html += `<h3>Other motions</h3><div>${other.map(row).join("")}</div>`;
    }

    if (current) {
        const movement = movementById(current);
        const movers = movementMovers(current);
        const chipList = (ids, prime) => ids
            .map((id) => `<button class="chip${prime ? " prime" : ""}" type="button" data-open="${escapeHtml(id)}">${escapeHtml(entityName(id))}</button>`)
            .join("");
        html += `
            <h3>${escapeHtml(movement.name)} <span class="badge draft">Draft · unreviewed</span></h3>
            <dl class="facts">
                <div class="fact"><dt>Prime</dt><dd><div class="chips">${movers.prime.length ? chipList(movers.prime, true) : '<span class="lede">See the note</span>'}</div></dd></div>
                <div class="fact"><dt>Assist</dt><dd><div class="chips">${movers.assist.length ? chipList(movers.assist, false) : '<span class="lede">None listed</span>'}</div></dd></div>
            </dl>
            ${movers.note ? `<p class="note">${linkTerms(movers.note)}</p>` : ""}
            ${movement.rig
                ? `<div class="actions-row"><button class="btn" type="button" data-select-movement="${escapeHtml(current)}">Play again</button></div>`
                : '<p class="lede">This motion is not animated on the model yet; the muscles that produce it are highlighted.</p>'}`;
    }
    paneMovements.innerHTML = html;
}
''')

# --------------------------------------------------------------------------
replace("quizItems", r'''
function quizItems(focus = null) {
    const items = [];
    const ids = focus ? [focus] : musclesInScope(scopeNode());
    for (const id of ids) {
        const muscle = entities.muscles[id];
        if (!muscle.notes) {
            continue;
        }
        if (muscle.insertions.length) {
            items.push({ key: `insertion:${id}`, kind: "tap", role: "insertion", muscle: id });
        }
        if (muscle.origins.length) {
            items.push({ key: `origin:${id}`, kind: "tap", role: "origin", muscle: id });
        }
        items.push({ key: `nerve:${id}`, kind: "nerve", muscle: id });
        if (muscle.notes.actions.length) {
            items.push({ key: `action:${id}`, kind: "action", muscle: id });
        }
    }
    if (!focus && scopeIncludesKnee()) {
        for (const id of Object.keys(entities.ligaments)) {
            items.push({ key: `ligament:${id}`, kind: "ligament", ligament: id });
            if (id !== "patellar-ligament") {
                items.push({ key: `taut:${id}`, kind: "taut", ligament: id });
            }
        }
    }
    return items;
}
''')

replace("buildQuestion", r'''
function buildQuestion(item) {
    const question = { key: item.key, item, answered: false };

    if (item.kind === "tap") {
        const muscle = entities.muscles[item.muscle];
        const answer = new Set(musclePatches(muscle, item.role));
        const nearby = Object.keys(patchUsers).filter((patch) =>
            parts[patch] && patchUsers[patch].some((user) => entities.muscles[user.muscle].area === muscle.area));
        question.tap = true;
        question.text = `Tap the ${item.role} of ${muscle.name}.`;
        question.answerPatches = answer;
        question.candidates = new Set([...nearby, ...answer]);
        question.revealed = new Set();
        question.explain = item.role === "insertion" ? muscle.notes.insertion : muscle.notes.origin;
        return question;
    }

    if (item.kind === "nerve") {
        const muscle = entities.muscles[item.muscle];
        const nerves = state.content.nerves;
        const correct = nerves[muscle.notes.nerve].name;
        const region = tree[muscle.area]?.parent;
        const pool = Object.values(entities.muscles)
            .filter((other) => other.notes && tree[other.area]?.parent === region)
            .map((other) => nerves[other.notes.nerve].name);
        question.text = `Which nerve supplies ${muscle.name}?`;
        question.options = choices(correct, pool.length >= 4 ? pool : Object.values(nerves).map((n) => n.name));
        question.correct = correct;
        question.explain = `${muscle.notes.nerveNote ?? correct}, roots ${muscle.notes.roots}.`;
        return question;
    }

    if (item.kind === "action") {
        const muscle = entities.muscles[item.muscle];
        const own = muscle.notes.actions.map((id) => movementById(id)?.name).filter(Boolean);
        const pool = movementsInScope().map((movement) => movement.name).filter((name) => !own.includes(name));
        const fallback = Object.keys(state.content.movements).map((id) => movementById(id)?.name).filter((name) => name && !own.includes(name));
        const wrong = shuffle([...new Set(pool.length >= 3 ? pool : fallback)]).slice(0, 3);
        question.text = `Which of these is an action of ${muscle.name}?`;
        question.options = shuffle([own[0], ...wrong]);
        question.correct = own[0];
        question.explain = muscle.notes.actionText;
        return question;
    }

    if (item.kind === "ligament") {
        const ligament = entities.ligaments[item.ligament];
        question.text = `Which ligament does this job? ${ligament.function}`;
        question.options = choices(ligament.name, Object.values(entities.ligaments).map((l) => l.name));
        question.correct = ligament.name;
        question.explain = `${ligament.name}. ${ligament.tautText}`;
        return question;
    }

    const ligament = entities.ligaments[item.ligament];
    const angle = Math.random() < 0.5 ? 0 : 90;
    question.text = `With the knee ${angle === 0 ? "fully straight" : "bent to 90°"}, is the ${ligament.short} taut or slack?`;
    question.options = ["Taut", "Slack"];
    question.correct = interpolate(ligament.taut, angle) > 0.7 ? "Taut" : "Slack";
    question.explain = ligament.tautText;
    return question;
}
''')

replace_text('''        html += `<p class="lede">Nothing to quiz here yet: no muscles in this area have both attachments marked or written notes. Try the thigh and knee.</p>`;''',
             '''        html += `<p class="lede">Nothing to quiz in this selection. Choose an area with muscles.</p>`;''')

# --------------------------------------------------------------------------
replace("groupView", r'''
function groupView(groupName, area) {
    if (/^Sole/i.test(groupName)) {
        return [-0.2, -0.9, 0.35];
    }
    if (/Dorsum|Pelvic floor/i.test(groupName)) {
        return [-0.2, 0.9, 0.5];
    }
    if (/Posterior|Hamstrings|calf|Gluteal|rotators|back|Erector|Transversospinales|Splenius|Suboccipital|Segmental|Rotator|Quadratus|Teres/i.test(groupName)) {
        return VIEWS.back;
    }
    if (/Medial/i.test(groupName)) {
        return VIEWS.medial;
    }
    if (/Lateral|Scalenes|Deltoid/i.test(groupName)) {
        return VIEWS.right;
    }
    return AREA_VIEW[area] ?? VIEWS.front;
}
''')

# Boot: also load the corrected attachments.
replace_text('''        const [body, content] = await Promise.all([
            fetch("body.json").then((response) => response.json()),
            fetch("anatomy.json").then((response) => response.json()),
        ]);
        state.body = body;
        state.content = content;''',
'''        const [body, content, attachments] = await Promise.all([
            fetch("body.json").then((response) => response.json()),
            fetch("anatomy.json").then((response) => response.json()),
            fetch("attachments.json").then((response) => response.json()),
        ]);
        state.body = body;
        state.content = content;
        state.attachments = attachments;''')

# Non-animated movements can be opened from a muscle's action chips.
replace_text('''    if (data.playControl) {
        playMotion(JSON.parse(data.playControl));
        return;
    }''',
'''    if (data.playControl) {
        playMotion(JSON.parse(data.playControl));
        return;
    }
    if (data.showMovement) {
        showTab("movements", { skipRender: true });
        selectMovement(data.showMovement);
        return;
    }''')

replace_text('''    $("#credit").textContent = `${state.content.meta.modelCredit} Notes are drafts awaiting review.`;''',
             '''    $("#credit").textContent = `${state.content.meta.modelCredit} All notes are drafts awaiting review.`;''')

# Leftovers that referenced authored-only data.
replace_text('''    const supplied = musclesForNerve(name);''', '''    const supplied = musclesForNerve(name);''') if 'const supplied = musclesForNerve(name);' in source else None

PATH.write_text(source, encoding="utf-8")
print("patched")
