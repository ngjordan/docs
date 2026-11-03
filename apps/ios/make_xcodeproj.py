#!/usr/bin/env python3
"""Generate apps/ios/IridiumDocs.xcodeproj (project.pbxproj) from scratch.

An .xcodeproj is a plist-ish file with a specific structure. Writing it by
hand is error-prone; generating it keeps the build settings honest and lets
the project be regenerated after a rename.

Usage: python3 make_xcodeproj.py [project_dir]
"""

import json
import pathlib
import re
import subprocess
import sys
import uuid

from PIL import Image

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "apps/ios")
PROJ = ROOT / "IridiumDocs.xcodeproj"
BUNDLE_ID = "ph.iridium.docs"
TEAM_ID = "5JY6QC2345"
# The oldest iOS we support. Apple's SDK requirement is about the SDK a build
# is compiled against, not this: Xcode 26 + the iOS 26 SDK can still deploy to
# iOS 16. Raising this would needlessly drop devices.
DEPLOYMENT_TARGET = "16.0"
MARKETING_VERSION = "0.1.0"
BUILD_VERSION = "1"
SWIFT_VERSION = "5.0"

# ---- the iOS app icon set
#
# iOS rejects an app icon that carries an alpha channel, and it applies its own
# rounded-rect mask. So the iOS icons are full-bleed squares on an opaque
# background, rendered from the shared SVG with the corner radius removed.
REPO = ROOT.parent.parent   # ROOT is apps/ios, so the repo root is two up
ICON_SVG = REPO / "assets" / "app-icon" / "wordcraft.svg"
ICON_SET = ROOT / "IridiumDocs" / "Assets.xcassets" / "AppIcon.appiconset"

# (idiom, points, scale)
IOS_ICON_SPECS = [
    ("iphone", 60, 2), ("iphone", 60, 3),
    ("iphone", 120, 2), ("iphone", 120, 3),
    ("ipad", 20, 1), ("ipad", 20, 2),
    ("ipad", 29, 1), ("ipad", 29, 2),
    ("ipad", 40, 1), ("ipad", 40, 2),
    ("ipad", 76, 1), ("ipad", 76, 2),
    ("ipad", 83.5, 2),
    ("ios-marketing", 1024, 1),
]


def build_ios_icons():
    """Render the icon set into the asset catalog. Returns the Contents.json
    images list."""
    if not ICON_SVG.exists():
        return None
    svg = ICON_SVG.read_text(encoding="utf-8")
    # Drop the rounded-corner rect: iOS masks the icon itself.
    flat = re.sub(r'<rect[^>]*rx="[^"]*"[^>]*/>', '<rect width="512" height="512" fill="#0B6E4F"/>', svg, count=1)
    flat_path = ROOT / ".icon-flat.svg"
    flat_path.write_text(flat, encoding="utf-8")
    try:
        ICON_SET.mkdir(parents=True, exist_ok=True)
        images = []
        for idiom, points, scale in IOS_ICON_SPECS:
            px = int(round(points * scale))
            # Name the file after the slot, not just the pixel size: two slots
            # can share a pixel size (ipad 20x20 @2x and ipad 40x40 @1x are
            # both 40x40), and a file shared by two slots is asking for an
            # "invalid icon" rejection.
            slot = f"{idiom}-{str(points).replace('.', '_')}x{scale}"
            name = f"Icon-{slot}-{px}x{px}.png"
            out = ICON_SET / name
            subprocess.run(
                ["resvg", "-w", str(px), "-h", str(px), str(flat_path), str(out)],
                check=True)
            # Flatten onto an opaque background: resvg writes RGBA, and iOS
            # rejects an icon with an alpha channel.
            subprocess.run(
                ["python3", "-c",
                 "from PIL import Image; import sys\n"
                 "im = Image.open(sys.argv[1]).convert('RGBA')\n"
                 "bg = Image.new('RGB', im.size, '#0B6E4F')\n"
                 "bg.paste(im, mask=im.split()[-1])\n"
                 "bg.save(sys.argv[1])",
                 str(out)],
                check=True)
            size = f"{int(points)}x{int(points)}" if points == int(points) else f"{points}x{points}"
            images.append({"filename": name, "idiom": idiom,
                           "scale": f"{scale}x", "size": size})
        (ICON_SET / "Contents.json").write_text(
            json.dumps({"images": images,
                        "info": {"author": "xcode", "version": 1}},
                       indent=2) + "\n", encoding="utf-8")
        return images
    finally:
        flat_path.unlink(missing_ok=True)


# Xcode object ids are 24 hex characters (96 bits). uuid5 gives 32, so take the
# first 24 - stable across runs, so regenerating produces no spurious diff.
def oid(name: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"iridium-docs:{name}").hex.upper()[:24]


FILE_REFS = [
    ("IridiumDocsApp.swift", "IridiumDocs"),
]
# Resources: the asset catalog carries the app icon. Xcode needs a file
# reference for it, otherwise it is never compiled into Assets.car and
# App Store Connect rejects the build with "Missing required icon file".
RESOURCE_REFS = [
    ("Assets.xcassets", "IridiumDocs", "folder.assetcatalog"),
]
GROUPS = ["IridiumDocs"]

objects = []


def obj(cls, ident, body):
    objects.append((cls, ident, body))


# ---- file references and build files
for fname, group in FILE_REFS:
    obj("PBXFileReference", oid(f"fileref:{fname}"), f"""{{
\t\t\tisa = PBXFileReference;
\t\t\tlastKnownFileType = sourcecode.swift;
\t\t\tpath = {fname};
\t\t\tsourceTree = "<group>";
\t\t}}""")
    obj("PBXBuildFile", oid(f"buildfile:{fname}"), f"""{{
\t\t\tisa = PBXBuildFile;
\t\t\tfileRef = {oid(f"fileref:{fname}")} /* {fname} */;
\t\t}}""")

# ---- resource file references and build files
for fname, group, ftype in RESOURCE_REFS:
    obj("PBXFileReference", oid(f"fileref:{fname}"), f"""{{
\t\t\tisa = PBXFileReference;
\t\t\tlastKnownFileType = {ftype};
\t\t\tpath = {fname};
\t\t\tsourceTree = "<group>";
\t\t}}""")
    obj("PBXBuildFile", oid(f"buildfile:{fname}"), f"""{{
\t\t\tisa = PBXBuildFile;
\t\t\tfileRef = {oid(f"fileref:{fname}")} /* {fname} */;
\t\t}}""")

# ---- groups
for g in GROUPS:
    kid_files = [f for f, _ in FILE_REFS if _ == g]
    # RESOURCE_REFS entries are (name, group, filetype): the group is the
    # second field. Unpacking as (f, _, _) would bind _ to the filetype.
    kid_files += [f for f, grp, _ft in RESOURCE_REFS if grp == g]
    kids = ",\n".join(
        f"\t\t\t\t{oid(f'fileref:{f}')} /* {f} */" for f in kid_files)
    obj("PBXGroup", oid(f"group:{g}"), f"""{{
\t\t\tisa = PBXGroup;
\t\t\tchildren = (
{kids},
\t\t\t);
\t\t\tpath = {g};
\t\t\tsourceTree = "<group>";
\t\t}}""")

obj("PBXGroup", oid("group:root"), """{
\t\t\tisa = PBXGroup;
\t\t\tchildren = (
\t\t\t\t""" + oid("group:IridiumDocs") + """ /* IridiumDocs */,
\t\t\t\t""" + oid("group:Products") + """ /* Products */,
\t\t\t);
\t\t\tsourceTree = "<group>";
\t\t}""")

obj("PBXFileReference", oid("fileref:app"), """{
\t\t\tisa = PBXFileReference;
\t\t\texplicitFileType = wrapper.application;
\t\t\tincludeInIndex = 0;
\t\t\tpath = IridiumDocs.app;
\t\t\tsourceTree = BUILT_PRODUCTS_DIR;
\t\t}""")
obj("PBXGroup", oid("group:Products"), """{
\t\t\tisa = PBXGroup;
\t\t\tchildren = (
\t\t\t\t""" + oid("fileref:app") + """ /* IridiumDocs.app */,
\t\t\t);
\t\t\tname = Products;
\t\t\tsourceTree = "<group>";
\t\t}""")

# ---- build phases
sources = ",\n".join(f"\t\t\t\t{oid(f'buildfile:{f}')} /* {f} in Sources */"
                      for f, _ in FILE_REFS)
obj("PBXSourcesBuildPhase", oid("phase:sources"), f"""{{
\t\t\tisa = PBXSourcesBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
{sources},
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t}}""")

resources = ",\n".join(f"\t\t\t\t{oid(f'buildfile:{f}')} /* {f} in Resources */"
                        for f, _, _ in RESOURCE_REFS)
obj("PBXResourcesBuildPhase", oid("phase:resources"), f"""{{
\t\t\tisa = PBXResourcesBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
{resources},
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t}}""")

obj("PBXFrameworksBuildPhase", oid("phase:frameworks"), """{
\t\t\tisa = PBXFrameworksBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t}""")

# ---- build configurations
common = f"""PRODUCT_NAME = IridiumDocs;
\t\t\tPRODUCT_BUNDLE_IDENTIFIER = {BUNDLE_ID};
\t\t\tDEVELOPMENT_TEAM = {TEAM_ID};
\t\t\tSWIFT_VERSION = {SWIFT_VERSION};
\t\t\tIPHONEOS_DEPLOYMENT_TARGET = {DEPLOYMENT_TARGET};
\t\t\tMARKETING_VERSION = {MARKETING_VERSION};
\t\t\tCURRENT_PROJECT_VERSION = {BUILD_VERSION};
\t\t\tTARGETED_DEVICE_FAMILY = "1,2";
\t\t\tSDKROOT = iphoneos;
\t\t\tCODE_SIGN_STYLE = Automatic;
			GENERATE_INFOPLIST_FILE = YES;
\t\t\tENABLE_PREVIEWS = YES;
\t\t\tSWIFT_EMIT_LOC_STRINGS = YES;"""

obj("XCBuildConfiguration", oid("config:debug:target"), f"""{{
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {{
\t\t\t\t{common}
\t\t\t\tINFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;
\t\t\t\tINFOPLIST_KEY_UILaunchScreen_Generation = YES;
				INFOPLIST_KEY_CFBundleDisplayName = "Iridium Docs";
\t\t\t\tASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
\t\t\t\tINFOPLIST_KEY_CFBundleIconName = AppIcon;
\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPad = "UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";
\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";
\t\t\t}};
\t\t\tname = Debug;
\t\t}}""")

obj("XCBuildConfiguration", oid("config:release:target"), f"""{{
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {{
\t\t\t\t{common}
\t\t\t\tINFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;
\t\t\t\tINFOPLIST_KEY_UILaunchScreen_Generation = YES;
				INFOPLIST_KEY_CFBundleDisplayName = "Iridium Docs";
\t\t\t\tASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
\t\t\t\tINFOPLIST_KEY_CFBundleIconName = AppIcon;
\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPad = "UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";
\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";
\t\t\t}};
\t\t\tname = Release;
\t\t}}""")

project_debug = """{
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {
\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;
\t\t\t\tCLANG_ENABLE_MODULES = YES;
\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "-Onone";
\t\t\t\tSWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG;
\t\t\t\tENABLE_TESTABILITY = YES;
\t\t\t\tONLY_ACTIVE_ARCH = YES;
\t\t\t\tGCC_OPTIMIZATION_LEVEL = 0;
\t\t\t};
\t\t\tname = Debug;
\t\t}"""

project_release = """{
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {
\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;
\t\t\t\tCLANG_ENABLE_MODULES = YES;
\t\t\t\tSWIFT_COMPILATION_MODE = wholemodule;
\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "-O";
\t\t\t\tVALIDATE_PRODUCT = YES;
\t\t\t};
\t\t\tname = Release;
\t\t}"""

obj("XCBuildConfiguration", oid("config:debug:project"), project_debug)
obj("XCBuildConfiguration", oid("config:release:project"), project_release)

obj("XCConfigurationList", oid("configlist:project"), f"""{{
\t\t\tisa = XCConfigurationList;
\t\t\tbuildConfigurations = (
\t\t\t\t{oid('config:debug:project')} /* Debug */,
\t\t\t\t{oid('config:release:project')} /* Release */,
\t\t\t);
\t\t\tdefaultConfigurationIsVisible = 0;
\t\t\tdefaultConfigurationName = Release;
\t\t}}""")

obj("XCConfigurationList", oid("configlist:target"), f"""{{
\t\t\tisa = XCConfigurationList;
\t\t\tbuildConfigurations = (
\t\t\t\t{oid('config:debug:target')} /* Debug */,
\t\t\t\t{oid('config:release:target')} /* Release */,
\t\t\t);
\t\t\tdefaultConfigurationIsVisible = 0;
\t\t\tdefaultConfigurationName = Release;
\t\t}}""")

# ---- target and project
obj("PBXNativeTarget", oid("target"), f"""{{
\t\t\tisa = PBXNativeTarget;
\t\t\tbuildConfigurationList = {oid('configlist:target')} /* Build configuration list */;
\t\t\tbuildPhases = (
\t\t\t\t{oid('phase:sources')} /* Sources */,
\t\t\t\t{oid('phase:frameworks')} /* Frameworks */,
\t\t\t\t{oid('phase:resources')} /* Resources */,
\t\t\t);
\t\t\tbuildRules = (
\t\t\t);
\t\t\tdependencies = (
\t\t\t);
\t\t\tname = IridiumDocs;
\t\t\tproductName = IridiumDocs;
\t\t\tproductReference = {oid('fileref:app')} /* IridiumDocs.app */;
\t\t\tproductType = "com.apple.product-type.application";
\t\t}}""")

obj("PBXProject", oid("project"), f"""{{
\t\t\tisa = PBXProject;
\t\t\tattributes = {{
\t\t\t\tBuildIndependentTargetsInParallel = 1;
\t\t\t\tLastSwiftUpdateCheck = 1500;
\t\t\t\tLastUpgradeCheck = 1500;
\t\t\t\tTargetAttributes = {{
\t\t\t\t\t{oid('target')} = {{
\t\t\t\t\t\tCreatedOnToolsVersion = 15.4;
\t\t\t\t\t}};
\t\t\t\t}};
\t\t\t}};
\t\t\tbuildConfigurationList = {oid('configlist:project')} /* Build configuration list */;
\t\t\tcompatibilityVersion = "Xcode 14.0";
\t\t\tdevelopmentRegion = en;
\t\t\thasScannedForEncodings = 0;
\t\t\tknownRegions = (
\t\t\t\ten,
\t\t\t\tBase,
\t\t\t);
\t\t\tmainGroup = {oid('group:root')};
\t\t\tproductRefGroup = {oid('group:Products')} /* Products */;
\t\t\tprojectDirPath = "";
\t\t\tprojectRoot = "";
\t\t\ttargets = (
\t\t\t\t{oid('target')} /* IridiumDocs */,
\t\t\t);
\t\t}}""")

body = "\n".join(f"\t\t{ident} = {content};" for _, ident, content in objects)

pbx = f"""// !$*UTF8*$!
{{
\tarchiveVersion = 1;
\tclasses = {{
\t}};
\tobjectVersion = 56;
\tobjects = {{
{body}
\t}};
\trootObject = {oid('project')} /* Project object */;
}}
"""

# Regenerate the icon set before writing the project, so the catalog and the
# project always agree.
build_ios_icons()

PROJ.mkdir(parents=True, exist_ok=True)
(PROJ / "project.pbxproj").write_text(pbx, encoding="utf-8")



# The shared scheme, so xcodebuild -scheme finds it.
scheme_dir = PROJ / "xcshareddata" / "xcschemes"
scheme_dir.mkdir(parents=True, exist_ok=True)
(scheme_dir / "IridiumDocs.xcscheme").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion = "1500" version = "1.7">
   <BuildAction parallelizeBuildables = "YES" buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting = "YES" buildForRunning = "YES" buildForProfiling = "YES" buildForArchiving = "YES" buildForAnalyzing = "YES">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "{oid('target')}"
               BuildableName = "IridiumDocs.app"
               BlueprintName = "IridiumDocs"
               ReferencedContainer = "container:IridiumDocs.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv = "YES">
      <Testables>
      </Testables>
   </TestAction>
   <LaunchAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle = "0" useCustomWorkingDirectory = "NO" ignoresPersistentStateOnLaunch = "NO" debugDocumentVersioning = "YES" debugServiceExtension = "internal" allowLocationSimulation = "YES">
      <BuildableProductRunnable runnableDebuggingMode = "0">
         <BuildableReference
            BuildableIdentifier = "primary"
            BlueprintIdentifier = "{oid('target')}"
            BuildableName = "IridiumDocs.app"
            BlueprintName = "IridiumDocs"
            ReferencedContainer = "container:IridiumDocs.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </LaunchAction>
   <ProfileAction buildConfiguration = "Release" shouldUseLaunchSchemeArgsEnv = "YES" savedToolIdentifier = "" useCustomWorkingDirectory = "NO" debugDocumentVersioning = "YES">
   </ProfileAction>
   <AnalyzeAction buildConfiguration = "Debug">
   </AnalyzeAction>
   <ArchiveAction buildConfiguration = "Release" revealArchiveInOrganizer = "YES">
   </ArchiveAction>
</Scheme>
""", encoding="utf-8")

# Self-check: the pbxproj is an OpenStep plist and xcodebuild refuses to open a
# project that does not parse ("the project is damaged and cannot be opened
# due to a parse error"). Parse it here so a bad build setting is caught now,
# not three CI minutes later. The usual cause is an unquoted value containing a
# space - `FOO = Bar Baz;` is invalid; it must be `FOO = "Bar Baz";`.
try:
    import openstep_parser
    openstep_parser.OpenStepDecoder.ParseFromString(
        (PROJ / "project.pbxproj").read_text())
except ImportError:
    print("note: openstep_parser is not installed; skipped the parse check")
except Exception as exc:  # noqa: BLE001
    sys.exit(f"error: the generated project.pbxproj does not parse: {exc}")
else:
    print("parse check: OK")

print(f"wrote {PROJ}")
print(f"  project.pbxproj  ({len(objects)} objects)")
print(f"  xcshareddata/xcschemes/IridiumDocs.xcscheme")
print(f"  bundle id {BUNDLE_ID}, team {TEAM_ID}, iOS {DEPLOYMENT_TARGET}+")

# Self-check: every resource must be a child of its group AND in the resources
# build phase. A file reference that is not a child of any group resolves
# against SOURCE_ROOT instead, so actool gets the wrong path and Xcode
# reports "None of the input catalogs contained a matching ... app icon set".
_generated = (PROJ / "project.pbxproj").read_text(encoding="utf-8")
for _name, _grp, _ft in RESOURCE_REFS:
    assert _name in _generated, f"{_name} missing from the generated project"
    # A group child appears as "<id> /* name */," and a build file as
    # "<id> /* name in Resources */,".
    assert f"/* {_name} */," in _generated, (
        f"{_name} is not a child of its group")
    assert f"/* {_name} in Resources */," in _generated, (
        f"{_name} is not in the resources build phase")
print("self-check: every resource is a group child and in the resources phase")

# iOS rejects an icon with an alpha channel, and a transparent corner is the
# usual cause. Catch it here rather than at upload time.
_icon_bad = []
_seen = {}
for _png in sorted(ICON_SET.glob("*.png")):
    _mode = Image.open(_png).mode
    if _mode not in ("RGB", "L"):
        _icon_bad.append(f"{_png.name} is {_mode}")
    _seen.setdefault(_png.name, []).append(_png)
# Every declared slot must point at its own file.
_declared = json.loads((ICON_SET / "Contents.json").read_text())
_names = [i["filename"] for i in _declared["images"]]
if len(_names) != len(set(_names)):
    _icon_bad.append("two slots share one icon file")
if _icon_bad:
    raise SystemExit("iOS app icons must be opaque, no alpha channel:\n  "
                     + "\n  ".join(_icon_bad))
print(f"self-check: {len(list(ICON_SET.glob('*.png')))} app icons are opaque")

