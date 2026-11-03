#!/usr/bin/env python3
"""Create an Apple certificate through the App Store Connect API.

The API takes a CSR and returns the issued certificate. We generate the CSR
locally (the private key never leaves this machine), POST it, and write the
.cer out.

Usage:
    python3 asc_create_cert.py <name> [--type DISTRIBUTION|DEVELOPMENT|...]
                               [--csr path/to.csr --key path/to/key]
"""

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import asc_client  # noqa: E402

# The API's certificateType enum is SCREAMING_CASE, and only the types the API
# may create are listed here. DEVELOPER_ID_* are deliberately absent: Apple
# returns 403 for them over the API (they are portal-only, Account Holder).
CERT_TYPES = {
    "DISTRIBUTION": "DISTRIBUTION",
    "DEVELOPMENT": "DEVELOPMENT",
    "MAC_APP_DISTRIBUTION": "MAC_APP_DISTRIBUTION",
    "MAC_INSTALLER_DISTRIBUTION": "MAC_INSTALLER_DISTRIBUTION",
    "IOS_DEVELOPMENT": "IOS_DEVELOPMENT",
    "IOS_DISTRIBUTION": "IOS_DISTRIBUTION",
    "MAC_APP_DEVELOPMENT": "MAC_APP_DEVELOPMENT",
}


def make_csr(name: str, common_name: str) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path("/tmp/asc-csr")
    out.mkdir(exist_ok=True)
    key = out / f"{name}.key"
    csr = out / f"{name}.csr"
    if key.exists() or csr.exists():
        sys.exit(f"error: {key} / {csr} already exist. "
                 "A private key must never be regenerated for an issued certificate.")
    conf = out / "csr.cnf"
    conf.write_text(
        "[req]\ndefault_bits = 2048\nprompt = no\ndefault_md = sha256\n"
        "distinguished_name = dn\n"
        f"[dn]\nCN = {common_name}\nemailAddress = docs@iridium.ph\n"
        "O = Iridium Technologies, Inc.\nC = PH\n", encoding="utf-8")
    pem = csr.with_suffix(".pem")
    subprocess.run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(key), "-out", str(pem), "-config", str(conf)],
                   check=True, capture_output=True)
    # The API's csrContent is the base64 of the DER-encoded PKCS#10 request.
    # Sending PEM gets "Invalid Certificate".
    subprocess.run(["openssl", "req", "-in", str(pem), "-outform", "DER",
                    "-out", str(csr)], check=True, capture_output=True)
    conf.unlink()
    pem.unlink()
    key.chmod(0o600)
    return key, csr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="certificate name, e.g. iridium-distribution")
    ap.add_argument("--type", default="DISTRIBUTION", choices=sorted(CERT_TYPES))
    ap.add_argument("--csr", help="use an existing CSR instead of generating one")
    ap.add_argument("--key", help="the matching private key (for a .p12)")
    args = ap.parse_args()

    if args.csr:
        csr = pathlib.Path(args.csr)
        key = pathlib.Path(args.key) if args.key else None
        if not csr.exists():
            sys.exit(f"error: {csr} not found")
    else:
        key, csr = make_csr(args.name, args.name)

    csr_b64 = __import__("base64").b64encode(csr.read_bytes()).decode()

    # Apple derives the certificate's name from the CSR's subject: sending
    # "name" on a CREATE is rejected with ENTITY_ERROR.ATTRIBUTE.NOT_ALLOWED.
    payload = {
        "data": {
            "type": "certificates",
            "attributes": {
                "certificateType": CERT_TYPES[args.type],
                "csrContent": csr_b64,
            },
        }
    }
    r = asc_client.call("/v1/certificates", "POST", payload)
    if "__error" in r:
        print("CREATE FAILED:", json.dumps(r, indent=2))
        sys.exit(1)

    cid = r["data"]["id"]
    print(f"created certificate {cid}")

    # Download the .cer
    r2 = asc_client.call(f"/v1/certificates/{cid}")
    attrs = r2.get("data", {}).get("attributes", {})
    print(f"  type      {attrs.get('certificateType')}")
    print(f"  name      {attrs.get('name')}")
    print(f"  expires   {attrs.get('expirationDate')}")
    print(f"  serial    {attrs.get('serialNumber')}")

    # Apple returns the DER certificate inline, base64-encoded, in
    # `certificateContent` (not a download URL).
    content = r2.get("data", {}).get("attributes", {}).get("certificateContent")
    if not content:
        print("  no certificateContent in the response")
        return
    import base64
    data = base64.b64decode(content)

    out_dir = pathlib.Path("/opt/hermes-agent/workspace/wc-devid")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.name}.cer"
    out.write_bytes(data)
    print(f"  wrote {out} ({len(data)} bytes)")
    # Keep a PEM copy so `openssl pkcs12 -export` can use it.
    pem_out = out.with_suffix(".pem")
    subprocess.run(["openssl", "x509", "-inform", "DER", "-in", str(out),
                    "-out", str(pem_out)], check=False)
    subprocess.run(["openssl", "x509", "-in", str(pem_out),
                    "-noout", "-subject", "-issuer", "-dates"], check=False)


if __name__ == "__main__":
    main()
