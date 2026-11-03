#!/usr/bin/env python3
"""Finish the App Store Connect key setup: store the Issuer ID, verify the key
against Apple, and report what it can now do.

Usage:
    python3 asc_setup.py <ISSUER_ID>

The Issuer ID is the UUID shown at the top of
https://developer.apple.com/account/resources/integrations/api/
It is the same value Apple displays next to your Team Keys.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import asc_client  # noqa: E402

KEY_DIR = asc_client.KEY_DIR


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    issuer = sys.argv[1].strip()

    import uuid
    try:
        uuid.UUID(issuer)
    except ValueError:
        sys.exit(f"error: '{issuer}' is not a UUID. "
                 "The Issuer ID looks like 57246542-96fe-1a63-e053-0824d011072a.")

    (KEY_DIR / "issuer_id").write_text(issuer)
    (KEY_DIR / "issuer_id").chmod(0o600)

    print(f"issuer_id stored: {issuer}")
    print(f"key_id:           {(KEY_DIR/'key_id').read_text().strip()}")
    print()

    print("=== verifying against Apple ===")
    d = asc_client.call("/v1/users")
    if "__error" in d:
        print(f"AUTH FAILED: {d}")
        sys.exit(1)

    print("AUTHENTICATED. This key can act as:")
    for u in d.get("data", []):
        a = u.get("attributes", {})
        roles = a.get("roles", [])
        print(f"  user      {a.get('username')} ({a.get('firstName','')} {a.get('lastName','')})")
        print(f"  roles     {roles}")
        # Apple returns roles as plain strings: ["ACCOUNT_HOLDER", "ADMIN"].
        for r in roles:
            print(f"  role           {r}")
        print()

    # What the key's role can actually do, per Apple's matrix.
    ROLE_CAPS = {
        "ADMIN": ["create/revoke distribution certificates",
                  "create/delete distribution provisioning profiles",
                  "download provisioning profiles",
                  "register & configure App IDs", "add/disable UDIDs",
                  "notarize software", "manage TestFlight builds"],
        "DEVELOPER": ["upload builds to TestFlight", "manage internal testers",
                       "create development certificates", "create development profiles",
                       "add UDIDs", "notarize software"],
        "APP_MANAGER": ["upload builds to TestFlight", "manage builds & testers",
                        "update App Store metadata", "submit for review"],
    }
    for u in d.get("data", []):
        for r in u.get("attributes", {}).get("roles", []):
            caps = ROLE_CAPS.get(str(r).upper())
            if caps:
                print(f"  role {r} capabilities:")
                for c in caps:
                    print(f"    - {c}")

    print()
    print("=== certificates ===")
    for c in asc_client.call("/v1/certificates").get("data", []):
        a = c.get("attributes", {})
        print(f"  {c['id']}  {a.get('certificateType')}  expires {a.get('expirationDate')}")
    print()
    print("=== provisioning profiles ===")
    for p in asc_client.call("/v1/profiles").get("data", []):
        a = p.get("attributes", {})
        print(f"  {p['id']}  {a.get('name')}  ({a.get('profileType')})")
    print()
    print("=== apps ===")
    for a in asc_client.call("/v1/apps").get("data", []):
        at = a.get("attributes", {})
        print(f"  {a['id']}  {at.get('name')}  ({at.get('bundleId')})")


if __name__ == "__main__":
    main()
