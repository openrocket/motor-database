import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sign_database.py"
spec = importlib.util.spec_from_file_location("sign_database", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load sign_database module")
sign_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sign_db)


def _generate_private_key_b64(tmp_path):
    private_key_path = tmp_path / "private-key.pem"
    private_key_der_path = tmp_path / "private-key.der"
    public_key_path = tmp_path / "public-key.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(private_key_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private_key_path), "-outform", "DER", "-out", str(private_key_der_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private_key_path), "-pubout", "-out", str(public_key_path)],
        check=True,
        capture_output=True,
    )
    private_key_b64 = base64.b64encode(private_key_der_path.read_bytes()).decode("utf-8")
    return private_key_b64, public_key_path


def test_compute_sha256_hex(tmp_path):
    path = tmp_path / "file.bin"
    data = b"abc123"
    path.write_bytes(data)

    assert sign_db.compute_sha256_hex(path) == hashlib.sha256(data).hexdigest()


def test_load_private_key_rejects_invalid_base64():
    with pytest.raises(ValueError, match="Invalid base64"):
        sign_db.load_private_key_from_b64("not-base64")


def test_sign_metadata_writes_signature(tmp_path):
    key_b64, public_key_path = _generate_private_key_b64(tmp_path)
    gz_path = tmp_path / "motors.db.gz"
    meta_path = tmp_path / "metadata.json"
    gz_path.write_bytes(b"payload")
    meta_path.write_text(json.dumps({"database_version": 20240101010101}))

    result = sign_db.sign_metadata(
        str(gz_path), str(meta_path), private_key_b64=key_b64, key_id="1"
    )

    sha = hashlib.sha256(b"payload").hexdigest()
    metadata = json.loads(meta_path.read_text())
    assert metadata["sha256"] == sha
    assert metadata["sha256_gz"] == sha
    assert metadata["sig"] == result["sig"]
    assert metadata["key_id"] == "1"

    message = f"{sign_db.MESSAGE_PREFIX}\n{metadata['database_version']}\n{sha}\n"
    message_path = tmp_path / "message"
    signature_path = tmp_path / "signature"
    message_path.write_text(message)
    signature_path.write_bytes(base64.b64decode(metadata["sig"]))
    subprocess.run(
        [
            "openssl", "pkeyutl", "-verify", "-pubin", "-rawin",
            "-inkey", str(public_key_path), "-in", str(message_path), "-sigfile", str(signature_path),
        ],
        check=True,
        capture_output=True,
    )


def test_sign_metadata_missing_database_version(tmp_path):
    key_b64, _ = _generate_private_key_b64(tmp_path)
    gz_path = tmp_path / "motors.db.gz"
    meta_path = tmp_path / "metadata.json"
    gz_path.write_bytes(b"payload")
    meta_path.write_text("{}")

    with pytest.raises(ValueError, match="database_version"):
        sign_db.sign_metadata(str(gz_path), str(meta_path), private_key_b64=key_b64)


def test_sign_metadata_missing_private_key(tmp_path, monkeypatch):
    gz_path = tmp_path / "motors.db.gz"
    meta_path = tmp_path / "metadata.json"
    gz_path.write_bytes(b"payload")
    meta_path.write_text(json.dumps({"database_version": "1"}))
    monkeypatch.delenv(sign_db.ENV_PRIVATE_KEY, raising=False)

    with pytest.raises(ValueError, match="Private key"):
        sign_db.sign_metadata(str(gz_path), str(meta_path))
