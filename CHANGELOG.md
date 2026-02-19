# Changelog

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
