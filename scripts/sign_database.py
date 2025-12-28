import base64
import hashlib
import json
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


ENV_PRIVATE_KEY = "MOTOR_DB_PRIVATE_KEY_BASE64"
ENV_KEY_ID = "MOTOR_DB_KEY_ID"
MESSAGE_PREFIX = "openrocket-motordb-v1"


def compute_sha256_hex(path):
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def load_private_key_from_b64(private_key_b64):
    try:
        key_bytes = base64.b64decode(private_key_b64)
    except (ValueError, TypeError) as e:
        raise ValueError("Invalid base64 for private key.") from e

    loaders = (serialization.load_der_private_key, serialization.load_pem_private_key)
    last_error = None
    for loader in loaders:
        try:
            key = loader(key_bytes, password=None)
            if isinstance(key, ed25519.Ed25519PrivateKey):
                return key
        except Exception as e:
            last_error = e

    raise ValueError("Unsupported private key format or type.") from last_error


def sign_metadata(db_file, metadata_file, private_key_b64=None, key_id=None):
    if private_key_b64 is None:
        private_key_b64 = os.environ.get(ENV_PRIVATE_KEY)
    if not private_key_b64:
        raise ValueError(f"Private key environment variable missing: {ENV_PRIVATE_KEY}")

    if key_id is None:
        key_id = os.environ.get(ENV_KEY_ID)

    sha256_gz = compute_sha256_hex(db_file)

    with open(metadata_file, "r") as f:
        metadata = json.load(f)
    db_version = str(metadata.get("database_version", "")).strip()
    if not db_version:
        raise ValueError("database_version missing in metadata.json")

    message_str = f"{MESSAGE_PREFIX}\n{db_version}\n{sha256_gz}\n"
    message_bytes = message_str.encode("utf-8")

    private_key = load_private_key_from_b64(private_key_b64)
    signature = private_key.sign(message_bytes)
    sig_b64 = base64.b64encode(signature).decode("utf-8")

    metadata["sha256"] = sha256_gz
    metadata["sha256_gz"] = sha256_gz
    metadata["sig"] = sig_b64
    if key_id:
        metadata["key_id"] = str(key_id)

    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)

    return {
        "sha256": sha256_gz,
        "sha256_gz": sha256_gz,
        "sig": sig_b64,
        "key_id": str(key_id) if key_id else None,
    }


def main():
    db_file = sys.argv[1] if len(sys.argv) > 1 else "motors.db.gz"
    metadata_file = sys.argv[2] if len(sys.argv) > 2 else "metadata.json"

    try:
        result = sign_metadata(db_file, metadata_file)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Signed {db_file} -> metadata sig: {result['sig']}")


if __name__ == "__main__":
    main()
