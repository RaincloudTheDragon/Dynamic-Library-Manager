## [v0.5.1] - 2026-09-04

### Fixes

- Remove Original: much faster on large scenes with many library-override hierarchies — remap via `user_map` subset owners; one-pass in-scene collection-instance set for ghost-armature GC (was O(n²)).

## [v0.5.0] - 2026-09-03

### Features

- Prop Migrator: migrate non-armature props (pair, copy attributes, NLA, constraints, relatives, retarget, Remove Original) separately from Character Migrator.
- Missing Library Propagation: external wizard stubs missing armature libraries (SSH on SMB), then Blender Continue rempaths; non-armature links stay for Atomic/FMT/search.
- Stub modes: Auto / Linux SSH / Native, plus explicit copy-file stubs with fingerprint-gated teardown; optional Windows `subst` for phantom drive letters.
- MigObjConst / MigObjRelatives: copy object constraints (names preserved for NLA), split object parenting, and path-parenting support; override armatures use Child Of when the parent is outside the asset hierarchy.
- MigNLA: copy unkeyed pose and object loc/rot/scale (partial keys respected); map/copy Blender 4.4+ action slots and cache duplicated `.rep` actions.
- RetargRelatives: collection-wide orig→rep object maps (nested collections, suffix stripping), modifier pointers, and world-motion-preserving reparent when scales differ.
- Remove Original: snapshot orig IDs and purge leftover orphans after deletion; remap leftover refs before delete.
- Tweak tools: ALS-safe bake on all tweak sets, not only MigFKRot.

### Changed

- Character Migrator panel: Situational Fixes and Tweak Tools collapse under CharMig.
- Linked Libraries Analysis UI/ops removed (path work lives in Missing Library Propagation).
- Missing Library Propagation: default stub mode is copy-file (safer on SMB); Auto/Linux SSH remain when symlinks are required.
- Renamed Symlink Propagation → Missing Library Propagation (operator id `dlm.symlink_propagation` unchanged).
- Search: match date-stamped archive basenames (`YYYY.MM.DD…_Name.blend`); do not auto-fill modern path when several hits exist (Pick hit).
- Release: draft notes come from CHANGELOG; default tag is `v{version}` from `blender_manifest.toml`.

### Fixes

- Remove Original: soft-unlink override hierarchies instead of `collections.remove`; target override asset root (not local staging collections); skip ghost GC for armatures inside in-scene collection instances; do not purge linked namesakes after a local orig is gone.
- Remove Original: strip `.rep` from replacement actions (PropMig too), including descendant shape-key actions; drop unused name collisions.
- MigObjRelatives: keep orig `matrix_parent_inverse` + `matrix_basis` on Child Of so override parenting survives playhead scrub.
- RetargRelatives: skip action rewrite when the same bone parents both armatures; preserve `parent_type` / `parent_bone` / inverse / basis; shift Bezier handles with value deltas.
- Missing Library Propagation: persist AssetArchive rempaths after apply; rewrite stored paths even when stubs already resolve; include `*_baked` missing libs; prune empty stub parent dirs; prevent SMB unlink/copy from moving AssetArchive moderns; require Windows-visible SSH stubs; gate Remap to in-scope pairs; initialize rows before subst auto-detect; center wizard/dialogs after map on Windows.
- POSIX map discovery: prefer existing files, still record UNC samples when archaic libs are missing.

## [v0.4.2] - 2026-08-18

### Fixes

- MigFKRot bake: write to a dedicated top REPLACE `FK_Bake_*` layer/action instead of the active ALS action.
- MigNLA / MigFKRot: select the topmost Animation Layers track so the NLA stack evaluates.

## [v0.4.1] - 2026-08-18

### Fixes

- RetargRelatives: do not rewrite orig's own Rigify bone constraints (stops orig snapping to rep); remap constraint/DOF/driver IDs on other owners.
- Remove Original: remap leftover orig→rep refs, drop unused override armatures, and purge orig's unused linked libraries.

## [v0.4.0] - 2026-03-25

### Features

- CharMig: ARP (Auto-Rig Pro) support alongside Rigify (rig-family selector and related migrator behavior).
- MigBBody shapekeys: include manually specified meshes in migration, not only auto-detected base body.

### Changed

- MigNLA: activate the replacement character before turning on Animation Layers, so AnimLayers apply without manually selecting rep first.

### Fixes

- Remove Original: when resolving which collection to delete, never remove a collection whose subtree still contains the replacement armature (avoids deleting both orig and rep when they share hierarchy); Blender 5 collection parent checks use collection names.

## [v0.3.0] - 2026-03-13

### Features

- Camera DOF focus_object retargeting in RetargRelations.
- Bone constraint retargeting for ALL armatures (other characters, props).
- New "Body" tweak mode: spine/torso tweaks without arm/leg.
- "Add All" tweaks now includes body, spine, and MCH tweaks.

### Changed

- Constraint retargeting now works on all objects (including orig hierarchy eyes).
- Tweak UI: renamed "Both" to "All", added "Body" row.

### Fixes

- Blender 5.0 bone selection API compatibility (pose_bone.select).

## [v0.2.0] - 2026-03-10

### Features

- New "Remove Original" operator with collection deletion and action management (purge/cleanup).
- FK rotation migration improvements: baking support, single-frame copy, armature parent replication in RetargRelatives.

### Changed

- UI improvements: Tweak Tools section is now collapsible; reorganized into Situational Fixes section.
- Removed "Run Migration" button (functionality merged into Remove Original workflow).

### Fixes

- MigFKRot: fixed error printing and improved bone matching reliability.

## [v0.1.2] - 2026-02-19

### Features

- MigFKRot operator: copy FK arm and finger rotations from original to replacement using pose matrix copy.

### Changed

- MigNLA: duplicate actions when copying to repchar so editing on repchar doesn't affect origchar.
- MigFKRot: expanded bone name pattern matching for various rig styles (Rigify and alternatives).
- MigBBody shapekeys: also duplicate shape key actions for independence.

### Fixes

- MigFKRot: add debug logging to show which bones are found and copied.

## [v0.1.1] - 2026-02-19

### Fixes

- MigBBody shapekeys: action slot not applying; now copy action and slot props (last_slot_identifier, action_slot, blend/extrapolation/influence) from original base body.
- RetargRelations: skip objects in Original Character's hierarchy (linked collection); only retarget relations outside orig's hierarchy.
- MigBoneConst: copy all constraint properties and targets (RNA POINTER/COLLECTION with orig→rep retarget), not just type/name/mute/influence.
- AnimLayers: detect/mirror via RNA (obj.als.turn_on) so "Animation Layer attributes migrated" reports correctly.
- MigCustProps: recursive id-property copy for nested groups; debug logging for armature/bone keys.

## [v0.1.0] - 2026-02-19

### Features

- Gitea release workflow and runner docker-compose.
- Tweak tools subsection: add/remove/bake constraints for arms, legs, and both; track name and post-clean options.
- MigNLA: when no NLA, copy active action and action slot (incl. last_slot_identifier, blend/extrapolation/influence); debug logging for slot migration.
- NLAMig: AnimLayers support (mirror `als.turn_on`), strip timing and properties; active-action-only path when no NLA tracks.
- Operator icons (CopyAttr, MigNLA, CustProps, BoneConst, RetargRelatives, MigBBodyShapeKeys, pickers, tweak ops).
- BaseBody shapekeys step: prefer original base body's shape-key action slot; library override + editable; copy shape key values.

### Changed

- Operator labels refactored to canonical short names (CopyAttr, MigNLA, MigCustProps, etc.) with `bl_description` on all UI operators.
- Migrate BaseBody shapekeys redefined: find base body in hierarchy, override mesh/key data when linked, then apply shape-key action.
- Button labels truncated (e.g. "NLA", "BaseBody ShapeKeys").

### Fixes

- BaseBody shapekeys: lib override creation and value copy; correct original-base-body lookup and slot assignment.
