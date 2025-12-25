import os
import sqlite3
import gzip
import hashlib
import json
import re
from datetime import datetime

DB_NAME = "motors.db"
GZ_NAME = "motors.db.gz"
SCHEMA_FILE = "schema/V1__initial_schema.sql"
DATA_DIR = "data"
METADATA_FILE = "metadata.json"


def init_db():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
    conn = sqlite3.connect(DB_NAME)
    with open(SCHEMA_FILE, 'r') as f:
        conn.executescript(f.read())
    return conn


def parse_rasp_eng(filepath):
    """ Simple RASP (.eng) parser """
    header_parsed = False
    data_points = []
    metadata = {}

    with open(filepath, 'r', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(';'):
                continue

            parts = line.split()
            if not header_parsed:
                if len(parts) < 7: continue
                # RASP Header: Name Diameter Length Delays PropWt TotalWt Mfr
                metadata = {
                    'designation': parts[0],
                    'diameter': float(parts[1]),
                    'length': float(parts[2]),
                    'prop_weight': float(parts[4]),
                    'total_weight': float(parts[5]),
                    'manufacturer': " ".join(parts[6:])
                }
                header_parsed = True
            else:
                # Data line: Time Thrust
                try:
                    t = float(parts[0])
                    f = float(parts[1])
                    data_points.append((t, f))
                except ValueError:
                    pass

    return metadata, data_points


def build():
    conn = init_db()
    cursor = conn.cursor()

    motor_count = 0

    # Traverse directory
    for root, dirs, files in os.walk(DATA_DIR):
        for file in files:
            if file.endswith(".eng"):
                path = os.path.join(root, file)
                try:
                    meta, points = parse_rasp_eng(path)
                    if not meta: continue

                    # 1. Handle Manufacturer
                    cursor.execute("INSERT OR IGNORE INTO manufacturers (name) VALUES (?)", (meta['manufacturer'],))
                    cursor.execute("SELECT id FROM manufacturers WHERE name = ?", (meta['manufacturer'],))
                    mfr_id = cursor.fetchone()[0]

                    # 2. Insert Motor (Calculating simple stats)
                    # Note: Impulse/BurnTime ideally calculated from points, simplified here
                    burn_time = points[-1][0] if points else 0
                    # Simple impulse integration (Trapezoidal rule omitted for brevity)
                    impulse = sum(p[1] for p in points) * (burn_time / len(points)) if points else 0

                    cursor.execute("""
                                   INSERT INTO motors
                                   (manufacturer_id, designation, diameter, length, propellant_weight, total_weight,
                                    impulse, burn_time, type, data_file_format)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                   """,
                                   (mfr_id, meta['designation'], meta['diameter'], meta['length'], meta['prop_weight'],
                                    meta['total_weight'], impulse, burn_time, 'SU', 'RASP'))

                    motor_id = cursor.lastrowid

                    # 3. Insert Thrust Data
                    data_rows = [(motor_id, p[0], p[1]) for p in points]
                    cursor.executemany("INSERT INTO thrust_data (motor_id, time_seconds, force_newtons) VALUES (?,?,?)",
                                       data_rows)

                    motor_count += 1
                except Exception as e:
                    print(f"Failed to parse {file}: {e}")

    print(f"Parsed {motor_count} motors.")

    # Optimize
    conn.execute("VACUUM")
    conn.close()

    # Compress
    with open(DB_NAME, 'rb') as f_in:
        with gzip.open(GZ_NAME, 'wb') as f_out:
            f_out.writelines(f_in)

    # Generate Metadata
    sha256 = hashlib.sha256()
    with open(GZ_NAME, 'rb') as f:
        sha256.update(f.read())

    meta = {
        "schema_version": 1,
        "database_version": int(datetime.now().strftime("%Y%m%d")),
        "generated_at": datetime.now().isoformat(),
        "motor_count": motor_count,
        "sha256": sha256.hexdigest(),
        "download_url": "https://openrocket.github.io/motor-database/motors.db.gz"  # Update with your repo name
    }

    with open(METADATA_FILE, 'w') as f:
        json.dump(meta, f, indent=2)

    print(f"Build complete: {GZ_NAME}")


if __name__ == "__main__":
    build()