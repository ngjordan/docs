#!/usr/bin/env python3
"""Apple release automation for any project.

Two Apple signing paths exist, and they differ in what can be automated:

  macOS outside the App Store (Developer ID)
      Signed with a "Developer ID Application" certificate and notarized with
      `xcrun notarytool`. Apple issues these certificates ONLY through the
      developer portal and ONLY to the Account Holder - the App Store Connect
      API cannot create them. So one human portal step is unavoidable.

  iOS / Mac App Store (distribution)
      Signed with an "Apple Distribution" certificate plus a provisioning
      profile. The App Store Connect API CAN create these, so once an API key
      exists it is fully scriptable.

This tool covers the scriptable half and automates as much of the rest as
Apple permits.

Subcommands:
  csr <out-dir>            Generate a Developer ID CSR + private key.
  p12 <key> <cer> <out>    Combine key + .cer into a .p12.
  secrets <file.json>      Upload GitHub Actions secrets (encrypted).
  check                    Report what Apple access this box has.

Usage: apple_release.py <subcommand> [args]
"""

import argparse
import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

REPO_DEFAULT = os.environ.get("GH_REPO", "ngjordan/iridium-docs")
CREDS = pathlib.Path("/home/coreuser/.git-credentials")


# ---------------------------------------------------------------- helpers
def gh_token() -> str:
    m = re.search(r"https://[^:]+:([^@]+)@github\.com", CREDS.read_text())
    if not m:
        sys.exit("no GitHub token in ~/.git-credentials")
    return m.group(1)


def api(path, method="GET", data=None, raw_body=None, headers=None):
    h = {"Authorization": f"Bearer {gh_token()}", "User-Agent": "hermes",
         "Accept": "application/vnd.github+json"}
    if data is not None:
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    body = raw_body if raw_body is not None else (
        json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(f"https://api.github.com{path}", method=method,
                                 headers=h, data=body)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        raw = r.read()
        return json.loads(raw) if raw else {"__status": r.status}
    except urllib.error.HTTPError as e:
        return {"__error": e.code, "body": e.read().decode()[:400]}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- subcommands
def cmd_csr(args):
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    key = out / f"{args.name_slug}-devid.key"
    csr = out / f"{args.name_slug}-devid.csr"
    if key.exists() or csr.exists():
        sys.exit(f"error: {key.name} / {csr.name} exist already.\n"
                 "       The private key must NOT be regenerated after Apple "
                 "issues the certificate.")
    conf = out / "csr.cnf"
    conf.write_text(
        "[req]\ndefault_bits = 2048\nprompt = no\ndefault_md = sha256\n"
        "distinguished_name = dn\n"
        f"[dn]\nCN = {args.cn}\nemailAddress = {args.email}\n"
        f"O = {args.org}\nC = {args.country}\n", encoding="utf-8")
    run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(csr), "-config", str(conf)])
    conf.unlink()
    key.chmod(0o600)
    print(f"private key : {key}  (mode 600 - never upload)")
    print(f"CSR         : {csr}")
    print("\nUpload the CSR at:")
    print("  https://developer.apple.com/account/resources/certificates/list")
    print("  + -> Software -> Developer ID -> Developer ID Application")
    v = run(["openssl", "req", "-in", str(csr), "-noout", "-verify"]).stderr
    print(f"\n{v.strip()}")


def cmd_p12(args):
    run(["openssl", "pkcs12", "-export", "-inkey", args.key, "-in", args.cer,
         "-out", args.out, "-passout", f"pass:{args.password}"])
    p = pathlib.Path(args.out)
    p.chmod(0o600)
    b64 = base64.b64encode(p.read_bytes()).decode()
    b64p = pathlib.Path(str(args.out) + ".b64")
    b64p.write_text(b64, encoding="utf-8")
    print(f"wrote {p} ({p.stat().st_size} bytes, mode 600)")
    print(f"wrote {b64p} (base64, {len(b64)} chars)")
    print(f"\nAPPLE_CERTIFICATE = contents of {b64p}")


def cmd_secrets(args):
    repo = args.repo or REPO_DEFAULT
    secrets = json.loads(pathlib.Path(args.file).read_text())
    pk = api(f"/repos/{repo}/actions/secrets/public-key")
    if "key" not in pk:
        sys.exit(f"no public key for {repo}: {pk}")
    import nacl.public
    sealed_box = nacl.public.SealedBox(
        nacl.public.PublicKey(base64.b64decode(pk["key"])))
    print(f"repo: {repo}")
    for name, value in secrets.items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
            sys.exit(f"invalid secret name: {name}")
        enc = base64.b64encode(sealed_box.encrypt(value.encode())).decode()
        r = api(f"/repos/{repo}/actions/secrets/{name}", "PUT",
                raw_body=json.dumps({"encrypted_value": enc,
                                     "key_id": pk["key_id"]}).encode(),
                headers={"Content-Type": "application/json"})
        ok = "__error" not in r
        print(f"  [{'OK' if ok else 'FAIL'}] {name:28s} ({len(value)} chars)")
        if not ok:
            print(f"         {r}")


def cmd_check(args):
    print("=== GitHub ===")
    r = api(f"/repos/{args.repo or REPO_DEFAULT}")
    print(f"  repo        : {r.get('full_name')}  private={r.get('private')}")
    s = api(f"/repos/{args.repo or REPO_DEFAULT}/actions/secrets")
    print(f"  secrets set : {s.get('total_count', 0)}")
    for x in s.get("secrets", []):
        print(f"      {x['name']}")
    print()
    print("=== Apple ===")
    for label, url in [
        ("developer.apple.com", "https://developer.apple.com/"),
        ("idmsa.apple.com (sign-in)", "https://idmsa.apple.com/"),
        ("api.appstoreconnect.apple.com", "https://api.appstoreconnect.apple.com/v1/"),
    ]:
        try:
            req = urllib.request.Request(url)
            urllib.request.urlopen(req, timeout=10)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception:
            code = "unreachable"
        print(f"  {label:34s} -> {code}")
    print()
    print("  Developer ID Application : portal-only, Account Holder  <- human step")
    print("  Apple Distribution       : App Store Connect API        <- scriptable")
    print()
    print("=== local toolchain ===")
    for t in ["openssl", "security", "xcodebuild", "codesign", "notarytool",
              "stapler", "hdiutil", "iconutil", "fastlane"]:
        print(f"  {t:12s} : {shutil.which(t) or 'MISSING'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("csr", help="generate a Developer ID CSR")
    p.add_argument("out_dir")
    p.add_argument("--cn", default="Jordan Ng")
    p.add_argument("--email", default="docs@iridium.ph")
    p.add_argument("--org", default="Iridium Technologies, Inc.")
    p.add_argument("--country", default="PH")
    p.add_argument("--name-slug", default="iridium")
    p.set_defaults(fn=cmd_csr)

    p = sub.add_parser("p12", help="combine a private key and .cer into a .p12")
    p.add_argument("key")
    p.add_argument("cer")
    p.add_argument("out")
    p.add_argument("--password", required=True)
    p.set_defaults(fn=cmd_p12)

    p = sub.add_parser("secrets", help="upload GitHub Actions secrets (encrypted)")
    p.add_argument("file")
    p.add_argument("--repo", default=None)
    p.set_defaults(fn=cmd_secrets)

    p = sub.add_parser("check", help="report available Apple/GitHub access")
    p.add_argument("--repo", default=None)
    p.set_defaults(fn=cmd_check)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
