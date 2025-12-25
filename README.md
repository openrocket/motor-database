# OpenRocket Motor Database

This repository acts as the dynamic backend for OpenRocket's thrust curve data.

## Architecture

1.  **Source:** ThrustCurve.org API.
2.  **Automation:** GitHub Actions runs weekly.
3.  **Process:**
    *   Checks for new motors.
    *   Downloads raw `.eng` and `.rse` files to `data/`.
    *   Compiles them into a SQLite database (`motors.db`).
    *   GZips and hashes the database.
4.  **Distribution:** The resulting `motors.db.gz` and `metadata.json` are published to GitHub Pages.

## Manual Usage

1.  `pip install -r scripts/requirements.txt`
2.  `python scripts/fetch_updates.py` (Downloads new files)
3.  `python scripts/build_database.py` (Generates DB)