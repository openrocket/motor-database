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
| **Manifest** | `https://openrocket.github.io/motor-database/metadata.json` | Lightweight JSON file. Contains `database_version`, `generated_at`, `last_checked`, `sha256`, and the signature fields for verification. Checked by the client on startup. |
| **Database** | `https://openrocket.github.io/motor-database/motors.db.gz` | GZipped SQLite database. Downloaded by the client *only* if the manifest version differs from the local cache. |

### Manifest Format
The `metadata.json` structure is defined as follows:
`database_version` is a sortable timestamp in `YYYYMMDDHHMMSS` format.
```json
{
  "schema_version": 2,
  "database_version": 20251225140000,
  "generated_at": "2025-12-25T14:00:00.000000",
  "last_checked": "2025-12-27T14:00:00.000000",
  "motor_count": 1033,
  "curve_count": 1320,
  "sha256": "a1b2c3d4e5f6...",
  "sha256_gz": "a1b2c3d4e5f6...",
  "sig": "base64-signature...",
  "download_url": "https://openrocket.github.io/motor-database/motors.db.gz"
}
```

Signature notes:
- `sig` is an Ed25519 signature over `openrocket-motordb-v1\n{database_version}\n{sha256_gz}\n`.
- `sha256_gz` is the SHA-256 of the gzipped database; `sha256` is kept for backward compatibility.
- `key_id` is optional for key rotation.

## Database Schema

The SQLite schema lives in `schema/V1__initial_schema.sql` and is optimized for fast client lookups. Foreign keys are enabled with cascade deletes.

### Entity Relationship

```
manufacturers          motors              thrust_curves           thrust_data
┌──────────────┐      ┌──────────────┐     ┌──────────────┐        ┌──────────────┐
│ id (PK)      │◄─────│ mfr_id (FK)  │     │ id (PK)      │◄───────│ curve_id(FK) │
│ name         │  1:N │ id (PK)      │◄────│ motor_id(FK) │    1:N │ id (PK)      │
│ abbrev       │      │ tc_motor_id  │ 1:N │ tc_simfile_id│        │ time_seconds │
└──────────────┘      │ designation  │     │ source       │        │ force_newtons│
                      │ impulse_class│     │ format       │        └──────────────┘
                      │ ...          │     │ ...          │
                      └──────────────┘     └──────────────┘
```

- **manufacturers** → **motors**: One manufacturer has many motors
- **motors** → **thrust_curves**: One motor can have multiple thrust curves (different sources/measurements)
- **thrust_curves** → **thrust_data**: One curve has many time/thrust data points

### Tables and Columns

**meta**

| Column | Type | Notes |
| :--- | :--- | :--- |
| key | TEXT | Primary key |
| value | TEXT | Required |

Keys stored: `schema_version`, `database_version`, `generated_at`, `motor_count`, `curve_count`.

---

**manufacturers**

| Column | Type | Notes |
| :--- | :--- | :--- |
| id | INTEGER | Primary key, autoincrement |
| name | TEXT | Required, unique (e.g. "AeroTech") |
| abbrev | TEXT | Short name (e.g. "AT") |

---

**motors**

| Column | Type | Notes |
| :--- | :--- | :--- |
| id | INTEGER | Primary key, autoincrement |
| manufacturer_id | INTEGER | FK to `manufacturers.id` |
| tc_motor_id | TEXT | ThrustCurve.org motor ID |
| designation | TEXT | Required (e.g. "H128W") |
| common_name | TEXT | Display name (e.g. "H128") |
| impulse_class | TEXT | Letter class: A, B, C, ... O |
| diameter | REAL | Motor diameter in mm |
| length | REAL | Motor length in mm |
| total_impulse | REAL | Total impulse in Ns |
| avg_thrust | REAL | Average thrust in N |
| max_thrust | REAL | Maximum thrust in N |
| burn_time | REAL | Burn time in seconds |
| propellant_weight | REAL | Propellant weight in grams |
| total_weight | REAL | Total weight in grams |
| type | TEXT | "SU" (single-use), "reload", "hybrid" |
| delays | TEXT | Available delays, e.g. "0,6,10,14" |
| case_info | TEXT | Case info, e.g. "RMS 38/360" |
| prop_info | TEXT | Propellant info, e.g. "White Lightning" |
| sparky | INTEGER | 1 if sparky motor, 0 otherwise |
| info_url | TEXT | URL to motor info page |
| data_files | INTEGER | Number of data files on ThrustCurve |
| updated_on | TEXT | Last update date from ThrustCurve |
| description | TEXT | RASP file comments (header notes, newlines removed) |
| source | TEXT | Data source (e.g. "thrustcurve.org", "manual") |

---

**thrust_curves**

Each motor can have multiple thrust curves from different sources (certification, manufacturer, user submissions).

| Column | Type | Notes |
| :--- | :--- | :--- |
| id | INTEGER | Primary key, autoincrement |
| motor_id | INTEGER | FK to `motors.id`, cascade delete |
| tc_simfile_id | TEXT | ThrustCurve.org simfile ID |
| source | TEXT | "cert", "mfr", or "user" |
| format | TEXT | "RASP" or "RSE" |
| license | TEXT | "PD", "free", or other |
| info_url | TEXT | URL to simfile info page |
| data_url | TEXT | URL to download simfile |
| total_impulse | REAL | Calculated total impulse (Ns) |
| avg_thrust | REAL | Calculated average thrust (N) |
| max_thrust | REAL | Calculated max thrust (N) |
| burn_time | REAL | Calculated burn time (s) |

---

**thrust_data**

Time/thrust data points for each thrust curve.

| Column | Type | Notes |
| :--- | :--- | :--- |
| id | INTEGER | Primary key, autoincrement |
| curve_id | INTEGER | FK to `thrust_curves.id`, cascade delete |
| time_seconds | REAL | Time in seconds |
| force_newtons | REAL | Thrust force in Newtons |

---

### Indices

| Index | Table | Columns | Purpose |
| :--- | :--- | :--- | :--- |
| idx_motor_mfr | motors | manufacturer_id | Filter by manufacturer |
| idx_motor_diameter | motors | diameter | Filter by size |
| idx_motor_impulse | motors | total_impulse | Filter by impulse |
| idx_motor_impulse_class | motors | impulse_class | Filter by class (A-O) |
| idx_motor_tc_id | motors | tc_motor_id | Lookup by ThrustCurve ID |
| idx_curve_motor | thrust_curves | motor_id | Get curves for a motor |
| idx_curve_simfile | thrust_curves | tc_simfile_id | Lookup by simfile ID |
| idx_thrust_curve | thrust_data | curve_id | Get data for a curve |

## Manual Usage

1.  `pip install -r scripts/requirements.txt`
2.  `python scripts/fetch_updates.py` (Downloads new files)
3.  `python scripts/build_database.py` (Generates DB)

## State Files

- `state/last_update.json`: timestamp of the most recent data/metadata change detected by `scripts/fetch_updates.py`.
- `state/last_check.json`: timestamp of the most recent update check, even if no changes were found.
- `state/last_build.json`: input hash + build outputs used by `scripts/build_database.py` to skip rebuilding when the schema/data inputs are unchanged.

## Signing

Signing is done in CI after the database build completes.

What is signed:
- Canonical message: `openrocket-motordb-v1\n{database_version}\n{sha256_gz}\n`
- `sha256_gz` is the SHA-256 of `motors.db.gz` (the compressed DB)

What gets added to `metadata.json` by the signing step:
- `sha256_gz`: SHA-256 of `motors.db.gz` (currently matches `sha256`)
- `sig`: base64-encoded Ed25519 signature of the canonical message
- `key_id` (optional): identifier for key rotation

How CI handles it:
- `.github/workflows/update-motors.yml` installs `cryptography`
- It runs `python scripts/sign_database.py motors.db.gz metadata.json`
- The private key is provided via secrets

Set the private key in:

- `MOTOR_DB_PRIVATE_KEY_BASE64` (Ed25519 private key, DER or PEM encoded, then base64)
- `MOTOR_DB_KEY_ID` (optional, for key rotation)

Manual signing: `python scripts/sign_database.py motors.db.gz metadata.json`

## Unit Tests

1.  `pip install -r scripts/requirements.txt`
2.  `pip install pytest cryptography`
3.  `pytest`

## Data Attribution & License
The motor data in this repository is cached from [ThrustCurve.org](https://www.thrustcurve.org). 

*   **Source:** ThrustCurve.org (maintained by John Coker).
*   **Copyright:** The data files (`.eng`, `.rse`) retain their original internal copyright headers.
*   **Usage:** This data is intended for use within OpenRocket. If you wish to use this data for other projects, please use the [ThrustCurve.org API](https://www.thrustcurve.org/info/api.html) directly to ensure you are respecting the latest updates and restrictions.
