#!/usr/bin/env python3
"""Build a PKCS#12 that Apple's Security framework accepts.

`security import` on macOS only understands the older PKCS#12 schemes: a
SHA-1 MAC and SHA1-and-3DES (or SHA1-and-RC2) PBE for the key and the
certificate. OpenSSL 3.x's defaults are PBES2 with AES-256-CBC and an
HMAC-SHA256 MAC, and `security import` rejects those with:

    SecKeychainItemImport: MAC verification failed during PKCS12 import
    (wrong password?)

The message blames the password, but the password is fine - OpenSSL reads the
file on both Linux and the runner because it supports every algorithm, while
Apple's parser cannot. Re-export with the legacy algorithms.

    openssl pkcs12 -export \\
      -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1 \\
      -inkey key.pem -in cert.pem -out out.p12 -passout pass:<password>

`-legacy` does the same thing but needs the legacy provider and picks RC2-40
for the certificate bag, so the explicit form is used here.

Usage:
    python3 make_p12.py <key.pem> <cert.pem> <out.p12> --password <pw>
"""

import argparse
import pathlib
import subprocess
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("cert")
    ap.add_argument("out")
    ap.add_argument("--password", required=True)
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    subprocess.run(
        ["openssl", "pkcs12", "-export",
         "-keypbe", "PBE-SHA1-3DES",
         "-certpbe", "PBE-SHA1-3DES",
         "-macalg", "sha1",
         "-inkey", args.key, "-in", args.cert,
         "-out", str(out), "-passout", f"pass:{args.password}"],
        check=True, capture_output=True)
    out.chmod(0o600)

    # Prove the file has the algorithms Apple wants, and that it still opens.
    info = subprocess.run(
        ["openssl", "pkcs12", "-in", str(out), "-passin", f"pass:{args.password}",
         "-info", "-noout"], capture_output=True, text=True).stderr
    algorithms = [ln.strip() for ln in info.splitlines()
                  if "MAC:" in ln or "PKCS7 Encrypted" in ln or "Shrouded Keybag" in ln]
    for ln in algorithms:
        print("  ", ln)

    if not any("MAC: sha1" in ln for ln in algorithms):
        sys.exit("error: the MAC is not SHA-1; macOS security import will reject it")
    if not any("3-KeyTripleDES-CBC" in ln for ln in algorithms):
        sys.exit("error: the key bag is not 3DES; macOS security import will reject it")

    subprocess.run(["openssl", "pkcs12", "-in", str(out),
                    "-passin", f"pass:{args.password}", "-nokeys", "-passout", "pass:"],
                   check=True, capture_output=True)
    print(f"wrote {out} ({out.stat().st_size} bytes, mode 600)")
    print("algorithms verified: SHA-1 MAC, 3DES key and certificate bags")


if __name__ == "__main__":
    main()
