# OpenRocket Motor Database

This repository acts as the dynamic backend for OpenRocket's thrust curve data.

## Deployment & API Endpoints

This repository utilizes **GitHub Pages** to act as a static Content Delivery Network (CDN) for the compiled motor data. This ensures high availability and fast downloads for OpenRocket users without requiring a dedicated backend server.

## Architecture

1.  **Source:** [ThrustCurve.org](https://www.thrustcurve.org/) API (thanks a lot for this incredible resource!).
2.  **Automation:** GitHub Actions runs weekly.
3.  **Process:**
    *   Checks for new motors.
    *   Downloads raw `.eng` and `.rse` files to `data/`.
    *   Compiles them into a SQLite database (`motors.db`).
    *   GZips and hashes the database.
4.  **Distribution:** The resulting `motors.db.gz` and `metadata.json` are published to GitHub Pages.

The deployment process follows a split-branch strategy:

1.  **`main` branch:** Contains the source code, scripts, and the raw text cache (`.eng`/`.rse` files).
2.  **`gh-pages` branch:** Contains **only** the build artifacts (`motors.db.gz` and `metadata.json`).

Every time the [Update Workflow](.github/workflows/update-motors.yml) runs (scheduled weekly), it commits the new raw data to `main`, compiles the database, and force-pushes the binary artifacts to `gh-pages`.

### Public Endpoints

The OpenRocket client (and other interested 3rd parties) can access the live data at the following URLs:

| File | URL | Description |
| :--- | :--- | :--- |
| **Manifest** | `https://openrocket.info/motor-database/metadata.json` | Lightweight JSON file. Contains the `database_version`, `timestamp`, and `sha256` checksum. Checked by the client on startup. |
| **Database** | `https://openrocket.info/motor-database/motors.db.gz` | GZipped SQLite database. Downloaded by the client *only* if the manifest version differs from the local cache. |

### Manifest Format
The `metadata.json` structure is defined as follows:
`database_version` is a sortable timestamp in `YYYYMMDDHHMMSS` format.
```json
{
  "schema_version": 1,
  "database_version": 20251225140000,
  "generated_at": "2025-12-25T14:00:00.000000",
  "motor_count": 1033,
  "sha256": "a1b2c3d4e5f6...",
  "download_url": "https://openrocket.info/motor-database/motors.db.gz"
}
```

## Database Schema

The SQLite schema lives in `schema/V1__initial_schema.sql` and is optimized for fast client lookups. Foreign keys are enabled, with `motors` referencing `manufacturers` and `thrust_data` referencing `motors` (cascade delete).

### Tables and Columns

**meta**

| Column | Type | Notes |
| :--- | :--- | :--- |
| key | TEXT | Primary key |
| value | TEXT | Required |

Keys stored include `schema_version`, `database_version`, `generated_at`, and `motor_count`.

**manufacturers**

| Column | Type | Notes |
| :--- | :--- | :--- |
| id | INTEGER | Primary key, autoincrement |
| name | TEXT | Required, unique |
| abbrev | TEXT | Optional short name |

**motors**

| Column | Type | Notes |
| :--- | :--- | :--- |
| id | INTEGER | Primary key, autoincrement |
| manufacturer_id | INTEGER | Required, FK to `manufacturers.id` |
| designation | TEXT | Required motor designation |
| common_name | TEXT | Optional display name |
| diameter | REAL | mm |
| length | REAL | mm |
| impulse | REAL | Ns |
| avg_thrust | REAL | N |
| burn_time | REAL | s |
| propellant_weight | REAL | kg |
| total_weight | REAL | kg |
| type | TEXT | e.g. SU (Single Use), RE (Reload) |
| data_file_format | TEXT | e.g. RASP, RSE |
| last_updated_source | TEXT | Source metadata string |

**thrust_data**

| Column | Type | Notes |
| :--- | :--- | :--- |
| id | INTEGER | Primary key, autoincrement |
| motor_id | INTEGER | Required, FK to `motors.id`, cascade delete |
| time_seconds | REAL | Required, seconds |
| force_newtons | REAL | Required, newtons |

### Indices

| Index | Table | Columns | Purpose |
| :--- | :--- | :--- | :--- |
| idx_motor_mfr | motors | manufacturer_id | Filter by manufacturer |
| idx_motor_diameter | motors | diameter | Filter by size |
| idx_motor_impulse | motors | impulse | Filter by impulse class |

## Manual Usage

1.  `pip install -r scripts/requirements.txt`
2.  `python scripts/fetch_updates.py` (Downloads new files)
3.  `python scripts/build_database.py` (Generates DB)

## Data Attribution & License
The motor data in this repository is cached from [ThrustCurve.org](https://www.thrustcurve.org). 

*   **Source:** ThrustCurve.org (maintained by John Coker).
*   **Copyright:** The data files (`.eng`, `.rse`) retain their original internal copyright headers.
*   **Usage:** This data is intended for use within OpenRocket. If you wish to use this data for other projects, please use the [ThrustCurve.org API](https://www.thrustcurve.org/info/api.html) directly to ensure you are respecting the latest updates and restrictions.
