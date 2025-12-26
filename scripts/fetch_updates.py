import os
import json
import requests
import time
import base64
from datetime import datetime

# Config
DATA_DIR = "data/thrustcurve.org"
STATE_FILE = "state/last_sync.json"
MOTORS_METADATA_FILE = "data/thrustcurve.org/motors_metadata.json"
MANUFACTURERS_FILE = "data/thrustcurve.org/manufacturers.json"
SIMFILE_MAPPING_FILE = "data/thrustcurve.org/simfile_to_motor.json"
TC_API_METADATA = "https://www.thrustcurve.org/api/v1/metadata.json"
TC_API_SEARCH = "https://www.thrustcurve.org/api/v1/search.json"
TC_API_DOWNLOAD = "https://www.thrustcurve.org/api/v1/download.json"

# Headers mimicking OpenRocket
HEADERS = {
    'User-Agent': 'OpenRocket-Updater/1.0',
    'Content-Type': 'application/json'
}


def load_state():
    # Handle empty or corrupt JSON files gracefully
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except (json.JSONDecodeError, IOError):
            print("Warning: State file corrupted or empty. Resetting to full download.")
    return {"last_updated": "1970-01-01"}


def load_motors_metadata():
    """Load existing motors metadata from JSON file."""
    if os.path.exists(MOTORS_METADATA_FILE):
        try:
            with open(MOTORS_METADATA_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except (json.JSONDecodeError, IOError):
            print("Warning: Motors metadata file corrupted or empty. Starting fresh.")
    return {"motors": {}}


def save_motors_metadata(metadata):
    """Save motors metadata to JSON file."""
    os.makedirs(os.path.dirname(MOTORS_METADATA_FILE), exist_ok=True)
    with open(MOTORS_METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)


def load_simfile_mapping():
    """Load simfileId -> motorId mapping from JSON file."""
    if os.path.exists(SIMFILE_MAPPING_FILE):
        try:
            with open(SIMFILE_MAPPING_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except (json.JSONDecodeError, IOError):
            print("Warning: Simfile mapping file corrupted or empty. Starting fresh.")
    return {}


def save_simfile_mapping(mapping):
    """Save simfileId -> motorId mapping to JSON file."""
    os.makedirs(os.path.dirname(SIMFILE_MAPPING_FILE), exist_ok=True)
    with open(SIMFILE_MAPPING_FILE, 'w') as f:
        json.dump(mapping, f, indent=2)


def save_state():
    # Ensure directory exists before writing
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump({"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f)


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def sanitize_filename(name):
    # Sanitize to be filesystem safe
    return "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()


def get_manufacturers():
    """Fetch and save the canonical manufacturers list from ThrustCurve metadata API."""
    print("Fetching manufacturer list...")
    try:
        payload = {
            "availability": "all"
        }

        resp = requests.get(TC_API_METADATA, json=payload, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            manufacturers = data.get('manufacturers', [])
            
            # Save the full manufacturers list for use in build_database.py
            os.makedirs(os.path.dirname(MANUFACTURERS_FILE), exist_ok=True)
            with open(MANUFACTURERS_FILE, 'w') as f:
                json.dump({"manufacturers": manufacturers}, f, indent=2)
            print(f"Saved {len(manufacturers)} manufacturers to {MANUFACTURERS_FILE}")
            
            return [m['name'] for m in manufacturers]
    except Exception as e:
        print(f"Failed to fetch manufacturers: {e}")
    return []


def download_motor_data(motor_id, mfr_name, motor_name, simfile_mapping):
    """
    Download motor data files and record simfileId -> motorId mapping with metadata.
    
    Returns: (saved_count, simfile_ids) - number of files saved and list of simfile IDs
    """
    # Matches Java: info.openrocket.core.thrustcurve.ThrustCurveAPI.postDownload
    payload = {
        "motorIds": [motor_id],
        "format": "RASP"  # Or loop ["RASP", "RockSim"] if you want both
    }

    try:
        resp = requests.post(TC_API_DOWNLOAD, json=payload, headers=HEADERS)
        if resp.status_code != 200:
            print(f"  [Error] Download failed for {motor_id}: Status {resp.status_code}")
            return 0, []

        data = resp.json()
        results = data.get('results', [])

        saved_count = 0
        simfile_ids = []
        
        for res in results:
            # Matches Java: info.openrocket.core.thrustcurve.MotorBurnFile.decodeFile
            b64_data = res.get('data')
            simfile_id = res.get('simfileId')
            fmt = res.get('format', 'RASP')

            if not b64_data or not simfile_id:
                continue

            # Record the simfileId -> motorId mapping with full metadata
            simfile_mapping[simfile_id] = {
                'motorId': motor_id,
                'format': fmt,
                'source': res.get('source'),        # 'cert', 'mfr', 'user'
                'license': res.get('license'),      # 'PD', 'free', 'other'
                'infoUrl': res.get('infoUrl'),
                'dataUrl': res.get('dataUrl'),
            }
            simfile_ids.append(simfile_id)

            try:
                # Decode Base64
                file_content = base64.b64decode(b64_data).decode('utf-8', errors='ignore')

                # Save file
                mfr_dir = os.path.join(DATA_DIR, sanitize_filename(mfr_name))
                ensure_dir(mfr_dir)

                # Keep original filename format for backward compatibility
                # The simfile_mapping.json provides the motorId lookup
                filename = f"{sanitize_filename(motor_name)}_{simfile_id}.{fmt.lower()}"
                filepath = os.path.join(mfr_dir, filename)

                with open(filepath, 'w') as f:
                    f.write(file_content)
                saved_count += 1

            except Exception as e:
                print(f"  [Error] Failed to decode/write {simfile_id}: {e}")

        return saved_count, simfile_ids

    except Exception as e:
        print(f"  [Error] API Request failed: {e}")
        return 0, []


def fetch_motors():
    state = load_state()
    last_updated_date = state['last_updated']
    
    # Load existing motor metadata
    motors_metadata = load_motors_metadata()
    
    # Load existing simfile -> motorId mapping
    simfile_mapping = load_simfile_mapping()
    
    # If metadata file doesn't exist or is empty, force a full sync
    if not motors_metadata['motors']:
        print("No existing metadata found. Performing full sync...")
        last_updated_date = "1970-01-01"
    else:
        print(f"Checking for updates since {last_updated_date}...")

    manufacturers = get_manufacturers()
    if not manufacturers:
        print("No manufacturers found. Exiting.")
        return
    
    total_downloaded = 0
    total_metadata_updated = 0

    for mfr in manufacturers:
        # Search by manufacturer (Matches Java logic)
        search_payload = {
            "manufacturer": mfr,
            "maxResults": 9999,
            "availability": "all"
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

                # Store motor metadata (all fields from the search response)
                motors_metadata['motors'][mid] = {
                    'motorId': mid,
                    'manufacturer': motor.get('manufacturer'),
                    'manufacturerAbbrev': motor.get('manufacturerAbbrev'),
                    'designation': motor.get('designation'),
                    'commonName': common_name,
                    'impulseClass': motor.get('impulseClass'),
                    'diameter': motor.get('diameter'),
                    'length': motor.get('length'),
                    'type': motor.get('type'),
                    'avgThrustN': motor.get('avgThrustN'),
                    'maxThrustN': motor.get('maxThrustN'),
                    'totImpulseNs': motor.get('totImpulseNs'),
                    'burnTimeS': motor.get('burnTimeS'),
                    'dataFiles': motor.get('dataFiles'),
                    'infoUrl': motor.get('infoUrl'),
                    'totalWeightG': motor.get('totalWeightG'),
                    'propWeightG': motor.get('propWeightG'),
                    'delays': motor.get('delays'),
                    'caseInfo': motor.get('caseInfo'),
                    'propInfo': motor.get('propInfo'),
                    'sparky': motor.get('sparky'),
                    'updatedOn': motor.get('updatedOn'),
                }
                total_metadata_updated += 1

                # Download thrust curve data files
                count, _ = download_motor_data(mid, mfr, common_name, simfile_mapping)
                total_downloaded += count
                if count > 0:
                    print(f"  Downloaded {count} files for motor {common_name} (ID: {mid})")

                # Sleep briefly to respect API
                time.sleep(0.01)

        except Exception as e:
            print(f"Error processing {mfr}: {e}")

    print(f"Update complete. {total_downloaded} files downloaded, {total_metadata_updated} motor metadata entries updated.")
    
    if total_metadata_updated > 0:
        save_motors_metadata(motors_metadata)
        print(f"Saved metadata for {len(motors_metadata['motors'])} total motors to {MOTORS_METADATA_FILE}")
    
    if total_downloaded > 0:
        save_simfile_mapping(simfile_mapping)
        print(f"Saved {len(simfile_mapping)} simfile->motor mappings to {SIMFILE_MAPPING_FILE}")
    
    if total_downloaded > 0 or total_metadata_updated > 0:
        save_state()


def rebuild_simfile_mapping():
    """
    Rebuild the simfile mapping by querying the ThrustCurve API for all motors
    in the metadata. This is useful if you already have the data files but
    the mapping wasn't created.
    """
    print("Rebuilding simfile->motor mapping from existing metadata...")
    
    # Load existing motor metadata
    motors_metadata = load_motors_metadata()
    tc_motors = motors_metadata.get('motors', {})
    
    if not tc_motors:
        print("No motor metadata found. Run fetch_updates first.")
        return
    
    # Load existing mapping
    simfile_mapping = load_simfile_mapping()
    initial_count = len(simfile_mapping)
    
    print(f"Found {len(tc_motors)} motors in metadata, {initial_count} existing mappings")
    
    # For each motor, query the download API to get simfile IDs
    processed = 0
    for motor_id, motor_meta in tc_motors.items():
        common_name = motor_meta.get('commonName', 'Unknown')
        mfr = motor_meta.get('manufacturer', 'Unknown')
        
        # Query download API (but don't save the files)
        payload = {
            "motorIds": [motor_id],
            "format": "RASP"
        }
        
        try:
            resp = requests.post(TC_API_DOWNLOAD, json=payload, headers=HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get('results', [])
                
                for res in results:
                    simfile_id = res.get('simfileId')
                    if simfile_id:
                        # Store full metadata for each simfile
                        simfile_mapping[simfile_id] = {
                            'motorId': motor_id,
                            'format': res.get('format', 'RASP'),
                            'source': res.get('source'),        # 'cert', 'mfr', 'user'
                            'license': res.get('license'),      # 'PD', 'free', 'other'
                            'infoUrl': res.get('infoUrl'),
                            'dataUrl': res.get('dataUrl'),
                        }
                
                processed += 1
                if processed % 100 == 0:
                    print(f"  Processed {processed}/{len(tc_motors)} motors...")
            
            # Brief sleep to respect API
            time.sleep(0.01)
            
        except Exception as e:
            print(f"  [Error] Failed to query {motor_id}: {e}")
    
    # Save the mapping
    save_simfile_mapping(simfile_mapping)
    print(f"Done! Added {len(simfile_mapping) - initial_count} new mappings.")
    print(f"Total: {len(simfile_mapping)} simfile->motor mappings saved to {SIMFILE_MAPPING_FILE}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--rebuild-mapping":
        rebuild_simfile_mapping()
    else:
        fetch_motors()