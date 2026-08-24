import base64
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_release.py"
spec = importlib.util.spec_from_file_location("validate_release", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load validate_release module")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def _create_release(tmp_path, database_version=20240101010101):
    database_path = tmp_path / "motors.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE manufacturers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, abbrev TEXT);
        CREATE TABLE motors (
            id INTEGER PRIMARY KEY, manufacturer_id INTEGER NOT NULL, tc_motor_id TEXT,
            designation TEXT NOT NULL, common_name TEXT, impulse_class TEXT, diameter REAL,
            length REAL, total_impulse REAL, avg_thrust REAL, max_thrust REAL, burn_time REAL,
            propellant_weight REAL, total_weight REAL, type TEXT, delays TEXT, case_info TEXT,
            prop_info TEXT, sparky INTEGER, info_url TEXT, data_files INTEGER, updated_on TEXT,
            FOREIGN KEY (manufacturer_id) REFERENCES manufacturers(id)
        );
        CREATE TABLE thrust_curves (
            id INTEGER PRIMARY KEY, motor_id INTEGER NOT NULL, tc_simfile_id TEXT, source TEXT,
            format TEXT, license TEXT, info_url TEXT, data_url TEXT, total_impulse REAL,
            avg_thrust REAL, max_thrust REAL, burn_time REAL,
            FOREIGN KEY (motor_id) REFERENCES motors(id)
        );
        CREATE TABLE thrust_data (
            id INTEGER PRIMARY KEY, curve_id INTEGER NOT NULL, time_seconds REAL NOT NULL,
            force_newtons REAL NOT NULL, FOREIGN KEY (curve_id) REFERENCES thrust_curves(id)
        );
        INSERT INTO manufacturers VALUES (1, 'Test Motors', 'TM');
        INSERT INTO motors (id, manufacturer_id, designation) VALUES (1, 1, 'A1');
        INSERT INTO thrust_curves (id, motor_id) VALUES (1, 1);
        INSERT INTO thrust_data VALUES (1, 1, 0.0, 0.0);
        INSERT INTO thrust_data VALUES (2, 1, 1.0, 1.0);
        """
    )
    metadata_values = {
        "schema_version": 2,
        "database_version": database_version,
        "motor_count": 1,
        "curve_count": 1,
    }
    connection.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [(key, str(value)) for key, value in metadata_values.items()],
    )
    connection.commit()
    connection.close()

    compressed_path = tmp_path / "motors.db.gz"
    with open(database_path, "rb") as database_file, gzip.open(compressed_path, "wb") as compressed_file:
        compressed_file.write(database_file.read())
    sha256_gz = hashlib.sha256(compressed_path.read_bytes()).hexdigest()
    metadata = {
        **metadata_values,
        "sha256": sha256_gz,
        "sha256_gz": sha256_gz,
        "download_url": "https://openrocket.github.io/motor-database/motors.db.gz",
    }
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata))
    return compressed_path, metadata_path


def _validate_small_release(compressed_path, metadata_path, **kwargs):
    return validator.validate_release(
        compressed_path,
        metadata_path,
        minimum_motors=1,
        minimum_curves=1,
        minimum_points=2,
        **kwargs,
    )


def _generate_signing_key(tmp_path):
    private_key_path = tmp_path / "private.pem"
    private_key_der_path = tmp_path / "private.der"
    public_key_path = tmp_path / "public.pem"
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
    return base64.b64encode(private_key_der_path.read_bytes()).decode("utf-8"), public_key_path


def test_validate_release_accepts_consistent_database(tmp_path):
    compressed_path, metadata_path = _create_release(tmp_path)

    counts = _validate_small_release(compressed_path, metadata_path)

    assert counts == {"motor_count": 1, "curve_count": 1, "point_count": 2}


def test_validate_release_rejects_metadata_database_version_mismatch(tmp_path):
    compressed_path, metadata_path = _create_release(tmp_path)
    metadata = json.loads(metadata_path.read_text())
    metadata["database_version"] += 1
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(validator.ValidationError, match="database_version"):
        _validate_small_release(compressed_path, metadata_path)


def test_validate_release_rejects_large_count_drop(tmp_path):
    compressed_path, metadata_path = _create_release(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"motor_count": 2, "curve_count": 2}))

    with pytest.raises(validator.ValidationError, match="dropped"):
        _validate_small_release(compressed_path, metadata_path, baseline_path=baseline_path)


def test_validate_release_verifies_signature(tmp_path):
    compressed_path, metadata_path = _create_release(tmp_path)
    private_key_b64, public_key_path = _generate_signing_key(tmp_path)

    sign_path = Path(__file__).resolve().parents[1] / "scripts" / "sign_database.py"
    sign_spec = importlib.util.spec_from_file_location("sign_database_for_validator", sign_path)
    sign_module = importlib.util.module_from_spec(sign_spec)
    sign_spec.loader.exec_module(sign_module)
    sign_module.sign_metadata(compressed_path, metadata_path, private_key_b64=private_key_b64)

    _validate_small_release(
        compressed_path,
        metadata_path,
        require_signature=True,
        public_key_path=public_key_path,
    )


def test_validate_release_rejects_invalid_signature(tmp_path):
    compressed_path, metadata_path = _create_release(tmp_path)
    metadata = json.loads(metadata_path.read_text())
    metadata["sig"] = base64.b64encode(bytes(64)).decode("utf-8")
    metadata_path.write_text(json.dumps(metadata))
    _, public_key_path = _generate_signing_key(tmp_path)

    with pytest.raises(validator.ValidationError, match="signature verification"):
        _validate_small_release(
            compressed_path,
            metadata_path,
            require_signature=True,
            public_key_path=public_key_path,
        )
