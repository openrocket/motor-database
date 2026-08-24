"""Fail-closed validation for a motor database release artifact."""

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from urllib.parse import urlparse


MESSAGE_PREFIX = "openrocket-motordb-v1"
MAX_COMPRESSED_BYTES = 50 * 1024 * 1024
MAX_DATABASE_BYTES = 200 * 1024 * 1024
MIN_MOTOR_COUNT = 1_000
MIN_CURVE_COUNT = 1_000
MIN_THRUST_POINT_COUNT = 10_000
MAX_COUNT_DROP_RATIO = 0.15
ALLOWED_DOWNLOAD_HOSTS = {"openrocket.info", "openrocket.github.io"}

REQUIRED_COLUMNS = {
    "meta": {"key", "value"},
    "manufacturers": {"id", "name", "abbrev"},
    "motors": {
        "id", "manufacturer_id", "tc_motor_id", "designation", "common_name",
        "impulse_class", "diameter", "length", "total_impulse", "avg_thrust",
        "max_thrust", "burn_time", "propellant_weight", "total_weight", "type",
        "delays", "case_info", "prop_info", "sparky", "info_url", "data_files",
        "updated_on",
    },
    "thrust_curves": {
        "id", "motor_id", "tc_simfile_id", "source", "format", "license",
        "info_url", "data_url", "total_impulse", "avg_thrust", "max_thrust",
        "burn_time",
    },
    "thrust_data": {"id", "curve_id", "time_seconds", "force_newtons"},
}


class ValidationError(Exception):
    """Raised when a release artifact is unsafe to publish or install."""


def sha256_file(path):
    """Return the lowercase SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_metadata(metadata_path):
    """Load and validate release metadata fields that are independent of SQLite."""
    with open(metadata_path, "r", encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)

    required = {"schema_version", "database_version", "motor_count", "curve_count", "sha256_gz", "download_url"}
    missing = sorted(required.difference(metadata))
    if missing:
        raise ValidationError(f"metadata.json is missing fields: {', '.join(missing)}")

    for key in ("schema_version", "database_version", "motor_count", "curve_count"):
        if not isinstance(metadata[key], int) or isinstance(metadata[key], bool):
            raise ValidationError(f"metadata field {key} must be an integer")
    if metadata["database_version"] <= 0:
        raise ValidationError("database_version must be positive")

    sha256_gz = str(metadata["sha256_gz"]).strip().lower()
    if len(sha256_gz) != 64 or any(character not in "0123456789abcdef" for character in sha256_gz):
        raise ValidationError("sha256_gz must be 64 lowercase hexadecimal characters")
    metadata["sha256_gz"] = sha256_gz

    parsed_url = urlparse(str(metadata["download_url"]))
    if parsed_url.scheme.lower() != "https" or parsed_url.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise ValidationError("download_url must use HTTPS and an approved OpenRocket host")
    return metadata


def decompress_database(database_gz_path, output_path):
    """Decompress a database while enforcing compressed and expanded size limits."""
    if os.path.getsize(database_gz_path) > MAX_COMPRESSED_BYTES:
        raise ValidationError("compressed database exceeds the release size limit")

    expanded_bytes = 0
    try:
        with gzip.open(database_gz_path, "rb") as compressed_file, open(output_path, "wb") as database_file:
            while True:
                chunk = compressed_file.read(1024 * 1024)
                if not chunk:
                    break
                expanded_bytes += len(chunk)
                if expanded_bytes > MAX_DATABASE_BYTES:
                    raise ValidationError("expanded database exceeds the release size limit")
                database_file.write(chunk)
    except (OSError, EOFError) as error:
        raise ValidationError(f"invalid gzip database: {error}") from error


def table_columns(connection, table_name):
    """Return the column names for an SQLite table."""
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table_name}")')}


def read_single_count(connection, table_name):
    """Read a table count using a fixed, internally supplied table name."""
    return connection.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0]


def validate_database(database_path, metadata, minimum_motors, minimum_curves, minimum_points):
    """Validate integrity, schema, metadata consistency, and core physical invariants."""
    database_uri = Path(database_path).resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(database_uri, uri=True)
    try:
        integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if integrity_rows != ["ok"]:
            raise ValidationError(f"SQLite integrity_check failed: {integrity_rows[:3]}")

        foreign_key_error = connection.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_error is not None:
            raise ValidationError(f"SQLite foreign_key_check failed: {foreign_key_error}")

        for table_name, required_columns in REQUIRED_COLUMNS.items():
            present_columns = table_columns(connection, table_name)
            missing_columns = sorted(required_columns.difference(present_columns))
            if missing_columns:
                raise ValidationError(f"table {table_name} is missing columns: {', '.join(missing_columns)}")

        database_metadata = dict(connection.execute("SELECT key, value FROM meta"))
        for key in ("schema_version", "database_version", "motor_count", "curve_count"):
            if key not in database_metadata:
                raise ValidationError(f"SQLite metadata is missing {key}")
            if int(database_metadata[key]) != metadata[key]:
                raise ValidationError(f"SQLite and release metadata disagree on {key}")

        motor_count = read_single_count(connection, "motors")
        curve_count = read_single_count(connection, "thrust_curves")
        point_count = read_single_count(connection, "thrust_data")
        if motor_count != metadata["motor_count"] or curve_count != metadata["curve_count"]:
            raise ValidationError("declared motor/curve counts do not match the SQLite tables")
        if motor_count < minimum_motors or curve_count < minimum_curves or point_count < minimum_points:
            raise ValidationError(
                f"release is unexpectedly small: {motor_count} motors, {curve_count} curves, {point_count} points"
            )

        invalid_point = connection.execute(
            "SELECT id FROM thrust_data "
            "WHERE time_seconds IS NULL OR force_newtons IS NULL "
            "OR typeof(time_seconds) NOT IN ('integer', 'real') "
            "OR typeof(force_newtons) NOT IN ('integer', 'real') "
            "OR time_seconds < 0 OR force_newtons < 0 "
            "OR abs(time_seconds) > 1000000 OR abs(force_newtons) > 1000000000 LIMIT 1"
        ).fetchone()
        if invalid_point is not None:
            raise ValidationError(f"invalid thrust point found at row {invalid_point[0]}")

        incomplete_curve = connection.execute(
            "SELECT thrust_curves.id FROM thrust_curves "
            "LEFT JOIN thrust_data ON thrust_data.curve_id = thrust_curves.id "
            "GROUP BY thrust_curves.id "
            "HAVING count(thrust_data.id) < 2 OR max(time_seconds) <= min(time_seconds) LIMIT 1"
        ).fetchone()
        if incomplete_curve is not None:
            raise ValidationError(f"thrust curve has insufficient time coverage: {incomplete_curve[0]}")
    except (sqlite3.DatabaseError, TypeError, ValueError) as error:
        if isinstance(error, ValidationError):
            raise
        raise ValidationError(f"invalid SQLite database: {error}") from error
    finally:
        connection.close()

    return {"motor_count": motor_count, "curve_count": curve_count, "point_count": point_count}


def validate_baseline(counts, baseline_path):
    """Reject unexpectedly large count drops relative to the previous successful build."""
    if baseline_path is None:
        return
    with open(baseline_path, "r", encoding="utf-8") as baseline_file:
        baseline = json.load(baseline_file)
    for count_key in ("motor_count", "curve_count"):
        old_count = int(baseline.get(count_key, 0))
        if old_count > 0 and counts[count_key] < old_count * (1 - MAX_COUNT_DROP_RATIO):
            raise ValidationError(
                f"{count_key} dropped from {old_count} to {counts[count_key]} (more than {MAX_COUNT_DROP_RATIO:.0%})"
            )


def verify_signature(metadata, public_key_path):
    """Verify the release signature with the public key embedded by OpenRocket."""
    signature_text = metadata.get("sig")
    if not signature_text:
        raise ValidationError("signed metadata is missing sig")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (TypeError, ValueError) as error:
        raise ValidationError("sig is not valid base64") from error
    if len(signature) != 64:
        raise ValidationError("Ed25519 signature must be 64 bytes")

    message = (
        f"{MESSAGE_PREFIX}\n{metadata['database_version']}\n{metadata['sha256_gz']}\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="openrocket-motordb-verify-") as temp_dir:
        message_path = os.path.join(temp_dir, "message")
        signature_path = os.path.join(temp_dir, "signature")
        with open(message_path, "wb") as message_file:
            message_file.write(message)
        with open(signature_path, "wb") as signature_file:
            signature_file.write(signature)
        command = [
            "openssl", "pkeyutl", "-verify", "-pubin", "-rawin",
            "-inkey", str(public_key_path), "-in", message_path, "-sigfile", signature_path,
        ]
        try:
            subprocess.run(command, check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise ValidationError("release signature verification failed") from error


def validate_release(database_gz_path, metadata_path, baseline_path=None, require_signature=False,
                     public_key_path=None, minimum_motors=MIN_MOTOR_COUNT,
                     minimum_curves=MIN_CURVE_COUNT, minimum_points=MIN_THRUST_POINT_COUNT):
    """Validate a complete release and return its verified row counts."""
    metadata = load_metadata(metadata_path)
    actual_sha256 = sha256_file(database_gz_path)
    if actual_sha256 != metadata["sha256_gz"]:
        raise ValidationError("motors.db.gz SHA-256 does not match metadata.json")
    if "sha256" in metadata and str(metadata["sha256"]).lower() != actual_sha256:
        raise ValidationError("legacy sha256 field does not match motors.db.gz")

    with tempfile.TemporaryDirectory(prefix="openrocket-motordb-validate-") as temp_dir:
        database_path = os.path.join(temp_dir, "motors.db")
        decompress_database(database_gz_path, database_path)
        counts = validate_database(database_path, metadata, minimum_motors, minimum_curves, minimum_points)

    validate_baseline(counts, baseline_path)
    if require_signature:
        if public_key_path is None:
            raise ValidationError("a public key is required for signature verification")
        verify_signature(metadata, public_key_path)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="path to motors.db.gz")
    parser.add_argument("metadata", help="path to metadata.json")
    parser.add_argument("--baseline", help="previous build state used for count-drop detection")
    parser.add_argument("--require-signature", action="store_true", help="require and verify the Ed25519 signature")
    parser.add_argument("--public-key", help="PEM public key used with --require-signature")
    args = parser.parse_args()

    try:
        counts = validate_release(
            args.database,
            args.metadata,
            baseline_path=args.baseline,
            require_signature=args.require_signature,
            public_key_path=args.public_key,
        )
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"Release validation failed: {error}", file=os.sys.stderr)
        return 1

    print(
        f"Release validated: {counts['motor_count']} motors, "
        f"{counts['curve_count']} curves, {counts['point_count']} thrust points"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
