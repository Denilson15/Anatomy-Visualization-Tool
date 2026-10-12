# PT Anatomy Atlas

Interactive full-body 3D study tool for PT students. Pick a region (head and neck,
trunk, upper limb, lower limb) and an area inside it; the joint sliders, movements,
nerves and quiz all narrow to what you picked.

- 251 bones, 213 muscles, 332 marked attachment patches, 117 nerve paths
- 17 joint controls from the neck to the ankle, with muscles bending on the GPU
- Written notes for every muscle (origin, insertion, nerve, roots, actions), sorted
  into 53 functional groups (for example the abdomen splits into anterolateral wall,
  posterior wall and pelvic floor)
- 77 movements with prime movers and assistants, 47 nerves with roots, branches
  and injury signs, and a 39-term glossary
- 36 joints, each with its type, close-packed position, resting position and
  capsular pattern, and 159 ligament notes (attachments, job, when taut, clinical
  note) covering all 236 joint structures in the atlas: ligaments, capsules, discs,
  labra, menisci and membranes. Ligaments whose taut position depends on a rigged
  joint change colour live as the sliders move. A few craniovertebral ligaments that
  the atlas does not model (alar, transverse, tectorial) have notes only.

All anatomy content is a **draft** and must be checked against the course textbook
and approved by a reviewer before it is treated as correct. The atlas's own nerve
tags are not used. Its attachment patches are kept only where they match the
written notes; see `notes/attachment-report.md`.

## Folders

```
app/                   the app (source)
    index.html         page and styles
    app.js             all app logic
    anatomy.json       generated from notes/ by build_content.py
    attachments.json   generated: which atlas patches are each muscle's origin and insertion
    body.json          generated: rig, controls, region tree, muscle metadata
    *.bin              generated: packed mesh data (skeleton, then one file per region)
notes/                 the written notes (edit these)
    upper-limb.json, lower-limb.json, trunk.json, head-neck.json
                       groups and muscles per region
    movements.json     movements: prime movers, assistants, notes
    nerves.json        nerves: roots, parent, injury signs
    ligaments-upper-limb.json, ligaments-lower-limb.json,
    ligaments-trunk.json, ligaments-head-neck.json
                       joints and their ligaments per region
    base.json          meta, attachment sites, glossary
    attachment-report.md  which atlas patches were kept, relabelled or dropped
dist/                  what gets published (app.js inlined, meshes as base64 .txt)
tools/
    build_content.py   merges notes/ into app/anatomy.json and checks them
    export_body.py     pulls bones, muscles, patches, nerves, landmarks from Z-Anatomy
    prep_body.py       decimates meshes, builds the rig, skin weights and region files
    build.py           makes dist/ from app/
    smoke_body.py      headless browser test that screenshots each mode
    debug_page.py      runs JavaScript against the app in a headless browser
```

## Run it locally

```
python3 tools/build_content.py .
python3 tools/build.py app dist
cd dist
python3 -m http.server 8000
```

Then open http://localhost:8000.

## Put it on GitHub Pages

The live site is in `docs/`. In the repo open Settings → Pages, choose
"Deploy from a branch", pick `main` and `/docs`, and save. The site appears at
`https://<username>.github.io/<repo>/` a minute or two later.

After editing notes, rebuild straight into it:

```
python3 tools/build_content.py .
python3 tools/build.py app docs
```

`build.py` writes a complete standalone page by default; `--artifact` leaves out
the document wrapper for the Claude artifact host.

## Rebuild the 3D data

```
pip install bpy numpy scipy pyfqmr
git clone --depth 1 https://github.com/Z-Anatomy/Models-of-human-anatomy
unzip Models-of-human-anatomy/Z-Anatomy.zip -d zanat

python tools/export_body.py zanat/Z-Anatomy/Startup.blend export
python tools/prep_body.py export/raw_body.json app   # reads notes/ligaments-*.json to place ligaments
python tools/build.py app dist
```

## Editing the notes

Edit the files in `notes/`, then run `python3 tools/build_content.py .`. It fails
if a muscle has no notes, a group or nerve is unknown, a movement lists a muscle
whose actions disagree, or an atlas joint structure has no ligament notes.

Ligament `taut` rules are lists of `{"control": <slider id>, "points": [[angle,
tension], ...]}` with tension from 0 (slack) to 1 (taut); the app shows the highest
value among the rules. Joint `views` give the camera direction with +x toward the
body's right side. `originBones` and `insertionBones` are keywords used to
check the atlas patches against the notes.

## Licence and credit

3D models: Z-Anatomy (CC BY-SA 4.0), derived from BodyParts3D, The Database Center
for Life Science (CC BY-SA 2.1 Japan). Because of the share-alike terms, anything
that redistributes these models must use the same licence.
