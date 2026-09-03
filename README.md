# Dynamic Library Manager

Character migrator and linked library tools for Blender. Swap a linked character or prop for a newer asset without rebuilding NLA, constraints, parenting, or scene references by hand — and restub missing armature libraries so pose data survives a rempath.

Officially supports Blender 4.5 LTS to 5.2 LTS.

## Features

- **Missing Library Propagation** — If libraries containing overridden armatures are not present on load, all their bone data (unkeyed pose data, all bone constraints, possibly some override data) is lost once relinked. This workflow helps the user find the modern paths of the missing blends, creates stubs of missing armature libraries (copy-file by default, SSH/native symlinks on SMB or local), then reload and remap in Blender. Non-armature links stay for Atomic Remap / FMT / External Data search.
- **Character Migrator** — This feature set allows you to migrate a fully animated character in a scene, with a replacement. You can choose a new version of the same character, or replace an entirely different character with another character. The possibilities are (close to) endless! Support Rigify (especially Character Creator rigs) and Auto Rig Pro* characters.
- **Prop Migrator** — The same pipeline for non-armature objects (meshes, empties, curves).
- **Situational fixes** — base body shape keys and FK arm/finger rotation copy (with bake). Designed for Character Creator rigs.
- **Tweak tools** — add / remove / bake arm, leg, body, or all tweak constraints on the replacement. Designed for Character Creator rigs.
- **Path helpers** — Simple shortcuts to make all file paths relative or absolute.

## Installation

1. Download the latest zip from [Releases](https://github.com/RaincloudTheDragon/Dynamic-Library-Manager/releases).
2. Drag and drop the zip into blender, or:

- **Edit → Preferences → Add-ons → Install from Disk** and pick the zip.
- Ensure **Dynamic Library Manager** is enabled.

## Prerequisites, Recommendations, & Interoperability

* [Copy Attributes Menu](https://extensions.blender.org/add-ons/copy-attributes-menu/): Blender official extension, originally bundled with Blender 4.1, now with limited support. Required for both migration workflows (it's the first step)
* [Atomic Data Manager](https://github.com/RaincloudTheDragon/atomic-data-manager): My fork of Atomic, highly recommended for missing library diagnosis, expidited relinking workflow and popups, and more. Not explicity required for any workflows in this addon.
* [CC/iC Tools](https://github.com/soupday/cc_blender_tools): Official workflow tools to port assets created in Reallusion's Character Creator and iClone to Blender. Not explicitly required, but DLM was designed off of these rigs and thus has several hardcoded operations for them. I'm hoping to expand the featureset to make it more accessible to Rigify rigs in general.
* [Auto-Rig Pro](https://superhivemarket.com/products/auto-rig-pro): Kit for automatic character rigging, action remapping, and more. Highly recommended, one of the GOATs of superhive. Character Migrator supports ARP rigs to a degree. More information below.
* [Animation Layers](https://superhivemarket.com/products/animation-layers): Another animation must-have. Character Migrator has custom support for characters and objects with active AnimLayers, but vanilla NLA actions work as well, so long as all relevant actions are pulled down.

## Usage

Open **3D Viewport → Sidebar (N) → Dynamic Library Manager**.

### Missing Library Propagation

This feature is designed for Armature libraries only; pose data is lost if those libraries are missing on load, as documented in [90924](https://projects.blender.org/blender/blender/issues/90924), [143902](https://projects.blender.org/blender/blender/issues/143902), and other official Blender issues. Pose data is not preserved if Armature data is lost or modified. That is to say, all pose data that isn't in an action (i.e. bones that have been posed without being keyframed, any bone constraints, possibly other data) is purged if 1. The Library containing the Armature is not found on load 2. The Library containing the Armature is relinked to a Library where the Armature's data has been modified.

The latter cause is irrelevant; Pose data doesn't need to be preserved in the case of modified Armature data. All it needs is to be preserved on load, so that relinking preserves relevant pose data.

It is theoretically possible that this limitation can be solved by keeping relevant pose data until the Libraries are relinked; only lose the Pose data when the relinked library has modified Armature data. However, with Blender's current logic, this feature is not simple; this issue cannot be fixed but for a deep refactor of how pose data and actual Armature ID (and its bones) are linked and handled in Blender. The developers of Blender's **Core** and **Rigging & Animation** modules are aware of this issue and would like to improve it, but it's not on any current development milestones. It will likely be years before this refactor takes place given that it's not a top priority in regards to feature scope. Perhaps it will make it into a Winter of Quality in 1-3 years, perhaps not. But in the meantime, a workaround is required.

This issue only affects armatures. Libraries that do not link armatures do not lose data in the same circumstance. Thus, any library that has no overridden armature in scene is out of scope. This means any library with overrides on non-armature objects, or any library that was not overridden and thus remains as an instance collection, even if it has an armature within it. Only when that armature has an override session and is missing will it be targeted by the Propagator.

In most cases, the Armature data hasn't been lost; the libraries are valid, only they can't be found on load. In order to load the blendfile as it was saved, the user must ensure that the valid files are in the _exact_ path as was saved in the blendfile. This involves either copying the blends to those exact locations, or reverting to the proper point in your versioning control tool if relevant (and only if relpaths are used). Using abspaths compounds the issue, particularly on Windows, which requires remapping drive letters and disconnecting network drives in order to get the paths valid. This workaround was so tedious that I did it agentically for a while, but then I realized it could be done deterministically without a terrible amount of headache, so I automated the process as follows.

1. Set **Default Search Roots** in addon preferences (semicolon-separated folders of modern `.blend` files).
2. Click **Missing Library Propagation**. The external wizard will open, you can search (or remove) your default paths, or add new ones to search. If they are found, click 'Create stubs'. If there are multiple hits on the target library, click 'Pick Hit' to choose which search result to use.
3. When stubs are ready, **Revert**, verify hits, then **Remap** (Remap does not auto-save).
4. Return to the wizard and teardown stubs when you are done.

There are many modes by which the stubs can be created, the default is a simple copy of all the binary hits. This is generally the safest mode over SMB. Auto / Linux SSH remain when you actually need symlinks to evaluate on linux via a Linux-hosted SMB share. Optional Windows `subst` covers phantom drive letters.

### Character Migrator

#### Definitions

* OrigChar: Original Character.
* RepChar: Replacement Character.

1. Pick **Rigify** or **ARP**. (Note that ARP rigs must reflect the expected outliner hierarchy, so support may be limited. I would love to expand this in future.)
2. Set **Original** and **Replacement** (eyedropper or automatic pair discovery).
3. Run the steps you need, typically:


   | Operator        | What it does                                                                                                                                                                                                                                                                                                                  |
   | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | CopyAttr        | Copies the armature's object attributes from OrigChar to RepChar.`Copy Attributes Menu`<br />extension required.                                                                                                                                                                                                              |
   | MigNLA          | Migrates NLA tracks, action slots, unkeyed pose/object transforms.<br />If an action is not in the NLA evaluation stack (pulled down) it will not be migrated<br />because DLM cannot (yet?) tell the difference between the active action slot and an action in tweak mode, so anything that's currently active is ignored. |
   | MigCustProps    | Migrates each bone's Custom Properties override from Orig to Repchar, e.g. unkeyframed IK/FK switch value                                                                                                                                                                                                                     |
   | MigObjConst     | Object constraints (names kept for NLA)                                                                                                                                                                                                                                                                                       |
   | MigObjRelatives | Parenting (Child Of when the parent is outside an override hierarchy)                                                                                                                                                                                                                                                         |
   | MigBoneConst    | Bone constraints                                                                                                                                                                                                                                                                                                              |
   | RetargRelatives | Scene-wide orig→rep pointers (parents, constraints, modifiers, camera DOF)                                                                                                                                                                                                                                                   |
   | Remove Original | Remap leftover refs and delete the original                                                                                                                                                                                                                                                                                   |
4. **Situational Fixes** when the rig needs them: **MigBBodyShapeKeys**, **MigFKRot** (then Bake / Remove).
5. **Tweak Tools** for post-migration pose offsets (arm / leg / body / all).

There is no single “run everything” button for characters — steps are independent so you can skip what the pair already has.

### Prop Migrator

Same idea for a non-armature pair. **Migrate Prop** runs CopyAttr → MigNLA → MigCustProps → MigObjConst → MigObjRelatives → RetargRelatives. **Remove Original** is separate.

## Requirements

- Blender **4.5.0** or newer (validated on 4.5 LTS and 5.2 LTS)
- For Missing Library Propagation over SMB: SSH access to the Linux host when using Linux SSH stub mode

## License

GPL-3.0-or-later

## Links

- **Repository**: [github.com/RaincloudTheDragon/Dynamic-Library-Manager](https://github.com/RaincloudTheDragon/Dynamic-Library-Manager)
- **Issues**: [GitHub Issues](https://github.com/RaincloudTheDragon/Dynamic-Library-Manager/issues)
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)
