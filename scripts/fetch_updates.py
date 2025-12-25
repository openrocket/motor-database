import os
import json
import requests
import time
import base64
from datetime import datetime

# Config
DATA_DIR = "data/thrustcurve.org"
STATE_FILE = "state/last_sync.json"
TC_API_METADATA = "https://www.thrustcurve.org/api/v1/metadata.json"
TC_API_SEARCH = "https://www.thrustcurve.org/api/v1/search.json"
TC_API_DOWNLOAD = "https://www.thrustcurve.org/api/v1/download.json"

# Headers mimicking OpenRocket
HEADERS = {
    'User-Agent': 'OpenRocket-Updater/1.0',
    'Content-Type': 'application/json'
}


def load_state():
    # Fix: Handle empty or corrupt JSON files gracefully
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except (json.JSONDecodeError, IOError):
            print("Warning: State file corrupted or empty. Resetting to full download.")
    return {"last_updated": "1970-01-01"}


def save_state():
    # Ensure directory exists before writing
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump({"last_updated": datetime.now().strftime("%Y-%m-%d")}, f)


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def sanitize_filename(name):
    # Sanitize to be filesystem safe
    return "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()


def get_manufacturers():
    print("Fetching manufacturer list...")
    try:
        resp = requests.get(TC_API_METADATA, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            # Extract just the abbreviations or names, similar to Java implementation
            return [m['name'] for m in data.get('manufacturers', [])]
    except Exception as e:
        print(f"Failed to fetch manufacturers: {e}")
    return []


def download_motor_data(motor_id, mfr_name, motor_name):
    # Matches Java: info.openrocket.core.thrustcurve.ThrustCurveAPI.postDownload
    payload = {
        "motorIds": [motor_id],
        "format": "RASP"  # Or loop ["RASP", "RockSim"] if you want both
    }

    try:
        resp = requests.post(TC_API_DOWNLOAD, json=payload, headers=HEADERS)
        if resp.status_code != 200:
            print(f"  [Error] Download failed for {motor_id}: Status {resp.status_code}")
            return 0

        data = resp.json()
        results = data.get('results', [])

        saved_count = 0
        for res in results:
            # Matches Java: info.openrocket.core.thrustcurve.MotorBurnFile.decodeFile
            b64_data = res.get('data')
            simfile_id = res.get('simfileId')
            fmt = res.get('format', 'eng').lower()

            if not b64_data:
                continue

            try:
                # Decode Base64
                file_content = base64.b64decode(b64_data).decode('utf-8', errors='ignore')

                # Save file
                mfr_dir = os.path.join(DATA_DIR, sanitize_filename(mfr_name))
                ensure_dir(mfr_dir)

                filename = f"{sanitize_filename(motor_name)}_{simfile_id}.{fmt}"
                filepath = os.path.join(mfr_dir, filename)

                with open(filepath, 'w') as f:
                    f.write(file_content)
                saved_count += 1

            except Exception as e:
                print(f"  [Error] Failed to decode/write {simfile_id}: {e}")

        return saved_count

    except Exception as e:
        print(f"  [Error] API Request failed: {e}")
        return 0


def fetch_motors():
    state = load_state()
    last_updated_date = state['last_updated']
    print(f"Checking for updates since {last_updated_date}...")

    manufacturers = get_manufacturers()
    if not manufacturers:
        print("No manufacturers found. Exiting.")
        return

    total_downloaded = 0

    for mfr in manufacturers:
        # Search by manufacturer (Matches Java logic)
        search_payload = {
            "manufacturer": mfr,
            "maxResults": 9999
        }

        try:
            resp = requests.post(TC_API_SEARCH, json=search_payload, headers=HEADERS)
            if resp.status_code != 200:
                print(f"Failed to search {mfr}: {resp.status_code}")
                continue

            results = resp.json().get('results', [])

            # Client-side filtering for dates (since API search criteria is limited)
            motors_to_update = []
            for motor in results:
                # 'updatedOn' format is usually "YYYY-MM-DD"
                updated_on = motor.get('updatedOn', '1970-01-01')
                if updated_on >= last_updated_date:
                    motors_to_update.append(motor)

            if not motors_to_update:
                continue

            print(f"Processing {mfr}: {len(motors_to_update)} updated motors found.")

            for motor in motors_to_update:
                mid = motor.get('motorId')
                common_name = motor.get('commonName', 'Unknown')

                # Download data
                count = download_motor_data(mid, mfr, common_name)
                total_downloaded += count
                if count > 0:
                    print(f"  Downloaded {count} files for motor {common_name} (ID: {mid})")

                # Sleep briefly to respect API
                time.sleep(0.01)

        except Exception as e:
            print(f"Error processing {mfr}: {e}")

    print(f"Update complete. {total_downloaded} files downloaded.")
    if total_downloaded > 0:
        save_state()


if __name__ == "__main__":
    fetch_motors()