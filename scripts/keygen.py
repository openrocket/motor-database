"""Generate an Ed25519 signing key pair using the system OpenSSL executable."""

import base64
import os
import subprocess
import tempfile


def run_openssl(arguments):
    """Run OpenSSL and raise a concise error if key generation fails."""
    try:
        subprocess.run(["openssl", *arguments], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("OpenSSL could not generate the Ed25519 key pair") from error


def main():
    with tempfile.TemporaryDirectory(prefix="openrocket-motordb-keygen-") as temp_dir:
        private_pem_path = os.path.join(temp_dir, "private.pem")
        private_der_path = os.path.join(temp_dir, "private.der")
        public_der_path = os.path.join(temp_dir, "public.der")

        run_openssl(["genpkey", "-algorithm", "Ed25519", "-out", private_pem_path])
        run_openssl(["pkey", "-in", private_pem_path, "-outform", "DER", "-out", private_der_path])
        run_openssl([
            "pkey", "-in", private_pem_path, "-pubout", "-outform", "DER", "-out", public_der_path,
        ])

        with open(private_der_path, "rb") as private_file:
            private_key_b64 = base64.b64encode(private_file.read()).decode("utf-8")
        with open(public_der_path, "rb") as public_file:
            public_key_b64 = base64.b64encode(public_file.read()).decode("utf-8")

    print("=== COPY TO GITHUB SECRETS (Private Key) ===")
    print(private_key_b64)
    print("\n=== COPY TO OPENROCKET JAVA CODE (Public Key) ===")
    print(public_key_b64)


if __name__ == "__main__":
    main()
