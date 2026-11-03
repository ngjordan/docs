#!/usr/bin/env python3
"""Generate apps/ios/IridiumDocs.xcodeproj (project.pbxproj) from scratch.

An .xcodeproj is a plist-ish file with a specific structure. Writing it by
hand is error-prone; generating it keeps the build settings honest and lets
the project be regenerated after a rename.

Usage: python3 make_xcodeproj.py [project_dir]
"""

import pathlib
import sys
import uuid

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "apps/ios")
PROJ = ROOT / "IridiumDocs.xcodeproj"
BUNDLE_ID = "ph.iridium.docs"
TEAM_ID = "5JY6QC2345"
DEPLOYMENT_TARGET = "16.0"
MARKETING_VERSION = "0.1.0"
BUILD_VERSION = "1"
SWIFT_VERSION = "5.0"

# Xcode object ids are 24 hex characters (96 bits). uuid5 gives 32, so take the
# first 24 - stable across runs, so regenerating produces no spurious diff.
def oid(name: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"iridium-docs:{name}").hex.upper()[:24]


FILE_REFS = [
    ("IridiumDocsApp.swift", "IridiumDocs"),
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

# ---- groups
for g in GROUPS:
    kids = ",\n".join(
        f"\t\t\t\t{oid(f'fileref:{f}')} /* {f} */" for f, _ in FILE_REFS if _ == g)
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

obj("PBXResourcesBuildPhase", oid("phase:resources"), """{
\t\t\tisa = PBXResourcesBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t}""")

obj("PBXFrameworksBuildPhase", oid("phase:frameworks"), """{
\t\t\tisa = PBXFrameworksBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t}""")

# ---- build configurations
common = f"""PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE_ID};
\t\t\tDEVELOPMENT_TEAM = {TEAM_ID};
\t\t\tSWIFT_VERSION = {SWIFT_VERSION};
\t\t\tIPHONEOS_DEPLOYMENT_TARGET = {DEPLOYMENT_TARGET};
\t\t\tMARKETING_VERSION = {MARKETING_VERSION};
\t\t\tCURRENT_PROJECT_VERSION = {BUILD_VERSION};
\t\t\tTARGETED_DEVICE_FAMILY = "1,2";
\t\t\tSDKROOT = iphoneos;
\t\t\tCODE_SIGN_STYLE = Automatic;
\t\t\tENABLE_PREVIEWS = YES;
\t\t\tSWIFT_EMIT_LOC_STRINGS = YES;"""

obj("XCBuildConfiguration", oid("config:debug:target"), f"""{{
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {{
\t\t\t\t{common}
\t\t\t\tINFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;
\t\t\t\tINFOPLIST_KEY_UILaunchScreen_Generation = YES;
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

print(f"wrote {PROJ}")
print(f"  project.pbxproj  ({len(objects)} objects)")
print(f"  xcshareddata/xcschemes/IridiumDocs.xcscheme")
print(f"  bundle id {BUNDLE_ID}, team {TEAM_ID}, iOS {DEPLOYMENT_TARGET}+")
