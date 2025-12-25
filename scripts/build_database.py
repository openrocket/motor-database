import os
import sqlite3
import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
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

    # Ensure schema file exists
    if not os.path.exists(SCHEMA_FILE):
        print(f"Error: Schema file not found at {SCHEMA_FILE}")
        exit(1)

    with open(SCHEMA_FILE, 'r') as f:
        conn.executescript(f.read())
    return conn


def parse_rasp(filepath):
    """ Parses standard RASP (.eng/.rasp) files """
    header_parsed = False
    data_points = []
    metadata = {}

    with open(filepath, 'r', errors='ignore') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith(';'):
                continue

            parts = line.split()

            if not header_parsed:
                # RASP Header line requires at least 7 fields:
                # Name Diameter Length Delays PropWt TotalWt Mfr
                if len(parts) < 7:
                    return None, None  # Invalid header

                try:
                    metadata = {
                        'designation': parts[0],
                        'diameter': float(parts[1]),
                        'length': float(parts[2]),
                        # parts[3] is delays, skipped for DB simple stats
                        'prop_weight': float(parts[4]),
                        'total_weight': float(parts[5]),
                        'manufacturer': " ".join(parts[6:]),
                        'type': 'SU'  # Default
                    }
                    header_parsed = True
                except ValueError:
                    return None, None  # Header parsing failed
            else:
                # Data line: Time Thrust
                try:
                    # RASP lines can be: Time Thrust [Mass]
                    if len(parts) >= 2:
                        t = float(parts[0])
                        f_n = float(parts[1])
                        data_points.append((t, f_n))
                except ValueError:
                    pass

    return metadata, data_points


def parse_rse(filepath):
    """ Parses RockSim (.rse) XML files """
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        # RSE structure: <engine-database> -> <engine-list> -> <engine>
        engine = root.find(".//engine")
        if engine is None:
            return None, None

        # Extract Metadata
        # attributes: code, mfg, len, dia, propWt, initWt
        metadata = {
            'designation': engine.get('code', 'Unknown'),
            'manufacturer': engine.get('mfg', 'Unknown'),
            'diameter': float(engine.get('dia', 0.0)),
            'length': float(engine.get('len', 0.0)),
            'prop_weight': float(engine.get('propWt', 0.0)) / 1000.0,
            # RSE is usually in grams? Check specific RSE spec. usually mm and g.
            # However, OpenRocket/ThrustCurve usually normalize.
            # Assuming standard RSE: dia/len in mm, mass in g.
            # Our DB schema expects: dia/len in mm, mass in kg.
            'total_weight': float(engine.get('initWt', 0.0)) / 1000.0,
            'type': 'SU'
        }

        # Fix mass units if they look too small (simple heuristic)
        # (This depends on if your raw files are standardized. RSE is defined as mm/g usually).

        data_points = []
        data_node = engine.find("data")
        if data_node is not None:
            for pt in data_node.findall("eng-data"):
                t = float(pt.get('t', 0.0))
                f = float(pt.get('f', 0.0))
                data_points.append((t, f))

        return metadata, data_points

    except Exception:
        return None, None


def build():
    print(f"Building database from '{DATA_DIR}'...")
    conn = init_db()
    cursor = conn.cursor()

    motor_count = 0
    files_found = 0

    # Traverse directory
    for root, dirs, files in os.walk(DATA_DIR):
        for file in files:
            path = os.path.join(root, file)
            lower_file = file.lower()

            meta = None
            points = None
            file_fmt = None

            # 1. Determine parser based on extension
            if lower_file.endswith(".eng") or lower_file.endswith(".rasp"):
                files_found += 1
                meta, points = parse_rasp(path)
                file_fmt = 'RASP'
            elif lower_file.endswith(".rse"):
                files_found += 1
                meta, points = parse_rse(path)
                file_fmt = 'RSE'
            else:
                continue

            if not meta or not points:
                print(f"  [Skipped] Unparseable: {file}")
                continue

            try:
                # 2. Handle Manufacturer
                cursor.execute("INSERT OR IGNORE INTO manufacturers (name) VALUES (?)", (meta['manufacturer'],))
                cursor.execute("SELECT id FROM manufacturers WHERE name = ?", (meta['manufacturer'],))
                mfr_id = cursor.fetchone()[0]

                # 3. Calculate Stats
                burn_time = points[-1][0] if points else 0
                impulse = 0.0
                if len(points) > 1:
                    for i in range(1, len(points)):
                        dt = points[i][0] - points[i - 1][0]
                        avg_f = (points[i][1] + points[i - 1][1]) / 2.0
                        impulse += avg_f * dt

                cursor.execute("""
                               INSERT INTO motors
                               (manufacturer_id, designation, diameter, length, propellant_weight, total_weight,
                                impulse, burn_time, type, data_file_format)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                               """, (mfr_id, meta['designation'], meta['diameter'], meta['length'],
                                     meta['prop_weight'], meta['total_weight'], impulse, burn_time, meta['type'],
                                     file_fmt))

                motor_id = cursor.lastrowid

                # 4. Insert Thrust Data
                data_rows = [(motor_id, p[0], p[1]) for p in points]
                cursor.executemany("INSERT INTO thrust_data (motor_id, time_seconds, force_newtons) VALUES (?,?,?)",
                                   data_rows)

                motor_count += 1

            except Exception as e:
                print(f"  [Error] Failed to insert {file}: {e}")

    print(f"Scanned {files_found} files. Imported {motor_count} motors.")

    if motor_count == 0:
        print("Warning: No motors imported. Check your data directory contents.")

    # --- FIX START ---
    # You must commit the transaction before running VACUUM
    conn.commit()
    # --- FIX END ---

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
        "download_url": "https://openrocket.github.io/motor-database/motors.db.gz"
    }

    with open(METADATA_FILE, 'w') as f:
        json.dump(meta, f, indent=2)

    print(f"Build complete: {GZ_NAME}")


if __name__ == "__main__":
    build()