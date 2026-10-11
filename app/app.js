import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/* ==========================================================================
 * Constants
 * ======================================================================== */

const REDUCED_MOTION = matchMedia("(prefers-reduced-motion: reduce)").matches;

const COLORS = {
    bone: 0xe6dfd2,
    boneContext: 0x8f8a81,
    muscle: 0xb34a3f,
    muscleMirror: 0xa04238,
    tissue: 0xd9cdbd,
    ligament: 0xcfc8bb,
    meniscus: 0xa8c4cf,
    origin: 0x3a86e0,
    insertion: 0xf08a2a,
    neutralSite: 0x8e9aa2,
    nerve: 0xf2c230,
    prime: 0xd8483a,
    assist: 0xe99a8c,
    lost: 0x5d6368,
    slack: 0xbfb8aa,
    amber: 0xf0a43a,
    taut: 0xe23c2d,
    correct: 0x3cbf74,
};

/* Right-limb segments mapped to the root they hang from, for the mirrored
 * (left) copies of muscles: the left limbs are not rigged. */
const MIRROR_SEGMENT = {
    humerus: "thorax",
    ulna: "thorax",
    radius: "thorax",
    hand: "thorax",
    femur: "pelvis",
    patella: "pelvis",
    tibia: "pelvis",
    foot: "pelvis",
};

/* Camera directions. The body's right side is at negative x; +z is anterior. */
const VIEWS = {
    front: [-0.3, 0.1, 1],
    right: [-1, 0.12, 0.35],
    medial: [1, 0.12, 0.3],
    back: [-0.3, 0.12, -1],
    above: [-0.4, 0.9, 0.6],
};

const AREA_VIEW = {
    head: VIEWS.front,
    neck: [-0.7, 0.1, 1],
    back: VIEWS.back,
    "thorax-area": VIEWS.front,
    abdomen: VIEWS.front,
    shoulder: [-0.8, 0.2, 1],
    arm: [-0.7, 0.1, 1],
    forearm: VIEWS.front,
    "hand-area": [-0.3, 0.2, 1],
    "hip-gluteal": [-0.7, 0.1, -1],
    "thigh-knee": VIEWS.front,
    "leg-ankle": [-0.6, 0.1, 1],
    "foot-area": [-0.7, 0.6, 1],
};

const LIGAMENT_VIEW = {
    acl: VIEWS.front,
    pcl: VIEWS.back,
    mcl: VIEWS.medial,
    lcl: VIEWS.right,
    "patellar-ligament": VIEWS.right,
    "medial-meniscus": [0.2, 1, 0.5],
    "lateral-meniscus": [-0.2, 1, 0.5],
};

const LANDMARK_SKIP = /(Bones|Muscles|Joints|system|nodes|plexus|Bursae|Fasciae|compartment|Taeniae|bladder|membrane|joint|Interosseous|Pelvic|Bony|surface$|^Body of)/i;

/* ==========================================================================
 * State
 * ======================================================================== */

const state = {
    body: null,
    content: null,
    pose: {},
    show: { muscles: true, deep: false, cords: false, sites: false },
    tab: "explore",
    node: "body",
    selection: null,
    nerve: { name: null, injury: false },
    movement: null,
    quiz: null,
    dirty: true,
    animation: null,
    loadedFiles: new Set(),
};

/* ==========================================================================
 * Helpers
 * ======================================================================== */

const $ = (selector) => document.querySelector(selector);

const escapeHtml = (value) =>
    String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");

const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

function interpolate(points, x) {
    if (x <= points[0][0]) {
        return points[0][1];
    }
    for (let i = 1; i < points.length; i++) {
        const [x1, y1] = points[i];
        const [x0, y0] = points[i - 1];
        if (x <= x1) {
            return y0 + ((x - x0) / (x1 - x0)) * (y1 - y0);
        }
    }
    return points[points.length - 1][1];
}

function storageGet(key, fallback) {
    try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : fallback;
    } catch (error) {
        return fallback;
    }
}

function storageSet(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
        /* storage is optional */
    }
}

function shuffle(list) {
    const copy = list.slice();
    for (let i = copy.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
}

function lowerFirst(text) {
    return text.charAt(0).toLowerCase() + text.slice(1);
}

/* ==========================================================================
 * Scene
 * ======================================================================== */

const canvas = $("#view");
const stage = $("#stage");

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setClearColor(0x14181b, 1);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, 1, 1, 4000);
const orbit = new OrbitControls(camera, canvas);
orbit.enableDamping = !REDUCED_MOTION;
orbit.dampingFactor = 0.08;
orbit.minDistance = 12;
orbit.maxDistance = 900;

scene.add(new THREE.HemisphereLight(0xf4f1ea, 0x30363b, 1.15));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.6);
keyLight.position.set(80, 240, 260);
scene.add(keyLight);
const rimLight = new THREE.DirectionalLight(0xbcd4ff, 0.7);
rimLight.position.set(-160, 120, -240);
scene.add(rimLight);
const fillLight = new THREE.DirectionalLight(0xffffff, 0.35);
fillLight.position.set(-80, -60, 200);
scene.add(fillLight);

let cameraGoal = null;

function resize() {
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    if (!width || !height) {
        return;
    }
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
}

new ResizeObserver(resize).observe(stage);

const cordGroup = new THREE.Group();
const nerveGroup = new THREE.Group();
scene.add(cordGroup);
scene.add(nerveGroup);

/* ==========================================================================
 * Model registry
 * ======================================================================== */

/** mesh name (or "<name>~mirror") -> part */
const parts = {};

/** entity id -> mesh names */
const ownedMeshes = {};


const entities = {
    muscles: {},
    tissues: {},
    bones: {},
    ligaments: {},
    structures: {},
    sites: {},
};

/** patch mesh name -> knee ligament site id */
const patchSite = {};

/** patch mesh name -> [{ muscle, role }] after atlas corrections */
const patchUsers = {};

const tree = {};

let segmentIndex = {};
let segmentOrder = [];
const segmentMatrices = [];
const segmentVersions = [];

/* GPU skinning: one shared skeleton whose bones carry the segment transforms. */
let sharedSkeleton = null;
const identity = new THREE.Matrix4();

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

/* ==========================================================================
 * Loading binary meshes
 * ======================================================================== */

function ownerOf(meshName) {
    const info = state.body.meshes[meshName];
    if (info.kind === "patch") {
        return { type: "patch", id: meshName };
    }
    for (const [type, group] of Object.entries(entities)) {
        for (const [id, entity] of Object.entries(group)) {
            if (ownedMeshes[id]?.includes(meshName)) {
                return { type: type.replace(/s$/, ""), id };
            }
        }
    }
    return null;
}

function buildPart(name, info, buffer, mirror = false) {
    const count = info.count;
    let base = new Float32Array(buffer, info.pos, count * 3);
    let indices = info.idxType === "u16"
        ? new Uint16Array(buffer, info.idx, info.idxCount)
        : new Uint32Array(buffer, info.idx, info.idxCount);

    let segs = info.segs !== undefined ? new Uint8Array(buffer, info.segs, count * 2) : null;
    const weights = info.w !== undefined ? new Uint8Array(buffer, info.w, count) : null;
    let segment = info.segment ?? null;

    if (mirror) {
        base = Float32Array.from(base);
        for (let i = 0; i < base.length; i += 3) {
            base[i] = -base[i];
        }
        const flipped = indices.slice();
        for (let i = 0; i < flipped.length; i += 3) {
            flipped[i + 1] = indices[i + 2];
            flipped[i + 2] = indices[i + 1];
        }
        indices = flipped;
        if (segs) {
            segs = Uint8Array.from(segs, (s) => {
                const mapped = MIRROR_SEGMENT[segmentOrder[s]];
                return mapped ? segmentIndex[mapped] : s;
            });
        }
        if (segment && MIRROR_SEGMENT[segment]) {
            segment = MIRROR_SEGMENT[segment];
        }
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(Float32Array.from(base), 3));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();

    const material = new THREE.MeshStandardMaterial({ color: COLORS.bone, roughness: 0.72, metalness: 0 });
    let mesh;
    if (segs) {
        const skinIndex = new Uint16Array(count * 4);
        const skinWeight = new Float32Array(count * 4);
        for (let v = 0; v < count; v++) {
            skinIndex[v * 4] = segs[v * 2];
            skinIndex[v * 4 + 1] = segs[v * 2 + 1];
            skinWeight[v * 4] = weights[v] / 255;
            skinWeight[v * 4 + 1] = 1 - weights[v] / 255;
        }
        geometry.setAttribute("skinIndex", new THREE.BufferAttribute(skinIndex, 4));
        geometry.setAttribute("skinWeight", new THREE.BufferAttribute(skinWeight, 4));
        mesh = new THREE.SkinnedMesh(geometry, material);
        mesh.bind(sharedSkeleton, identity);
        mesh.frustumCulled = false;
        // A fixed, generous sphere: three.js would otherwise re-skin every
        // vertex on the CPU to refresh it. It only needs to cover any pose.
        mesh.boundingSphere = geometry.boundingSphere.clone();
        mesh.boundingSphere.radius += 100;
    } else {
        mesh = new THREE.Mesh(geometry, material);
    }
    const key = mirror ? `${name}~mirror` : name;
    mesh.userData.part = key;
    mesh.matrixAutoUpdate = false;
    scene.add(mesh);

    if (info.kind === "patch") {
        material.polygonOffset = true;
        material.polygonOffsetFactor = -2;
        material.polygonOffsetUnits = -2;
        mesh.renderOrder = 2;
    }

    const usedSegments = segs ? [...new Set(segs)] : [];

    parts[key] = {
        name,
        key,
        mesh,
        kind: info.kind,
        mirror,
        base,
        segs,
        weights,
        segment,
        usedSegments,
        seen: new Array(segmentOrder.length).fill(-1),
        owner: mirror ? ownerOf(name) : ownerOf(name),
        info,
    };
}

/* Mesh data ships as base64 text (`<file>.txt`): the host serves text, not raw binary. */
async function fetchBinary(file) {
    const response = await fetch(`${file}.txt`);
    if (!response.ok) {
        throw new Error(`${file}: ${response.status}`);
    }
    const text = await response.text();
    const binary = atob(text.trim());
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
}

async function loadFile(file) {
    const buffer = await fetchBinary(file);

    for (const [name, info] of Object.entries(state.body.meshes)) {
        if (info.file !== file) {
            continue;
        }
        buildPart(name, info, buffer);
        const mirrorable = (info.kind === "muscle" || info.kind === "tissue") && name.endsWith(".r");
        if (mirrorable) {
            buildPart(name, info, buffer, true);
        }
    }
    state.loadedFiles.add(file);
    state.dirty = true;
    computeRestLengths();
}

/* ==========================================================================
 * Rig
 * ======================================================================== */

const tmpA = new THREE.Matrix4();
const tmpB = new THREE.Matrix4();
const tmpC = new THREE.Matrix4();
const axisVector = new THREE.Vector3();

function computeMatrices(pose, out) {
    const { body } = state;
    for (let i = 0; i < segmentOrder.length; i++) {
        const segment = segmentOrder[i];
        const pivot = body.pivots[segment] ?? [0, 0, 0];
        const local = tmpA.identity();

        for (const control of body.controls) {
            const angle = pose[control.id] ?? 0;
            if (!angle) {
                continue;
            }
            for (const [target, axis, share] of control.parts) {
                if (target !== segment) {
                    continue;
                }
                axisVector.set(axis[0], axis[1], axis[2]);
                local.multiply(tmpB.makeRotationAxis(axisVector, THREE.MathUtils.degToRad(angle * control.sign * share)));
            }
        }

        const matrix = tmpC
            .makeTranslation(pivot[0], pivot[1], pivot[2])
            .multiply(local)
            .multiply(tmpB.makeTranslation(-pivot[0], -pivot[1], -pivot[2]));

        const parent = body.parents[segment];
        if (parent) {
            out[i].copy(out[segmentIndex[parent]]).multiply(matrix);
        } else {
            out[i].copy(matrix);
        }
    }
    return out;
}

function updateSegments() {
    const next = segmentOrder.map(() => new THREE.Matrix4());
    computeMatrices(state.pose, next);
    for (let i = 0; i < next.length; i++) {
        if (!next[i].equals(segmentMatrices[i])) {
            segmentMatrices[i].copy(next[i]);
            segmentVersions[i]++;
        }
    }
}

function skinVertex(part, vertex, matrices = segmentMatrices) {
    const { base, segs, weights } = part;
    const point = new THREE.Vector3(base[vertex * 3], base[vertex * 3 + 1], base[vertex * 3 + 2]);
    if (!segs) {
        return point.applyMatrix4(matrices[segmentIndex[part.segment]]);
    }
    const a = point.clone().applyMatrix4(matrices[segs[vertex * 2]]);
    const b = point.clone().applyMatrix4(matrices[segs[vertex * 2 + 1]]);
    const wa = weights[vertex] / 255;
    return a.multiplyScalar(wa).addScaledVector(b, 1 - wa);
}

function applyPose() {
    updateSegments();

    sharedSkeleton.bones.forEach((bone, i) => {
        bone.matrix.copy(segmentMatrices[i]);
        bone.matrixWorld.copy(segmentMatrices[i]);
    });

    for (const part of Object.values(parts)) {
        if (part.segment && !part.segs) {
            part.mesh.matrix.copy(segmentMatrices[segmentIndex[part.segment]]);
            part.mesh.matrixWorldNeedsUpdate = true;
        }
    }

    rebuildCords();
    rebuildNerves();
    updateLiveReadouts();
}

/* ==========================================================================
 * Attachment points and lines of pull
 * ======================================================================== */

function patchPoint(patchName, matrices = segmentMatrices) {
    const info = state.body.meshes[patchName];
    if (!info) {
        return null;
    }
    return new THREE.Vector3(...info.centroid).applyMatrix4(matrices[segmentIndex[info.segment]]);
}

function averagePoints(points) {
    const valid = points.filter(Boolean);
    if (!valid.length) {
        return null;
    }
    const sum = new THREE.Vector3();
    valid.forEach((p) => sum.add(p));
    return sum.divideScalar(valid.length);
}

function sitePoint(siteId, matrices = segmentMatrices) {
    const site = entities.sites[siteId];
    const fromPatches = averagePoints(site.patches.map((patch) => patchPoint(patch, matrices)));
    if (fromPatches) {
        return fromPatches;
    }
    if (site.landmark) {
        return landmarkPoint(site.landmark, matrices);
    }
    return null;
}

function landmarkPoint(name, matrices = segmentMatrices) {
    const landmark = state.body.landmarks[name];
    if (!landmark) {
        return null;
    }
    return new THREE.Vector3(...landmark.point).applyMatrix4(matrices[segmentIndex[landmark.segment]]);
}

/**
 * Line of pull for a muscle, from origin to insertion.
 * Returns { points, approximate } or null when it cannot be drawn yet.
 */
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

function pathLength(points) {
    let length = 0;
    for (let i = 1; i < points.length; i++) {
        length += points[i].distanceTo(points[i - 1]);
    }
    return length;
}

const restLength = {};

function computeRestLengths() {
    const rest = segmentOrder.map(() => new THREE.Matrix4());
    computeMatrices({}, rest);
    for (const id of Object.keys(entities.muscles)) {
        if (restLength[id]) {
            continue;
        }
        const path = cordPath(id, rest);
        if (path) {
            restLength[id] = pathLength(path.points);
        }
    }
}

function lengthRatio(muscleId, matrices = segmentMatrices) {
    const path = cordPath(muscleId, matrices);
    if (!path || !restLength[muscleId]) {
        return null;
    }
    return pathLength(path.points) / restLength[muscleId];
}

function ligamentTension(id) {
    return clamp(interpolate(entities.ligaments[id].taut, state.pose.knee ?? 0), 0, 1);
}

function tensionColor(tension) {
    const slack = new THREE.Color(COLORS.slack);
    const amber = new THREE.Color(COLORS.amber);
    const taut = new THREE.Color(COLORS.taut);
    if (tension < 0.55) {
        return slack.lerp(amber, clamp((tension - 0.3) / 0.25, 0, 1));
    }
    return amber.lerp(taut, clamp((tension - 0.55) / 0.35, 0, 1));
}

function tubeAlong(points, radius) {
    const path = new THREE.CurvePath();
    for (let i = 1; i < points.length; i++) {
        path.add(new THREE.LineCurve3(points[i - 1], points[i]));
    }
    return new THREE.TubeGeometry(path, 20 * (points.length - 1), radius, 10, false);
}

function clearGroup(group) {
    for (const child of [...group.children]) {
        child.geometry?.dispose();
        child.material?.dispose();
        group.remove(child);
    }
}

function cordMuscles() {
    const ids = new Set();
    if (state.selection?.type === "muscle") {
        ids.add(state.selection.id);
    }
    if (state.show.cords) {
        for (const id of musclesInScope()) {
            ids.add(id);
        }
    }
    if (state.tab === "movements" && state.movement) {
        for (const id of movementMovers(state.movement).prime) {
            ids.add(id);
        }
    }
    return [...ids];
}

function rebuildCords() {
    clearGroup(cordGroup);
    const selectedId = state.selection?.type === "muscle" ? state.selection.id : null;

    for (const id of cordMuscles()) {
        const path = cordPath(id);
        if (!path) {
            continue;
        }
        const selected = id === selectedId;
        const color = selected ? 0xff7a66 : 0xf09c8f;
        const material = new THREE.MeshStandardMaterial({
            color,
            emissive: color,
            emissiveIntensity: 0.35,
            roughness: 0.4,
            depthTest: false,
            transparent: true,
            opacity: path.approximate ? 0.5 : selected ? 0.95 : 0.75,
        });
        const radius = selected ? 0.36 : 0.26;
        const tube = new THREE.Mesh(tubeAlong(path.points, radius), material);
        tube.renderOrder = 10;
        tube.userData.cord = id;
        cordGroup.add(tube);

        const end = path.points[path.points.length - 1];
        const before = path.points[path.points.length - 2];
        const direction = before.clone().sub(end).normalize();
        const cone = new THREE.Mesh(new THREE.ConeGeometry(radius * 2.6, radius * 7, 14), material.clone());
        cone.position.copy(end).addScaledVector(direction, radius * 9);
        cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
        cone.renderOrder = 10;
        cone.userData.cord = id;
        cordGroup.add(cone);
    }

    // The patellar ligament has no mesh in the atlas, so draw it as a band.
    const ligament = entities.ligaments["patellar-ligament"];
    const ends = ligament?.between?.map((site) => sitePoint(site));
    if (ends?.every(Boolean)) {
        const band = new THREE.Mesh(
            tubeAlong(ends, 0.7),
            new THREE.MeshStandardMaterial({ color: tensionColor(ligamentTension("patellar-ligament")), roughness: 0.6 }),
        );
        band.userData.ligament = "patellar-ligament";
        band.userData.band = true;
        cordGroup.add(band);
        styleBand(band);
    }
}

/* ==========================================================================
 * Nerves
 * ======================================================================== */

/** A nerve followed by the trunks it branches from. */
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

function nervesToShow() {
    const names = new Set();
    if (state.tab === "nerves" && state.nerve.name) {
        names.add(state.nerve.name);
    }
    if (state.selection?.type === "muscle") {
        muscleNerves(entities.muscles[state.selection.id]).forEach((name) => names.add(name));
    }
    return [...names];
}

function rebuildNerves() {
    clearGroup(nerveGroup);
    const curves = new Set(nervesToShow().flatMap(nerveCurves));
    const matrices = segmentMatrices;

    for (const curveName of curves) {
        for (const path of state.body.nerves[curveName].paths) {
            const points = path.points.map((point, i) => {
                const v = new THREE.Vector3(...point);
                const a = v.clone().applyMatrix4(matrices[path.segs[i][0]]);
                const b = v.clone().applyMatrix4(matrices[path.segs[i][1]]);
                const w = path.w[i] / 255;
                return a.multiplyScalar(w).addScaledVector(b, 1 - w);
            });
            if (points.length < 2) {
                continue;
            }
            const curve = new THREE.CatmullRomCurve3(points);
            const tube = new THREE.Mesh(
                new THREE.TubeGeometry(curve, points.length * 8, 0.38, 8, false),
                new THREE.MeshStandardMaterial({
                    color: COLORS.nerve,
                    emissive: COLORS.nerve,
                    emissiveIntensity: 0.45,
                    roughness: 0.5,
                    depthTest: false,
                    transparent: true,
                    opacity: 0.9,
                }),
            );
            tube.renderOrder = 9;
            nerveGroup.add(tube);
        }
    }
}

/* ==========================================================================
 * Scope: which part of the body is being studied
 * ======================================================================== */

function ancestors(id) {
    const chain = [];
    let current = id;
    while (current) {
        chain.unshift(current);
        current = tree[current]?.parent;
    }
    return chain;
}

/** The nearest node at or above `id` that defines joint controls. */
function scopeNode(id = state.node) {
    let current = id;
    while (current) {
        if (tree[current]?.controls) {
            return current;
        }
        current = tree[current]?.parent;
    }
    return "body";
}

const REGION_IDS = ["head-neck", "trunk", "upper-limb", "lower-limb"];

/** Areas (shoulder, thigh-knee, …) covered by a tree node; null for the whole body. */
function areasUnder(id) {
    if (!id || id === "body") {
        return null;
    }
    if (REGION_IDS.includes(id)) {
        return tree[id].children;
    }
    if (tree[id]?.region) {
        return [id];
    }
    const area = ancestors(id).find((nodeId) => tree[nodeId]?.region);
    return area ? [area] : null;
}

function musclesInScope(node = state.node) {
    const all = Object.keys(entities.muscles);
    if (!node || node === "body" || !tree[node]) {
        return all;
    }
    const areas = areasUnder(node);
    if (tree[node].controls) {
        return all.filter((id) => areas.includes(entities.muscles[id].area));
    }
    // A group: only its own muscles.
    return (tree[node].children ?? []).filter((id) => entities.muscles[id]);
}

function scopeSegments(node = state.node) {
    const areas = areasUnder(node);
    if (!areas) {
        return null;
    }
    const segments = new Set();
    for (const area of areas) {
        const bonesGroup = tree[area].children.find((child) => child.endsWith("--bones"));
        for (const boneId of tree[bonesGroup]?.children ?? []) {
            const bone = entities.bones[boneId];
            if (bone) {
                segments.add(bone.segment);
            }
        }
    }
    return segments;
}

function scopeControls(node = state.node) {
    return tree[scopeNode(node)]?.controls ?? [];
}

function scopeIncludesKnee() {
    return scopeControls().includes("knee");
}

/* ==========================================================================
 * Appearance
 * ======================================================================== */

function setLook(part, look) {
    const settings = { visible: true, color: COLORS.bone, opacity: 1, emissive: 0, emissiveIntensity: 0, ...look };
    const material = part.mesh.material;
    part.mesh.visible = settings.visible;
    if (!settings.visible) {
        return;
    }
    material.color.setHex(settings.color);
    material.emissive.setHex(settings.emissive);
    material.emissiveIntensity = settings.emissiveIntensity;
    const transparent = settings.opacity < 0.999;
    if (material.transparent !== transparent) {
        material.transparent = transparent;
        material.needsUpdate = true;
    }
    material.opacity = settings.opacity;
    material.depthWrite = !transparent || settings.opacity > 0.5;
}

function highlightSets() {
    const { selection, tab, nerve, movement, quiz } = state;
    const sets = {
        focus: new Set(),
        prime: new Set(),
        assist: new Set(),
        nerve: new Set(),
        lost: new Set(),
        patches: new Map(),
        dimOthers: false,
        hideMuscles: false,
    };

    if (tab === "quiz" && quiz?.current?.tap) {
        sets.hideMuscles = true;
        for (const patch of quiz.current.candidates) {
            sets.patches.set(patch, quiz.current.revealed?.has(patch) ? "correct" : "neutral");
        }
        return sets;
    }

    if (tab === "nerves" && nerve.name) {
        for (const id of musclesForNerve(nerve.name)) {
            (nerve.injury ? sets.lost : sets.nerve).add(id);
        }
        sets.dimOthers = true;
        return sets;
    }

    if (tab === "movements" && movement) {
        const movers = movementMovers(movement);
        movers.prime.forEach((id) => sets.prime.add(id));
        movers.assist.forEach((id) => sets.assist.add(id));
        sets.dimOthers = true;
        return sets;
    }

    if (!selection) {
        return sets;
    }

    if (selection.type === "muscle") {
        const muscle = entities.muscles[selection.id];
        sets.focus.add(selection.id);
        sets.dimOthers = true;
        for (const patch of musclePatches(muscle, "origin")) {
            sets.patches.set(patch, "origin");
        }
        for (const patch of musclePatches(muscle, "insertion")) {
            sets.patches.set(patch, "insertion");
        }
    } else if (selection.type === "ligament" || selection.type === "structure") {
        sets.focus.add(selection.id);
        sets.dimOthers = true;
        sets.hideMuscles = true;
    } else if (selection.type === "patch" || selection.type === "site" || selection.type === "bone") {
        for (const patch of patchesFor(selection)) {
            sets.patches.set(patch, state.body.meshes[patch].role);
        }
        if (selection.type === "bone") {
            sets.focus.add(selection.id);
        }
        sets.hideMuscles = true;
    } else if (selection.type === "tissue") {
        sets.focus.add(selection.id);
        sets.dimOthers = true;
    }
    return sets;
}

function musclePatches(muscle, role) {
    return role === "origin" ? muscle.origins : muscle.insertions;
}

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

function applyAppearance() {
    const sets = highlightSets();
    const scoped = new Set(musclesInScope());
    const atBody = state.node === "body";
    const segments = scopeSegments();
    const kneeGroup = state.node === "knee-joint";
    const scopeRegion = ancestors(state.node).find((nodeId) => REGION_IDS.includes(nodeId)) ?? null;

    for (const part of Object.values(parts)) {
        const owner = part.owner;

        if (part.kind === "bone") {
            const focused = owner && sets.focus.has(owner.id);
            const inScope = !segments || segments.has(part.segment) && !part.name.endsWith(".l");
            setLook(part, {
                color: inScope ? COLORS.bone : COLORS.boneContext,
                opacity: inScope ? 1 : 0.55,
                emissive: focused ? 0x3a3020 : 0,
                emissiveIntensity: focused ? 1 : 0,
            });
            continue;
        }

        if (part.kind === "patch") {
            const role = sets.patches.get(part.name);
            const always = state.show.sites && !sets.hideMuscles && (part.info.muscles ?? []).some((m) => scoped.has(m));
            if (!role && !always) {
                setLook(part, { visible: false });
                continue;
            }
            const color = {
                origin: COLORS.origin,
                insertion: COLORS.insertion,
                neutral: COLORS.neutralSite,
                correct: COLORS.correct,
            }[role ?? part.info.role] ?? COLORS.neutralSite;
            setLook(part, { color, emissive: color, emissiveIntensity: 0.25 });
            continue;
        }

        if (part.kind === "muscle" || part.kind === "tissue") {
            const id = owner?.id;
            const base = part.kind === "tissue" ? COLORS.tissue : part.mirror ? COLORS.muscleMirror : COLORS.muscle;
            const muscle = entities.muscles[id];

            if (!state.show.muscles || sets.hideMuscles) {
                setLook(part, { visible: false });
                continue;
            }
            if (state.show.deep && muscle?.superficial) {
                setLook(part, { visible: false });
                continue;
            }

            const inScope = atBody || (part.kind === "tissue" ? scopeHasArea(entities.tissues[id]?.area) : scoped.has(id));
            const ghost = { color: base, opacity: kneeGroup ? 0.05 : 0.08 };

            // The mirrored left side is context for the whole-body view only.
            if (part.mirror) {
                setLook(part, atBody && !sets.dimOthers ? { color: base } : { visible: false });
                continue;
            }

            // Muscles from other regions are hidden rather than ghosted: fewer
            // transparent layers keeps phones fast and the view uncluttered.
            const area = part.kind === "tissue" ? entities.tissues[id]?.area : muscle?.area;
            const highlighted = sets.focus.has(id) || sets.prime.has(id) || sets.assist.has(id)
                || sets.nerve.has(id) || sets.lost.has(id);
            if (!atBody && !highlighted && scopeRegion && tree[area]?.parent !== scopeRegion) {
                setLook(part, { visible: false });
                continue;
            }
            if (sets.focus.has(id)) {
                setLook(part, { color: base, emissive: 0x401010, emissiveIntensity: 1 });
            } else if (sets.prime.has(id)) {
                setLook(part, { color: COLORS.prime, emissive: COLORS.prime, emissiveIntensity: 0.25 });
            } else if (sets.assist.has(id)) {
                setLook(part, { color: COLORS.assist, opacity: 0.85 });
            } else if (sets.nerve.has(id)) {
                setLook(part, { color: base, emissive: 0x3a1408, emissiveIntensity: 1 });
            } else if (sets.lost.has(id)) {
                setLook(part, { color: COLORS.lost, opacity: 0.9 });
            } else if (sets.dimOthers || !inScope || kneeGroup) {
                setLook(part, ghost);
            } else {
                setLook(part, { color: base });
            }
            continue;
        }

        if (part.kind === "ligament") {
            const id = owner?.id;
            if (owner?.type === "structure") {
                const focused = sets.focus.has(id);
                setLook(part, {
                    color: COLORS.meniscus,
                    emissive: focused ? 0x204050 : 0,
                    emissiveIntensity: focused ? 1 : 0,
                    opacity: sets.dimOthers && !focused ? 0.35 : 1,
                });
                continue;
            }
            const focused = sets.focus.has(id);
            const color = tensionColor(id ? ligamentTension(id) : 0).getHex();
            setLook(part, {
                color,
                emissive: focused ? color : 0,
                emissiveIntensity: focused ? 0.35 : 0,
                opacity: sets.dimOthers && !focused ? 0.3 : 1,
            });
        }
    }

    for (const child of cordGroup.children) {
        if (child.userData.band) {
            styleBand(child);
        }
    }

    renderCrumbs();
    renderScopeBar();
    renderControls();
    rebuildLabels();
}

function scopeHasArea(area) {
    const areas = areasUnder(state.node);
    return !areas || areas.includes(area);
}

function styleBand(band) {
    const { selection } = state;
    const focused = selection?.type === "ligament" && selection.id === "patellar-ligament";
    const dim = selection && !focused && ["ligament", "structure"].includes(selection.type);
    const outOfScope = !scopeIncludesKnee() && state.node !== "body";
    band.visible = !outOfScope;
    band.material.transparent = Boolean(dim);
    band.material.opacity = dim ? 0.3 : 1;
    band.material.emissive.copy(focused ? band.material.color : new THREE.Color(0));
    band.material.emissiveIntensity = focused ? 0.35 : 0;
}

/* ==========================================================================
 * Labels pinned to the model
 * ======================================================================== */

const labelsEl = $("#labels");
let labels = [];

const landmarkCache = [];

function nearestLandmark(point, boneMesh) {
    if (!landmarkCache.length) {
        for (const [name, info] of Object.entries(state.body.landmarks)) {
            if (LANDMARK_SKIP.test(name) || entities.bones[name.toLowerCase()]) {
                continue;
            }
            landmarkCache.push({ name, bone: info.bone, point: new THREE.Vector3(...info.point) });
        }
    }
    let best = null;
    for (const item of landmarkCache) {
        if (boneMesh && item.bone !== boneMesh) {
            continue;
        }
        const distance = item.point.distanceTo(point);
        if (distance < 4 && (!best || distance < best.distance)) {
            best = { name: item.name, distance };
        }
    }
    return best?.name ?? null;
}

function patchDescription(patches) {
    const first = state.body.meshes[patches[0]];
    if (!first) {
        return null;
    }
    const bone = Object.values(entities.bones).find((b) => b.mesh === first.bone);
    const near = nearestLandmark(new THREE.Vector3(...first.centroid), first.bone);
    if (near) {
        return `near the ${lowerFirst(near)}`;
    }
    return bone ? `on the ${lowerFirst(bone.name)}` : null;
}

function rebuildLabels() {
    labelsEl.innerHTML = "";
    labels = [];
    const { selection, tab } = state;

    const add = (text, sub, color, getPoint) => {
        const el = document.createElement("div");
        el.className = "tag";
        el.style.setProperty("--c", color);
        el.innerHTML = `${escapeHtml(text)}${sub ? `<small>${escapeHtml(sub)}</small>` : ""}`;
        labelsEl.appendChild(el);
        labels.push({ el, getPoint });
    };

    if (tab !== "explore") {
        return;
    }

    if (selection?.type === "muscle") {
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
    }

    if (selection?.type === "site") {
        add(entities.sites[selection.id].name, "Attachment site", "#c8d0d4", () => sitePoint(selection.id));
        return;
    }

    if (selection?.type === "patch") {
        const info = state.body.meshes[selection.id];
        add(patchTitle(selection.id), "Attachment", "#c8d0d4", () => patchPoint(selection.id));
        return;
    }

    if (state.node === "knee-joint" || selection?.type === "ligament") {
        for (const [id, ligament] of Object.entries(entities.ligaments)) {
            if (selection?.type === "ligament" && selection.id !== id) {
                continue;
            }
            add(ligament.short, null, "#" + tensionColor(ligamentTension(id)).getHexString(), () => ligamentAnchor(id));
        }
    }
}

function ligamentAnchor(id) {
    const ligament = entities.ligaments[id];
    if (ligament.between) {
        const ends = ligament.between.map((site) => sitePoint(site));
        return ends.every(Boolean) ? ends[0].add(ends[1]).multiplyScalar(0.5) : null;
    }
    const part = parts[ligament.mesh];
    if (!part) {
        return null;
    }
    const count = part.base.length / 3;
    return averagePoints([0, Math.floor(count / 3), Math.floor((2 * count) / 3)].map((v) => skinVertex(part, v)));
}

function placeLabels() {
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    const placed = [];

    for (const label of labels) {
        const world = label.getPoint();
        if (!world) {
            label.el.hidden = true;
            continue;
        }
        const point = world.project(camera);
        if (point.z > 1) {
            label.el.hidden = true;
            continue;
        }
        label.el.hidden = false;
        let x = (point.x * 0.5 + 0.5) * width + 10;
        let y = (-point.y * 0.5 + 0.5) * height - 12;
        const w = label.el.offsetWidth;
        const h = label.el.offsetHeight;
        x = clamp(x, 6, width - w - 6);
        for (const other of placed) {
            if (Math.abs(other.x - x) < w && Math.abs(other.y - y) < h + 2) {
                y = other.y + h + 4;
            }
        }
        y = clamp(y, 50, height - h - 90);
        placed.push({ x, y });
        label.el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    }
}

/* ==========================================================================
 * Camera framing
 * ======================================================================== */

function frameBox(box, padding, view) {
    if (box.isEmpty()) {
        return;
    }
    const centre = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const radius = Math.max(size.length() / 2, 5) * padding;
    const verticalFov = THREE.MathUtils.degToRad(camera.fov);
    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * camera.aspect);
    const distance = radius / Math.sin(Math.min(verticalFov, horizontalFov) / 2);
    centre.y -= radius * 0.06;

    const direction = view
        ? new THREE.Vector3(...view).normalize()
        : camera.position.clone().sub(orbit.target).normalize();

    cameraGoal = { target: centre, position: centre.clone().addScaledVector(direction, distance) };
    if (REDUCED_MOTION) {
        snapCamera();
    }
}

function snapCamera() {
    if (cameraGoal) {
        orbit.target.copy(cameraGoal.target);
        camera.position.copy(cameraGoal.position);
        cameraGoal = null;
    }
}

function boxOfMeshes(names) {
    const box = new THREE.Box3();
    for (const name of names) {
        const part = parts[name];
        if (!part) {
            continue;
        }
        part.mesh.geometry.computeBoundingBox();
        box.union(part.mesh.geometry.boundingBox.clone().applyMatrix4(part.mesh.matrix));
    }
    return box;
}

function boxOfSegments(segments) {
    return boxOfMeshes(
        Object.values(parts)
            .filter((part) => part.kind === "bone" && segments.has(part.segment) && !part.name.endsWith(".l"))
            .map((part) => part.key),
    );
}

function groupView(groupName, area) {
    if (/^Sole/i.test(groupName)) {
        return [-0.2, -0.9, 0.35];
    }
    if (/Pelvic floor/i.test(groupName)) {
        return [0, 1, 0.55];
    }
    if (/Dorsum/i.test(groupName)) {
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

function frameCurrent() {
    const { selection, node } = state;

    if (selection) {
        const type = selection.type;
        if (type === "muscle") {
            const muscle = entities.muscles[selection.id];
            frameBox(boxOfMeshes([muscle.mesh]), 1.25, groupView(muscle.groupName, muscle.area));
            return;
        }
        if (type === "ligament" || type === "structure") {
            const view = LIGAMENT_VIEW[selection.id] ?? VIEWS.front;
            const names = entities.ligaments[selection.id]?.between ? ["Patella.r"] : ownedMeshes[selection.id];
            frameBox(boxOfMeshes(names), 2.6, view);
            return;
        }
        if (type === "patch" || type === "site") {
            const names = patchesFor(selection);
            const point = averagePoints(names.map((patch) => patchPoint(patch)));
            const info = state.body.meshes[names[0]];
            const boneBox = boxOfMeshes(info ? [info.bone] : []);
            frameBox(boxOfMeshes(names), 4, point ? viewToward(point, boneBox) : VIEWS.front);
            return;
        }
        if (type === "bone" || type === "tissue") {
            frameBox(boxOfMeshes(ownedMeshes[selection.id]), 1.15, VIEWS.front);
            return;
        }
    }

    if (node === "body") {
        frameBox(boxOfMeshes(Object.keys(parts).filter((key) => parts[key].kind === "bone")), 0.95, [-0.25, 0.08, 1]);
        return;
    }
    if (node === "knee-joint") {
        frameBox(boxOfMeshes(ownedMeshes.acl.concat(ownedMeshes.lcl, ownedMeshes.mcl)), 2.2, VIEWS.front);
        return;
    }

    const segments = scopeSegments(node);
    const area = ancestors(node).find((id) => tree[id]?.region);
    let view = AREA_VIEW[area] ?? VIEWS.front;
    if (tree[node] && !tree[node].controls && area) {
        view = groupView(tree[node].name, area);
    }
    if (["head-neck", "trunk", "upper-limb", "lower-limb"].includes(node)) {
        view = { "head-neck": [-0.5, 0.1, 1], trunk: [-0.4, 0.1, 1], "upper-limb": [-0.7, 0.1, 1], "lower-limb": [-0.5, 0.1, 1] }[node];
    }
    const muscleBox = boxOfMeshes(musclesInScope(node).map((id) => entities.muscles[id].mesh));
    const box = segments ? boxOfSegments(segments) : new THREE.Box3();
    if (!tree[node]?.controls && !muscleBox.isEmpty()) {
        // Small groups (pelvic floor, suboccipitals) need more room around them.
        const small = muscleBox.getSize(new THREE.Vector3()).length() < 18;
        frameBox(muscleBox, small ? 1.9 : 1.15, view);
        return;
    }
    frameBox(box.union(muscleBox), 1.0, view);
}

/** Camera direction that looks at `point` from outside the given box. */
function viewToward(point, box = null) {
    const centre = box && !box.isEmpty() ? box.getCenter(new THREE.Vector3()) : new THREE.Vector3(0, point.y, 0);
    const direction = new THREE.Vector3(point.x - centre.x, 0, point.z - centre.z);
    if (direction.lengthSq() < 0.01) {
        return VIEWS.front;
    }
    direction.normalize();
    return [direction.x, 0.25, direction.z];
}

/* ==========================================================================
 * Navigation
 * ======================================================================== */

function entityType(id) {
    if (tree[id]) return "node";
    if (entities.muscles[id]) return "muscle";
    if (entities.ligaments[id]) return "ligament";
    if (entities.structures[id]) return "structure";
    if (entities.bones[id]) return "bone";
    if (entities.tissues[id]) return "tissue";
    if (entities.sites[id]) return "site";
    if (state.body.meshes[id]?.kind === "patch") return "patch";
    return null;
}

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

function entityName(id) {
    if (tree[id]) return tree[id].name;
    const group = entities.muscles[id] ?? entities.ligaments[id] ?? entities.structures[id]
        ?? entities.bones[id] ?? entities.tissues[id] ?? entities.sites[id];
    if (group) return group.name;
    if (state.body.meshes[id]?.kind === "patch") return patchTitle(id);
    return id;
}

function parentNodeOf(id) {
    if (entities.bones[id]) {
        const groups = Object.keys(tree).filter((nodeId) => nodeId.endsWith("--bones") && tree[nodeId].children.includes(id));
        const current = ancestors(state.node);
        return groups.find((group) => current.includes(tree[group].parent)) ?? groups[0] ?? state.node;
    }
    for (const [nodeId, node] of Object.entries(tree)) {
        if (node.children?.includes(id)) {
            return nodeId;
        }
    }
    if (entities.tissues[id]) {
        return entities.tissues[id].area;
    }
    if (entities.sites[id]) {
        return "thigh-knee";
    }
    return state.node;
}

function openEntity(id, options = {}) {
    const type = entityType(id);
    if (!type) {
        return;
    }
    hidePop();
    state.animation = null;

    const previousControls = scopeControls();
    const previousNode = state.node;

    if (type === "node") {
        state.node = id;
        state.selection = null;
    } else {
        const parent = parentNodeOf(id);
        if (parent && tree[parent]) {
            state.node = parent;
        }
        state.selection = { type, id };
    }

    const visible = new Set(scopeControls());
    for (const control of previousControls) {
        if (!visible.has(control) && state.pose[control]) {
            setPose(control, 0);
        }
    }

    // A quiz belongs to the area or group it was started in.
    if (state.node !== previousNode) {
        state.quiz = null;
    }

    if (state.tab !== "explore" && options.keepTab !== true) {
        showTab("explore", { skipRender: true });
    }

    state.dirty = true;
    applyAppearance();
    renderActiveTab();
    if (options.frame !== false) {
        frameCurrent();
    }
    $("#views").scrollTop = 0;
}

function goUp() {
    if (state.selection) {
        openEntity(state.node);
        return;
    }
    const parent = tree[state.node]?.parent;
    if (parent) {
        openEntity(parent);
    }
}

/** On the model, a tap at a broad level narrows by one level instead of jumping. */
function openFromModel(id) {
    const chain = ancestors(parentNodeOf(id));
    const atBroadLevel = ["body", "head-neck", "trunk", "upper-limb", "lower-limb"].includes(state.node) && !state.selection;
    if (atBroadLevel) {
        const index = chain.indexOf(state.node);
        const next = index >= 0 ? chain[index + 1] : null;
        if (next) {
            openEntity(next);
            return;
        }
    }
    openEntity(id);
}

function renderCrumbs() {
    const trail = ancestors(state.node);
    if (state.selection) {
        trail.push(state.selection.id);
    }
    $("#crumbs").innerHTML = trail
        .map((item, index) => {
            const name = escapeHtml(entityName(item));
            const separator = index > 0 ? '<span class="sep" aria-hidden="true">›</span>' : "";
            if (index === trail.length - 1) {
                return `${separator}<span class="here">${name}</span>`;
            }
            return `${separator}<button type="button" data-open="${escapeHtml(item)}">${name}</button>`;
        })
        .join("");
}

function renderScopeBar() {
    const scope = scopeNode();
    const bar = $("#scope-bar");
    if (scope === "body") {
        bar.innerHTML = `Studying <b>the whole body</b>`;
        return;
    }
    bar.innerHTML = `Studying <b>${escapeHtml(tree[scope].name)}</b><button type="button" data-open="body">Whole body</button>`;
}

/* ==========================================================================
 * Joint controls
 * ======================================================================== */

let renderedControls = "";

function controlById(id) {
    return state.body.controls.find((control) => control.id === id);
}

function renderControls() {
    const ids = scopeControls();
    const key = ids.join(",");
    if (key === renderedControls) {
        return;
    }
    renderedControls = key;
    $("#controls").innerHTML = ids
        .map((id) => {
            const control = controlById(id);
            const value = Math.round(state.pose[id] ?? 0);
            return `
                <div class="ctl">
                    <label for="ctl-${id}">${escapeHtml(control.label)} <output id="out-${id}">${value}°</output></label>
                    <input id="ctl-${id}" type="range" min="${control.min}" max="${control.max}" value="${value}" step="1" data-control="${id}">
                </div>`;
        })
        .join("");
}

function setPose(id, value) {
    const control = controlById(id);
    state.pose[id] = clamp(value, control.min, control.max);
    const input = $(`#ctl-${id}`);
    if (input) {
        input.value = Math.round(state.pose[id]);
        $(`#out-${id}`).textContent = `${Math.round(state.pose[id])}°`;
    }
    state.dirty = true;
}

function resetPose() {
    state.animation = null;
    for (const control of state.body.controls) {
        setPose(control.id, 0);
    }
}

/* ==========================================================================
 * Movements
 * ======================================================================== */

function generatedMovements(controlIds) {
    const list = [];
    for (const id of controlIds) {
        const control = controlById(id);
        list.push({
            id: `${id}:+`,
            name: control.positive,
            control: id,
            rig: { control: id, from: 0, to: Math.round(control.max * 0.7) },
        });
        list.push({
            id: `${id}:-`,
            name: control.negative,
            control: id,
            rig: control.min < 0
                ? { control: id, from: 0, to: Math.round(control.min * 0.8) }
                : { control: id, from: Math.round(control.max * 0.6), to: 0 },
        });
    }
    return list;
}


function movementById(id) {
    const notes = state.content.movements[id];
    if (id.includes(":")) {
        const control = id.split(":")[0];
        const generated = generatedMovements([control]).find((movement) => movement.id === id);
        return generated ? { ...notes, ...generated } : null;
    }
    return notes ? { id, ...notes } : null;
}

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

/** Prime and assist muscles for a movement, from the notes or the model. */
function movementMovers(movementId) {
    const movement = movementById(movementId);
    return {
        prime: movement?.prime ?? [],
        assist: movement?.assist ?? [],
        note: movement?.note ?? null,
    };
}

/* ==========================================================================
 * Motion playback
 * ======================================================================== */

function playMotion(rig) {
    if (!rig) {
        return;
    }
    const { control, from, to } = rig;
    if (REDUCED_MOTION) {
        setPose(control, to);
        return;
    }
    state.animation = {
        control,
        legs: [
            [state.pose[control] ?? 0, from, 450],
            [from, to, 1300],
            [to, from, 1100],
            [from, to, 1300],
        ],
        leg: 0,
        start: performance.now(),
    };
}

function stepAnimation(now) {
    const animation = state.animation;
    if (!animation) {
        return;
    }
    const [a, b, duration] = animation.legs[animation.leg];
    const t = clamp((now - animation.start) / duration, 0, 1);
    const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    setPose(animation.control, a + (b - a) * eased);
    if (t >= 1) {
        animation.leg++;
        animation.start = now;
        if (animation.leg >= animation.legs.length) {
            state.animation = null;
        }
    }
}

/* ==========================================================================
 * Glossary
 * ======================================================================== */

let glossaryPattern = null;

function linkTerms(text, seen = new Set()) {
    if (!glossaryPattern) {
        const terms = Object.keys(state.content.glossary).sort((a, b) => b.length - a.length);
        glossaryPattern = new RegExp(`\\b(${terms.map((t) => t.replace(/-/g, "\\-")).join("|")})\\b`, "gi");
    }
    return escapeHtml(text).replace(glossaryPattern, (match) => {
        const key = match.toLowerCase();
        if (seen.has(key)) {
            return match;
        }
        seen.add(key);
        return `<button type="button" class="term" data-term="${escapeHtml(key)}">${match}</button>`;
    });
}

const pop = $("#pop");

function showTerm(term, anchor) {
    const definition = state.content.glossary[term];
    if (!definition) {
        return;
    }
    pop.innerHTML = `<b>${escapeHtml(term)}</b>${escapeHtml(definition)}`;
    pop.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const left = clamp(rect.left, 12, innerWidth - pop.offsetWidth - 12);
    let top = rect.bottom + 8;
    if (top + pop.offsetHeight > innerHeight - 12) {
        top = rect.top - pop.offsetHeight - 8;
    }
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
}

function hidePop() {
    pop.hidden = true;
}

/* ==========================================================================
 * Explore panel
 * ======================================================================== */

const paneExplore = $("#pane-explore");

function chip(id, label, extra = "") {
    return `<button class="chip" type="button" data-open="${escapeHtml(id)}">${escapeHtml(label ?? entityName(id))}${extra}</button>`;
}

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

function card(id) {
    const description = describeChild(id);
    return `
        <button class="card" type="button" data-open="${escapeHtml(id)}">
            <span class="nm">${escapeHtml(entityName(id))}</span>
            ${description ? `<span class="ds">${linkTerms(description)}</span>` : ""}
        </button>`;
}


function controlNames(ids) {
    return ids.map((id) => lowerFirst(controlById(id).label)).join(", ");
}

function renderNodePane(id) {
    const node = tree[id];
    const isBody = id === "body";
    const isRegion = ["head-neck", "trunk", "upper-limb", "lower-limb"].includes(id);
    let html = `
        <div class="eyebrow">${isBody ? "Start here" : isRegion ? "Region" : node.controls ? "Area" : "Group"}</div>
        <h2>${escapeHtml(node.name)}</h2>`;

    if (isBody) {
        html += `
            <p class="lede">Choose a region to narrow what you study. The sliders and the Movements, Nerves and Quiz tabs follow your choice.</p>
            <p class="note">The right side is the one you study; the left side mirrors it for context. Every muscle has draft notes (origin, insertion, nerve, roots, actions) that still need checking against your textbook.</p>`;
    } else if (node.summary) {
        html += `<p class="lede">${linkTerms(node.summary)}</p>`;
    } else if (node.controls) {
        html += `<p class="lede">Joints you can move here: ${escapeHtml(controlNames(node.controls))}.</p>`;
    }

    if (id === "knee-joint") {
        html += `
            <div class="legend">
                <span><i class="key" style="--k: var(--slack)"></i>Slack</span>
                <span><i class="key" style="--k: #f0a43a"></i>Tightening</span>
                <span><i class="key" style="--k: var(--taut)"></i>Taut</span>
            </div>
            <div class="actions-row"><button class="btn" type="button" data-sweep="knee">Bend and straighten the knee</button></div>`;
    }

    html += `<h3>${isBody ? "Regions" : isRegion ? "Areas" : "Inside"}</h3><div class="cards">`;
    for (const child of node.children ?? []) {
        html += card(child);
    }
    html += `</div>`;

    if (!isBody) {
        html += `
            <div class="legend">
                <span><i class="key" style="--k: var(--origin)"></i>Origin</span>
                <span><i class="key" style="--k: var(--insertion)"></i>Insertion</span>
                <span><i class="key" style="--k: var(--nerve)"></i>Nerve</span>
            </div>`;
    }
    return html;
}

function nerveLabel(muscle) {
    const notes = muscle.notes;
    if (!notes) {
        return "";
    }
    return notes.nerveNote ?? state.content.nerves[notes.nerve].name;
}

function lengthMeter() {
    return `
        <div class="meter" id="length-meter">
            <div class="meter-row">
                <span>Line of pull, compared with standing</span>
                <strong id="length-value">100%</strong>
            </div>
            <div class="bar"><i id="length-bar"></i></div>
            <span class="lede" id="length-text">Move a joint, or tap an action, to watch it change.</span>
        </div>`;
}

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



function renderLigamentPane(id) {
    const ligament = entities.ligaments[id];
    const seen = new Set();
    return `
        <div class="eyebrow">Knee ligament <span class="badge notes">Notes</span> <span class="badge draft">Draft · unreviewed</span></div>
        <h2>${escapeHtml(ligament.name)}</h2>
        <dl class="facts">
            <div class="fact"><dt>Attaches</dt><dd>${linkTerms(ligament.attachmentText, seen)}</dd></div>
            <div class="fact"><dt>Job</dt><dd>${linkTerms(ligament.function, seen)}</dd></div>
            <div class="fact"><dt>Taut in</dt><dd>${linkTerms(ligament.tautText, seen)}</dd></div>
        </dl>
        <div class="meter">
            <div class="meter-row">
                <span>Tension at <b id="tension-angle">0°</b> of knee flexion</span>
                <strong id="tension-word">Taut</strong>
            </div>
            <div class="bar"><i id="tension-bar"></i></div>
            <span class="lede">Colours follow the rule written for this ligament, not a physics simulation.</span>
        </div>
        <div class="actions-row"><button class="btn" type="button" data-sweep="knee">Bend and straighten the knee</button></div>`;
}

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

function renderAttachmentPane(selection) {
    const patches = patchesFor(selection);
    const title = selection.type === "site" ? entities.sites[selection.id].name : patchTitle(selection.id);
    return `
        <div class="eyebrow">Attachment site</div>
        <h2>${escapeHtml(title)}</h2>
        ${attachmentsBlock(patches)}
        <p class="lede">Exams often ask this in reverse: given a landmark, name everything attached to it.</p>`;
}

function renderBonePane(id) {
    const bone = entities.bones[id];
    const patches = patchesFor({ type: "bone", id });
    let html = `<div class="eyebrow">Bone</div><h2>${escapeHtml(bone.name)}</h2>`;
    if (!patches.length) {
        return html + `<p class="lede">No muscle attachments are marked on this bone in the atlas.</p>`;
    }
    html += `<p class="lede">Blue marks where muscles start; orange marks where they end. Tap a patch on the bone to see who attaches there.</p>`;
    return html + attachmentsBlock(patches);
}

function renderExplore() {
    const { selection } = state;
    let html;
    if (!selection) {
        html = renderNodePane(state.node);
    } else if (selection.type === "muscle") {
        html = renderMusclePane(entities.muscles[selection.id]);
    } else if (selection.type === "ligament") {
        html = renderLigamentPane(selection.id);
    } else if (selection.type === "structure") {
        const structure = entities.structures[selection.id];
        html = `<div class="eyebrow">Knee joint <span class="badge draft">Draft · unreviewed</span></div><h2>${escapeHtml(structure.name)}</h2><p>${linkTerms(structure.text)}</p>`;
    } else if (selection.type === "site" || selection.type === "patch") {
        html = renderAttachmentPane(selection);
    } else if (selection.type === "bone") {
        html = renderBonePane(selection.id);
    } else if (selection.type === "tissue") {
        const tissue = entities.tissues[selection.id];
        html = `<div class="eyebrow">Connective tissue</div><h2>${escapeHtml(tissue.name)}</h2><p class="lede">A tendon, band or sheet of fascia rather than a muscle. Written notes are not available yet.</p>`;
    }
    paneExplore.innerHTML = html;
    updateLiveReadouts();
}

function updateLiveReadouts() {
    const { selection } = state;
    if (selection?.type === "muscle") {
        const value = $("#length-value");
        if (!value) {
            return;
        }
        const ratio = lengthRatio(selection.id);
        if (ratio === null) {
            value.textContent = "–";
            $("#length-text").textContent = "This muscle is still loading.";
            return;
        }
        value.textContent = `${Math.round(ratio * 100)}%`;
        const bar = $("#length-bar");
        bar.style.setProperty("--w", `${clamp((ratio - 0.6) / 0.8, 0, 1) * 100}%`);
        bar.style.setProperty("--c", ratio < 0.98 ? "var(--good)" : ratio > 1.02 ? "var(--taut)" : "var(--muted)");
        let text = "At resting length. Move a joint to see it shorten or stretch.";
        if (ratio < 0.98) text = "Shorter than standing: this pose is in the direction the muscle pulls.";
        else if (ratio > 1.02) text = "Stretched: this pose is the opposite of what the muscle does.";
        $("#length-text").textContent = text;
    }
    if (selection?.type === "ligament") {
        const bar = $("#tension-bar");
        if (!bar) {
            return;
        }
        const tension = ligamentTension(selection.id);
        $("#tension-angle").textContent = `${Math.round(state.pose.knee ?? 0)}°`;
        $("#tension-word").textContent = tension > 0.85 ? "Taut" : tension > 0.55 ? "Tightening" : "Slack";
        bar.style.setProperty("--w", `${tension * 100}%`);
        bar.style.setProperty("--c", "#" + tensionColor(tension).getHexString());
    }
}

/* ==========================================================================
 * Nerves panel
 * ======================================================================== */

const paneNerves = $("#pane-nerves");

function musclesForNerve(nerveId) {
    return Object.values(entities.muscles)
        .filter((muscle) => muscleNerves(muscle).includes(nerveId))
        .map((muscle) => muscle.id);
}

function nervesInScope() {
    const ids = new Set();
    for (const id of musclesInScope(scopeNode())) {
        muscleNerves(entities.muscles[id]).forEach((nerve) => ids.add(nerve));
    }
    return [...ids].sort((a, b) => state.content.nerves[a].name.localeCompare(state.content.nerves[b].name));
}

function selectNerve(name) {
    state.nerve.name = name;
    state.dirty = true;
    applyAppearance();
    renderNerves();
    const ids = musclesForNerve(name);
    const box = boxOfMeshes(ids.map((id) => entities.muscles[id].mesh));
    frameBox(box, 1.2, null);
}

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

/* ==========================================================================
 * Movements panel
 * ======================================================================== */

const paneMovements = $("#pane-movements");

function selectMovement(id) {
    state.movement = id;
    state.dirty = true;
    applyAppearance();
    renderMovements();
    const movement = movementById(id);
    playMotion(movement?.rig);
    const sideways = ["shoulderAbd", "hipAbd", "trunkLat", "wristDev"].includes(movement?.control);
    const segments = scopeSegments(scopeNode()) ?? new Set(segmentOrder);
    frameBox(boxOfSegments(segments), 1.15, sideways ? VIEWS.front : VIEWS.right);
}

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

/* ==========================================================================
 * Quiz
 * ======================================================================== */

const paneQuiz = $("#pane-quiz");
const QUIZ_KEY = "pt-atlas-quiz-v1";

/** The node a quiz covers: the open group, or its area when the group has no muscles. */
function quizNode(node = state.node) {
    if (node === "knee-joint" || musclesInScope(node).length) {
        return node;
    }
    return scopeNode(node);
}

function quizItems(focus = null, node = quizNode()) {
    const items = [];
    const ids = focus ? [focus] : musclesInScope(node);
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
    const kneeLigaments = node === "knee-joint" || (tree[node]?.controls && scopeIncludesKnee());
    if (!focus && kneeLigaments) {
        for (const id of Object.keys(entities.ligaments)) {
            items.push({ key: `ligament:${id}`, kind: "ligament", ligament: id });
            if (id !== "patellar-ligament") {
                items.push({ key: `taut:${id}`, kind: "taut", ligament: id });
            }
        }
    }
    return items;
}

function loadBoxes() {
    return storageGet(QUIZ_KEY, {});
}

function pickQuestion() {
    const boxes = loadBoxes();
    const items = quizItems(state.quiz.focus, state.quiz.node);
    if (!items.length) {
        return null;
    }
    const last = state.quiz.current?.key;
    const weighted = [];
    for (const item of items) {
        if (item.key === last && items.length > 1) {
            continue;
        }
        const weight = [0, 8, 5, 3, 2, 1][boxes[item.key] ?? 1] ?? 1;
        for (let i = 0; i < weight; i++) {
            weighted.push(item);
        }
    }
    return buildQuestion(weighted[Math.floor(Math.random() * weighted.length)]);
}

function choices(correct, pool, count = 4) {
    return shuffle([correct, ...shuffle([...new Set(pool)].filter((v) => v !== correct)).slice(0, count - 1)]);
}

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

function recordAnswer(key, right) {
    const boxes = loadBoxes();
    boxes[key] = right ? Math.min(5, (boxes[key] ?? 1) + 1) : 1;
    storageSet(QUIZ_KEY, boxes);
}

function startQuiz(focus = null) {
    state.quiz = { focus, node: quizNode(), current: null, score: { right: 0, total: 0 } };
    nextQuestion();
}

function nextQuestion() {
    state.quiz.current = pickQuestion();
    const current = state.quiz.current;
    resetPose();
    state.selection = null;
    applyPose();
    applyAppearance();
    renderQuiz();
    if (current?.tap) {
        const names = [...current.answerPatches];
        const point = averagePoints(names.map((patch) => patchPoint(patch)));
        const segments = scopeSegments(scopeNode()) ?? new Set(segmentOrder);
        const box = boxOfSegments(segments);
        frameBox(box, 1.0, point ? viewToward(point, box) : VIEWS.front);
    }
}

function answerQuiz(choice) {
    const current = state.quiz.current;
    if (current.answered) {
        return;
    }
    current.answered = true;
    current.choice = choice;
    current.right = choice === current.correct;
    state.quiz.score.total++;
    if (current.right) state.quiz.score.right++;
    recordAnswer(current.key, current.right);
    renderQuiz();
}

function answerTap(patch) {
    const current = state.quiz?.current;
    if (!current?.tap || current.answered) {
        return;
    }
    current.answered = true;
    current.right = current.answerPatches.has(patch);
    current.tapped = patchTitle(patch);
    current.revealed = current.answerPatches;
    state.quiz.score.total++;
    if (current.right) state.quiz.score.right++;
    recordAnswer(current.key, current.right);
    applyAppearance();
    renderQuiz();
}

function renderQuiz() {
    const quiz = state.quiz;
    const boxes = loadBoxes();
    const items = quizItems(quiz?.focus, quiz?.node ?? quizNode());
    const counts = [0, 0, 0, 0, 0];
    for (const item of items) {
        counts[(boxes[item.key] ?? 1) - 1]++;
    }

    const scopeName = quiz?.focus ? entityName(quiz.focus) : tree[quiz?.node ?? quizNode()].name;
    let html = `<div class="eyebrow">Quiz · spaced repetition</div><h2>${escapeHtml(scopeName)}</h2>`;

    if (!items.length) {
        html += `<p class="lede">Nothing to quiz in this selection. Choose an area with muscles.</p>`;
    } else if (!quiz?.current) {
        html += `
            <p class="lede">${items.length} questions here. Ones you miss come back sooner; ones you know fade out. Tap questions ask you to find the answer on the model.</p>
            <div class="actions-row"><button class="btn" type="button" data-quiz-start>Start the quiz</button></div>`;
    } else {
        const current = quiz.current;
        html += `<div class="q"><div class="q-text">${escapeHtml(current.text)}</div>`;
        if (current.tap && !current.answered) {
            html += `<p class="lede">Muscles are hidden so you can see the bone. Grey patches are attachment sites in this area.</p>`;
        }
        if (!current.tap) {
            html += `<div class="options">${current.options
                .map((option) => {
                    let cls = "";
                    if (current.answered && option === current.correct) cls = " right";
                    else if (current.answered && option === current.choice) cls = " wrong";
                    return `<button class="opt${cls}" type="button" data-answer="${escapeHtml(option)}" ${current.answered ? "disabled" : ""}>${escapeHtml(option)}</button>`;
                })
                .join("")}</div>`;
        }
        if (current.answered) {
            const tapped = current.tap && !current.right ? ` You tapped: ${current.tapped}. The answer is shown in green.` : "";
            html += `
                <p class="feedback ${current.right ? "right" : "wrong"}">${current.right ? "Correct." : "Not quite."}${escapeHtml(tapped)}</p>
                <p>${linkTerms(current.explain)}</p>
                <div class="actions-row"><button class="btn" type="button" data-quiz-next>Next question</button></div>`;
        }
        html += `</div><p class="lede">This session: <b>${quiz.score.right}</b> of ${quiz.score.total} right.</p>`;
    }

    if (items.length) {
        html += `
            <h3>Your boxes</h3>
            <div class="boxes">${counts.map((count, i) => `<div class="box"><strong>${count}</strong>${i === 0 ? "New or missed" : i === 4 ? "Mastered" : `Box ${i + 1}`}</div>`).join("")}</div>
            <p class="lede">Progress is saved in this browser only.</p>`;
    }
    paneQuiz.innerHTML = html;
}

/* ==========================================================================
 * Terms panel
 * ======================================================================== */

const paneTerms = $("#pane-terms");

function renderTerms(filter = "") {
    const entries = Object.entries(state.content.glossary)
        .filter(([term, definition]) => !filter || term.includes(filter) || definition.toLowerCase().includes(filter))
        .sort(([a], [b]) => a.localeCompare(b));
    paneTerms.innerHTML = `
        <div class="eyebrow">Terms</div>
        <h2>Vocabulary</h2>
        <label class="eyebrow" for="term-search">Search</label>
        <input class="search" id="term-search" type="search" value="${escapeHtml(filter)}" placeholder="e.g. valgus, tuberosity" autocomplete="off">
        <dl class="gloss">${entries.length
            ? entries.map(([term, definition]) => `<div><dt>${escapeHtml(term)}</dt><dd>${escapeHtml(definition)}</dd></div>`).join("")
            : `<div><dd>No term matches “${escapeHtml(filter)}”.</dd></div>`}</dl>`;
    const input = $("#term-search");
    input.addEventListener("input", () => {
        const position = input.selectionStart;
        renderTerms(input.value.trim().toLowerCase());
        const next = $("#term-search");
        next.focus();
        next.setSelectionRange(position, position);
    });
}

/* ==========================================================================
 * Tabs
 * ======================================================================== */

const TABS = ["explore", "movements", "nerves", "quiz", "terms"];

function renderActiveTab() {
    if (state.tab === "explore") renderExplore();
    if (state.tab === "movements") renderMovements();
    if (state.tab === "nerves") renderNerves();
    if (state.tab === "quiz") renderQuiz();
    if (state.tab === "terms") renderTerms();
}

function showTab(name, options = {}) {
    if (name !== state.tab) {
        state.animation = null;
    }
    state.tab = name;
    for (const tab of TABS) {
        $(`#tab-${tab}`).setAttribute("aria-selected", String(tab === name));
        $(`#pane-${tab}`).hidden = tab !== name;
    }
    hidePop();
    if (!options.skipRender) {
        renderActiveTab();
    }
    state.dirty = true;
    applyAppearance();
}

/* ==========================================================================
 * Picking on the model
 * ======================================================================== */

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let pointerDown = null;

function pickAt(event) {
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);

    const candidates = [
        ...Object.values(parts)
            .filter((part) => !part.mirror && part.mesh.visible && part.mesh.material.opacity > 0.2)
            .map((part) => part.mesh),
        ...cordGroup.children.filter((child) => child.visible),
    ];
    const hits = raycaster.intersectObjects(candidates, false);
    if (!hits.length) {
        return null;
    }
    const front = hits[0].distance;
    const special = hits.find((hit) =>
        hit.distance < front + 1.5 && (hit.object.userData.cord || parts[hit.object.userData.part]?.kind === "patch"));
    return (special ?? hits[0]).object;
}

canvas.addEventListener("pointerdown", (event) => {
    pointerDown = { x: event.clientX, y: event.clientY, t: performance.now() };
});

canvas.addEventListener("pointerup", (event) => {
    if (!pointerDown) {
        return;
    }
    const moved = Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y);
    const quick = performance.now() - pointerDown.t < 600;
    pointerDown = null;
    if (moved > 6 || !quick) {
        return;
    }

    const object = pickAt(event);

    if (state.tab === "quiz" && state.quiz?.current?.tap) {
        const key = object?.userData.part;
        if (key && parts[key].kind === "patch") {
            answerTap(key);
        }
        return;
    }

    if (!object) {
        goUp();
        return;
    }
    if (object.userData.cord) {
        openFromModel(object.userData.cord);
        return;
    }
    if (object.userData.ligament) {
        openFromModel(object.userData.ligament);
        return;
    }
    const part = parts[object.userData.part];
    if (!part?.owner) {
        return;
    }
    if (part.owner.type === "patch") {
        openEntity(patchSite[part.owner.id] ?? part.owner.id);
        return;
    }
    openFromModel(part.owner.id);
});

/* ==========================================================================
 * Events
 * ======================================================================== */

document.addEventListener("click", (event) => {
    const target = event.target.closest("button, input");
    if (!target) {
        if (!event.target.closest(".pop")) hidePop();
        return;
    }
    const data = target.dataset;

    if (data.term) {
        event.stopPropagation();
        showTerm(data.term, target);
        return;
    }
    if (data.open) {
        openEntity(data.open);
        return;
    }
    if (data.nerve) {
        showTab("nerves", { skipRender: true });
        selectNerve(data.nerve);
        return;
    }
    if (data.selectNerve) {
        selectNerve(data.selectNerve);
        return;
    }
    if (data.selectMovement) {
        selectMovement(data.selectMovement);
        return;
    }
    if (data.playControl) {
        playMotion(JSON.parse(data.playControl));
        return;
    }
    if (data.showMovement) {
        showTab("movements", { skipRender: true });
        selectMovement(data.showMovement);
        return;
    }
    if (data.sweep) {
        playMotion({ control: "knee", from: 0, to: 110 });
        return;
    }
    if ("quizStart" in data) {
        startQuiz(null);
        return;
    }
    if (data.quizOn) {
        showTab("quiz", { skipRender: true });
        startQuiz(data.quizOn);
        return;
    }
    if ("quizNext" in data) {
        nextQuestion();
        return;
    }
    if (data.answer !== undefined && target.classList.contains("opt")) {
        answerQuiz(data.answer);
        return;
    }
    if (target.id === "injury-toggle") {
        state.nerve.injury = target.checked;
        state.dirty = true;
        applyAppearance();
        renderNerves();
        return;
    }
    hidePop();
});

$("#controls").addEventListener("input", (event) => {
    const id = event.target.dataset.control;
    if (id) {
        state.animation = null;
        setPose(id, Number(event.target.value));
    }
});

for (const tab of TABS) {
    $(`#tab-${tab}`).addEventListener("click", () => showTab(tab));
}

function toggle(id, key) {
    $(id).addEventListener("click", (event) => {
        state.show[key] = !state.show[key];
        event.currentTarget.setAttribute("aria-pressed", String(state.show[key]));
        state.dirty = true;
        applyAppearance();
    });
}

toggle("#tg-muscles", "muscles");
toggle("#tg-deep", "deep");
toggle("#tg-cords", "cords");
toggle("#tg-sites", "sites");

$("#tg-reset").addEventListener("click", resetPose);

document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
        return;
    }
    if (!pop.hidden) {
        hidePop();
        return;
    }
    if (!event.target.closest?.("input")) {
        goUp();
    }
});

orbit.addEventListener("start", () => {
    cameraGoal = null;
});

/* ==========================================================================
 * Loop
 * ======================================================================== */

let lastFrame = performance.now();

function tick(now) {
    const dt = Math.min((now - lastFrame) / 1000, 0.1);
    lastFrame = now;
    stepAnimation(now);

    if (state.dirty) {
        state.dirty = false;
        applyPose();
        for (const part of Object.values(parts)) {
            if (part.kind === "ligament" && part.owner?.type === "ligament" && part.mesh.visible) {
                part.mesh.material.color.copy(tensionColor(ligamentTension(part.owner.id)));
            }
        }
    }

    if (cameraGoal) {
        const ease = 1 - Math.exp(-dt * 7);
        camera.position.lerp(cameraGoal.position, ease);
        orbit.target.lerp(cameraGoal.target, ease);
        if (camera.position.distanceTo(cameraGoal.position) < 0.05) {
            cameraGoal = null;
        }
    }

    orbit.update();
    renderer.render(scene, camera);
    placeLabels();
    requestAnimationFrame(tick);
}

/* ==========================================================================
 * Boot
 * ======================================================================== */

async function boot() {
    try {
        const [body, content, attachments] = await Promise.all([
            fetch("body.json").then((response) => response.json()),
            fetch("anatomy.json").then((response) => response.json()),
            fetch("attachments.json").then((response) => response.json()),
        ]);
        state.body = body;
        state.content = content;
        state.attachments = attachments;
        setupEntities();
        await loadFile("skeleton.bin");
    } catch (error) {
        $("#loading-text").textContent = "The model files could not be loaded. Reload the page to try again.";
        console.error(error);
        return;
    }

    $("#credit").textContent = `${state.content.meta.modelCredit} All notes are drafts awaiting review.`;

    resize();
    camera.position.set(-60, 110, 420);
    orbit.target.set(0, 95, 0);
    applyPose();
    openEntity("body");
    snapCamera();
    $("#loading").hidden = true;
    requestAnimationFrame(tick);

    // Muscles stream in by region after the skeleton is on screen.
    const progress = $("#progress");
    const regionFiles = state.body.files.filter((file) => file !== "skeleton.bin");
    let done = 0;
    progress.hidden = false;
    progress.textContent = `Loading muscles 0/${regionFiles.length}`;
    await Promise.all(regionFiles.map(async (file) => {
        try {
            await loadFile(file);
        } catch (error) {
            console.error(error);
        }
        done++;
        progress.textContent = `Loading muscles ${done}/${regionFiles.length}`;
        applyAppearance();
        renderActiveTab();
    }));
    progress.hidden = true;

    // Hook for automated checks; harmless for viewers.
    window.__atlas = { state, camera, orbit, setPose, openEntity, entities, tree, applyPose, applyAppearance, renderer, scene };
}

boot();
