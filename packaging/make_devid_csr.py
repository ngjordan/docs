#!/usr/bin/env python3
"""Generate the certificate signing request (CSR) for a Developer ID Application
certificate, ready to upload to the Apple Developer portal.

Apple issues Developer ID Application certificates only through the developer
portal, to the Account Holder. The portal asks for a .certSigningRequest, so
that is what this produces. The private key stays here and never leaves the box.

Usage:
    python3 make_devid_csr.py <out-dir> [--name "Jordan Ng"]

Writes:
    <out-dir>/iridium-docs-devid.key   the private key (PEM, PKCS#8)
    <out-dir>/iridium-docs-devid.csr   the CSR to upload to Apple (.certSigningRequest)

Then, in the Apple Developer portal:
    Certificates -> + -> Software -> Developer ID -> Developer ID Application
    -> upload the .certSigningRequest -> Download the .cer
Export the certificate + this key from Keychain Access as a .p12, or convert
here:
    openssl pkcs12 -export -inkey iridium-docs-devid.key \\
      -in DeveloperIDApplication.cer -out DeveloperIDApplication.p12 \\
      -passout pass:<password>
"""

import argparse
import pathlib
import shutil
import subprocess
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--name", default="Iridium Technologies")
    ap.add_argument("--email", default="docs@iridium.ph")
    args = ap.parse_args()

    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    key = out / "iridium-docs-devid.key"
    csr = out / "iridium-docs-devid.csr"

    if shutil.which("openssl") is None:
        sys.exit("error: openssl not found")
    if key.exists() or csr.exists():
        sys.exit(
            f"error: {key.name} / {csr.name} already exist.\n"
            "       Delete them first, or use a different directory - the private\n"
            "       key must not be regenerated after the certificate is issued."
        )

    conf = out / "csr.cnf"
    conf.write_text(
        "[req]\n"
        "default_bits = 2048\n"
        "prompt = no\n"
        "default_md = sha256\n"
        "distinguished_name = dn\n"
        "[dn]\n"
        f"CN = {args.name}\n"
        f"emailAddress = {args.email}\n"
        "O = Iridium Technologies, Inc.\n"
        "C = PH\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(csr), "-config", str(conf)],
        check=True,
    )
    conf.unlink()
    key.chmod(0o600)

    print("\n=== CSR created ===")
    print(f"  private key : {key}   (mode 600, never upload this)")
    print(f"  CSR         : {csr}")
    print()
    print("Upload the CSR to Apple:")
    print("  https://developer.apple.com/account/resources/certificates/list")
    print("  + -> Software -> Developer ID -> Developer ID Application")
    print("  Choose File ->", csr.name)
    print()
    print("Verify the CSR before uploading:")
    subprocess.run(["openssl", "req", "-in", str(csr), "-noout", "-text"],
                   check=False)


if __name__ == "__main__":
    main()
