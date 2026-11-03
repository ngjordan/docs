#!/usr/bin/env python3
"""Finish a TestFlight upload: declare export compliance and attach the build.

`xcodebuild -exportArchive` + `altool --upload-app` uploads the build, but
Apple then needs two things done before the build is testable:

  1. Export compliance declared. A build uploaded without it has
     `usesNonExemptEncryption = None`, and assigning it to a beta group
     fails with "Build is not in an externally assignable state".
  2. The build attached to a beta group. Apple's default "Team" group is
     internal (`isInternalGroup: true`) and only receives Apple's own
     automatic uploads; a manually uploaded build needs an external group.

Both are scriptable with the App Store Connect API key.

    python3 packaging/testflight.py                 # attach the newest build
    python3 packaging/testflight.py --build <id>    # attach a specific build
    python3 packaging/testflight.py --group "Name"  # create the group if needed
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import asc_client  # noqa: E402

APP_ID = "6830192857"          # Iridium Docs
DEFAULT_GROUP = "Iridium Docs Testers"


def api(path, method="GET", data=None):
    """asc_client.call() narrowed to a dict."""
    r = asc_client.call(path, method, data)
    if isinstance(r, str):
        sys.exit(f"unexpected response from {path}: {r[:300]}")
    return r


def find_group(name):
    for g in api(f"/v1/apps/{APP_ID}/betaGroups").get("data", []):
        if g["attributes"].get("name") == name:
            return g["id"]
    return None


def create_group(name):
    body = {"data": {"type": "betaGroups", "attributes": {
        "name": name, "publicLinkEnabled": False},
        "relationships": {"app": {"data": {"type": "apps", "id": APP_ID}}}}}
    r = api("/v1/betaGroups", "POST", body)
    if "__error" in r:
        sys.exit(f"could not create the beta group: {r.get('body', '')[:400]}")
    return r["data"]["id"]


def newest_build():
    builds = api(f"/v1/apps/{APP_ID}/builds").get("data", [])
    if not builds:
        sys.exit("no builds on the app")
    return builds[0]


def build_by_version(version):
    """Pick the build with this version number.

    The upload step knows the version it built; the newest build may be a
    different one while Apple is still processing.
    """
    for b in api(f"/v1/apps/{APP_ID}/builds").get("data", []):
        if str(b["attributes"].get("version")) == str(version):
            return b
    sys.exit(f"no build with version {version} on the app")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", help="build id; default: the newest")
    ap.add_argument("--version", help="pick the build with this version number")
    ap.add_argument("--group", default=DEFAULT_GROUP)
    ap.add_argument("--no-encryption", action="store_true", default=True,
                    help="declare that the build uses no non-exempt encryption")
    args = ap.parse_args()

    if args.build:
        build = api(f"/v1/builds/{args.build}")["data"]
    elif args.version:
        build = build_by_version(args.version)
    else:
        build = newest_build()
    build_id = build["id"]
    attrs = api(f"/v1/builds/{build_id}")["data"]["attributes"]
    print(f"build {build_id}: version {attrs.get('version')}, "
          f"state {attrs.get('processingState')}")

    if attrs.get("usesNonExemptEncryption") is None:
        body = {"data": {"type": "builds", "id": build_id,
                          "attributes": {"usesNonExemptEncryption": False}}}
        r = api(f"/v1/builds/{build_id}", "PATCH", body)
        if "__error" in r:
            sys.exit(f"could not declare export compliance: {r.get('body', '')[:400]}")
        print("  export compliance declared (usesNonExemptEncryption = False)")
    else:
        print(f"  export compliance already set ({attrs['usesNonExemptEncryption']})")

    gid = find_group(args.group)
    if gid is None:
        gid = create_group(args.group)
        print(f"  created the beta group {args.group!r}")
    else:
        print(f"  beta group {args.group!r}: {gid}")

    # The relationship uses CREATE, not REPLACE.
    body = {"data": [{"type": "builds", "id": build_id}]}
    r = api(f"/v1/betaGroups/{gid}/relationships/builds", "POST", body)
    if "__error" in r:
        # Already attached is not a failure.
        if "already" in r.get("body", "").lower():
            print("  already attached")
        else:
            sys.exit(f"could not attach the build: {r.get('body', '')[:400]}")
    else:
        print("  attached to the beta group")

    builds = api(f"/v1/betaGroups/{gid}/relationships/builds").get("data", [])
    print(f"  {args.group!r} now has {len(builds)} build(s)")


if __name__ == "__main__":
    main()
