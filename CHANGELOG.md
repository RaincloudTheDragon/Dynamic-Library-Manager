# Changelog

## [0.1.1] - 2026-02-19

### Fixed
- MigBBody shapekeys: action slot not applying; now copy action and slot props (last_slot_identifier, action_slot, blend/extrapolation/influence) from original base body.
- RetargRelations: skip objects in Original Character’s hierarchy (linked collection); only retarget relations outside orig’s hierarchy.
- MigBoneConst: copy all constraint properties and targets (RNA POINTER/COLLECTION with orig→rep retarget), not just type/name/mute/influence.
- AnimLayers: detect/mirror via RNA (obj.als.turn_on) so “Animation Layer attributes migrated” reports correctly.
- MigCustProps: recursive id-property copy for nested groups; debug logging for armature/bone keys.

## [0.1.0] - 2026-02-19

### Added
- Gitea release workflow and runner docker-compose.
- Tweak tools subsection: add/remove/bake constraints for arms, legs, and both; track name and post-clean options.
- MigNLA: when no NLA, copy active action and action slot (incl. last_slot_identifier, blend/extrapolation/influence); debug logging for slot migration.
- NLAMig: AnimLayers support (mirror `als.turn_on`), strip timing and properties; active-action-only path when no NLA tracks.
- Operator icons (CopyAttr, MigNLA, CustProps, BoneConst, RetargRelatives, MigBBodyShapeKeys, pickers, tweak ops).
- BaseBody shapekeys step: prefer original base body’s shape-key action slot; library override + editable; copy shape key values.

### Changed
- Operator labels refactored to canonical short names (CopyAttr, MigNLA, MigCustProps, etc.) with `bl_description` on all UI operators.
- Migrate BaseBody shapekeys redefined: find base body in hierarchy, override mesh/key data when linked, then apply shape-key action.
- Button labels truncated (e.g. “NLA”, “BaseBody ShapeKeys”).

### Fixed
- BaseBody shapekeys: lib override creation and value copy; correct original-base-body lookup and slot assignment.
