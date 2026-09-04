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

* Blender **4.5.0** or newer (official support 4.5 LTS and 5.2 LTS)
* For Missing Library Propagation over a Linux-hosted SMB share: SSH access to the Linux host when using Linux SSH stub mode
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
3. Run the steps you need in order, typically:


   | Operator                          | What it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
   | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | CopyAttr                          | Copies the armature's object attributes from OrigChar to RepChar.`Copy Attributes Menu`<br />extension required.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
   | MigNLA                            | Migrates NLA tracks, action slots, unkeyed pose/object transforms. If an action is not in the NLA evaluation stack (pulled down) it will not be migrated<br />because DLM cannot (yet?) tell the difference between the active action slot and an action in tweak mode, so anything that's currently active is ignored. Keep in mind that RepChar's actions are not 1:1 with Orig's; they will be named `**.rep` until **Remove Original** is run.                                                                                                                                                                                                                                                     |
   | MigCustProps                      | Migrates each bone's Custom Properties override from Orig to Repchar, e.g. unkeyframed IK/FK switch value                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
   | MigObjConst                       | Migrates object constraints of the Armature Object itself (names kept for NLA)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
   | MigObjRelatives                   | Migrates Parenting of the Armature Object (Child Of when the parent is outside an override hierarchy)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
   | MigBoneConst                      | Migrates all Bone constraints. By this step, you should scrub through the animation to ensure that the two armatures match as much as possible. Look for Z-Fighting on superimposed geometry and bones; it's what you want because it indicates that RepChar is in perfect sync with OrigChar.                                                                                                                                                                                                                                                                                                                                                                                                            |
   | RetargRelatives                   | Scene-wide orig→rep relative tree (parents, constraints, modifiers, camera DOFm anything that points to the armature, rig objects, or bones). This step causes OrigChar to be bound to RepChar, so the Z-Fighting will lie to you on RepChar's behavior being being accurate, thus discrepancies must be noted in the step previous.                                                                                                                                                                                                                                                                                                                                                                    |
   | Situational: MigBBodyShapekeys    | For CC/iC characters. Migrates the shapekeys on OrigChar's`CC_Base_Body` object to that of RepChar. Library-override aware, keyframe/action aware.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
   | Situational: MigFKRot/Tweak Tools | Sometimes, OrigChar and RepChar have inherent discrepancies that can't be cleanly fixed with a simple action migration. These tools will create constraints on certain armature bones (mostly tweaks, but MigFKRot will do so for other bones on the Arm hierarchies) that bind them more closely. There is room for improvement here; sometimes the Rigify`head` bone could use a tweak tool as well. Either way, spawn the bone constrants, then bake them (they go to a new NLA layer by default). If preferred, you can opt not to bake them and keep OrigChar in the scene, but this is not recommended, given that the point is to have all the data modernized to functional, current libraries. |
   | Remove Original                   | Remaps leftover refs and deletes OrigChar and all library references. Removes`*.rep` from RepChar's action duplicates and purges all originals.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

There is no single “run everything” button for characters; steps are independent due to the inherent complexity of each animation and blendfile. CharMig has been designed to account for a great many situations, but it's still a deterministic procedure, so anything it doesn't account for could break things. Verify everything, use caution, and use version control to prevent any work loss.

### Prop Migrator

Same idea, but for a non-armature pair. Can be used to replace old props with new versions, or to replace one prop with an entirely different prop (cleanup likely required). **Migrate Prop** runs CopyAttr → MigNLA → MigCustProps → MigObjConst → MigObjRelatives → RetargRelatives. **Remove Original** is separate so you can verify if the replacement landed properly. The logic is a little different here; constraints and parent hierarchies have offsets that need to be set properly, so they may require scrubbing at least one frame in order to snap into place.

## License

GPL-3.0-or-later

## Links

- **Repository**: [github.com/RaincloudTheDragon/Dynamic-Library-Manager](https://github.com/RaincloudTheDragon/Dynamic-Library-Manager)
- **Issues**: [GitHub Issues](https://github.com/RaincloudTheDragon/Dynamic-Library-Manager/issues)
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)
