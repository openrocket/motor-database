# OpenRocket Motor Database

This repository acts as the dynamic backend for OpenRocket's thrust curve data.

## Architecture

1.  **Source:** [ThrustCurve.org](https://www.thrustcurve.org/) API (thanks a lot for this incredible resource!).
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

## Data Attribution & License
The motor data in this repository is cached from [ThrustCurve.org](https://www.thrustcurve.org). 

*   **Source:** ThrustCurve.org (maintained by John Coker).
*   **Copyright:** The data files (`.eng`, `.rse`) retain their original internal copyright headers.
*   **Usage:** This data is intended for use within OpenRocket. If you wish to use this data for other projects, please use the [ThrustCurve.org API](https://www.thrustcurve.org/info/api.html) directly to ensure you are respecting the latest updates and restrictions.
