#!/usr/bin/env python3
"""Set GitHub Actions repository secrets from a JSON file.

Values are encrypted with the repo's public key (libsodium sealed box, as
GitHub requires) before upload, so the plaintext never leaves this box.

Usage:
    python3 set_gh_secrets.py secrets.json [--dry-run]

secrets.json: {"NAME": "value", ...}
"""

import base64
import json
import os
import pathlib
import re
import sys
import urllib.request

REPO = os.environ.get("GH_REPO", "ngjordan/iridium-docs")


def token() -> str:
    txt = pathlib.Path("/home/coreuser/.git-credentials").read_text()
    m = re.search(r"https://[^:]+:([^@]+)@github\.com", txt)
    if not m:
        sys.exit("no GitHub token in ~/.git-credentials")
    return m.group(1)


TOK = token()


def api(path, method="GET", data=None, raw_body=None, headers=None):
    h = {
        "Authorization": f"Bearer {TOK}",
        "User-Agent": "hermes",
        "Accept": "application/vnd.github+json",
    }
    if data is not None:
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    body = raw_body if raw_body is not None else (
        json.dumps(data).encode() if data is not None else None
    )
    req = urllib.request.Request(
        f"https://api.github.com{path}", method=method, headers=h, data=body
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        raw = resp.read()
        return json.loads(raw) if raw else {"__status": resp.status}
    except urllib.error.HTTPError as e:
        return {"__error": e.code, "body": e.read().decode()[:400]}


def encrypt(plaintext: str, public_key_b64: str) -> str:
    """GitHub's secret format: libsodium sealed box.

    The blob is ephemeral_pubkey(32) | nonce(24) | crypto_box_ciphertext.
    The shared secret is X25519(ephemeral_priv, repo_pub); the box is
    XSalsa20-Poly1305 (crypto_box) over it.
    """
    # GitHub expects a libsodium sealed box:
    #   ephemeral_pubkey(32) | crypto_box_easy ciphertext
    # nacl.public.SealedBox produces exactly that shape.
    import nacl.public

    key_bytes = base64.b64decode(public_key_b64)
    sealed = nacl.public.SealedBox(nacl.public.PublicKey(key_bytes))
    return base64.b64encode(sealed.encrypt(plaintext.encode())).decode()


def main() -> None:
    path = sys.argv[1]
    dry = "--dry-run" in sys.argv
    secrets = json.loads(pathlib.Path(path).read_text())

    pk = api(f"/repos/{REPO}/actions/secrets/public-key")
    if "key" not in pk:
        sys.exit(f"no public key: {pk}")
    key_id, pub = pk["key_id"], pk["key"]

    print(f"repo: {REPO}")
    print(f"public key id: {key_id}")
    print(f"{len(secrets)} secret(s) to set\n")

    for name, value in secrets.items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
            sys.exit(f"invalid secret name: {name}")
        enc = encrypt(value, pub)
        if dry:
            print(f"  [dry] {name:28s} ({len(value)} chars)")
            continue
        r = api(
            f"/repos/{REPO}/actions/secrets/{name}",
            method="PUT",
            raw_body=json.dumps(
                {"encrypted_value": enc, "key_id": key_id}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        ok = "__error" not in r
        print(f"  [{'OK' if ok else 'FAIL'}] {name:28s} ({len(value)} chars)")
        if not ok:
            print(f"         {r}")


if __name__ == "__main__":
    main()
