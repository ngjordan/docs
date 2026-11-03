#!/usr/bin/env python3
"""App Store Connect API client.

With a team API key (.p8 + Issuer ID + Key ID) this can, fully scriptable:
  - list users, teams, devices, apps, bundle ids, provisioning profiles
  - CREATE Apple Distribution / Apple Development certificates
  - CREATE provisioning profiles
  - download the .cer / .p12 / .mobileprovision
  - read App Store Connect app metadata

It cannot create Developer ID Application certificates: Apple issues those only
through the developer portal, to the Account Holder.

Key material lives at:
  ~/.hermes/keys/apple/AuthKey_<KEY_ID>.p8
  ~/.hermes/keys/apple/issuer_id
  ~/.hermes/keys/apple/key_id
"""

import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt

KEY_DIR = pathlib.Path(os.environ.get("APPLE_KEY_DIR",
                                       pathlib.Path.home() / ".hermes/keys/apple"))
BASE = "https://api.appstoreconnect.apple.com"


def _read(name: str) -> str:
    p = KEY_DIR / name
    if not p.exists():
        raise SystemExit(
            f"missing {p}\n"
            "Put the ASC key material there:\n"
            f"  AuthKey_<KEY_ID>.p8  (from developer.apple.com -> Integrations)\n"
            f"  issuer_id            (the Issuer ID)\n"
            f"  key_id               (the Key ID)"
        )
    return p.read_text().strip()


def token() -> str:
    key_id = _read("key_id")
    issuer = _read("issuer_id")
    pem = _read(f"AuthKey_{key_id}.p8")
    now = int(time.time())
    return jwt.encode(
        {"iss": issuer, "iat": now - 60, "exp": now + 1200,
         "aud": "appstoreconnect-v1"},
        pem, algorithm="ES256", headers={"kid": key_id, "typ": "JWT"},
    )


def call(path, method="GET", data=None, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, method=method, data=body, headers={
        "Authorization": f"Bearer {token()}",
        "Content-Type": "application/json",
    })
    try:
        r = urllib.request.urlopen(req, timeout=30)
        raw = r.read()
        return json.loads(raw) if raw else {"__status": r.status}
    except urllib.error.HTTPError as e:
        return {"__error": e.code, "body": e.read().decode()[:500]}
    except urllib.error.URLError as e:
        return {"__error": "network", "body": str(e)}


if __name__ == "__main__":
    import sys
    import urllib.parse

    cmd = sys.argv[1] if len(sys.argv) > 1 else "whoami"
    if cmd == "whoami":
        d = call("/v1/users")
        if "__error" in d:
            print("AUTH FAILED:", d)
        else:
            for u in d.get("data", []):
                print(f"  user  {u['id']}  {u.get('attributes',{}).get('username')}"
                      f"  roles={u.get('attributes',{}).get('roles')}")
    elif cmd == "certificates":
        d = call("/v1/certificates")
        for c in d.get("data", []):
            a = c.get("attributes", {})
            print(f"  {c['id']}  {a.get('certificateType')}  expires={a.get('expirationDate')}")
    elif cmd == "profiles":
        d = call("/v1/profiles")
        for p in d.get("data", []):
            a = p.get("attributes", {})
            print(f"  {p['id']}  {a.get('name')}  {a.get('profileType')}")
    elif cmd == "apps":
        d = call("/v1/apps")
        for a in d.get("data", []):
            print(f"  {a['id']}  {a.get('attributes',{}).get('name')} "
                  f"{a.get('attributes',{}).get('bundleId')}")
    else:
        print(__doc__)
