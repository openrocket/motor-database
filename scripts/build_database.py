import os
import re
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
MOTORS_METADATA_FILE = "data/thrustcurve.org/motors_metadata.json"
MANUFACTURERS_FILE = "data/thrustcurve.org/manufacturers.json"
SIMFILE_MAPPING_FILE = "data/thrustcurve.org/simfile_to_motor.json"
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


def load_motors_metadata():
    """Load motors metadata from JSON file."""
    if os.path.exists(MOTORS_METADATA_FILE):
        try:
            with open(MOTORS_METADATA_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load motors metadata: {e}")
    return {"motors": {}}


def load_manufacturers():
    """Load canonical manufacturers list from JSON file."""
    if os.path.exists(MANUFACTURERS_FILE):
        try:
            with open(MANUFACTURERS_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    return data.get('manufacturers', [])
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load manufacturers: {e}")
    return []


def load_simfile_mapping():
    """Load simfileId -> motorId mapping from JSON file."""
    if os.path.exists(SIMFILE_MAPPING_FILE):
        try:
            with open(SIMFILE_MAPPING_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load simfile mapping: {e}")
    return {}


def build_manufacturer_lookup(manufacturers):
    """
    Build a lookup table to map various manufacturer names/abbreviations 
    to their canonical (name, abbrev) tuple.
    
    Based on OpenRocket's Manufacturer.java mappings.
    """
    lookup = {}
    
    for mfr in manufacturers:
        name = mfr.get('name', '')
        abbrev = mfr.get('abbrev', '')
        canonical = (name, abbrev)
        
        # Add various lookup keys (all lowercase for case-insensitive matching)
        if name:
            lookup[name.lower()] = canonical
        if abbrev:
            lookup[abbrev.lower()] = canonical
        
        # Add without spaces
        name_lower = name.lower()
        lookup[name_lower.replace(' ', '')] = canonical
        lookup[name_lower.replace(' ', '-')] = canonical
        lookup[name_lower.replace(' ', '_')] = canonical
    
    # Comprehensive manufacturer alias mappings (from OpenRocket's Manufacturer.java)
    # Format: alias -> (canonical_name, abbrev)
    
    # AeroTech has many name combinations
    aerotech = ('AeroTech', 'AeroTech')
    for prefix in ['a', 'at', 'aero', 'aerot', 'aerotech']:
        lookup[prefix] = aerotech
        lookup[f'{prefix}-rms'] = aerotech
        lookup[f'{prefix}-rcs'] = aerotech
        lookup[f'{prefix}_rms'] = aerotech
        lookup[f'{prefix}_rcs'] = aerotech
        lookup[f'rcs-{prefix}'] = aerotech
        lookup[f'rcs_{prefix}'] = aerotech
        lookup[f'{prefix}/rcs'] = aerotech
        lookup[f'rcs/{prefix}'] = aerotech
        lookup[f'{prefix}-apogee'] = aerotech
        lookup[f'{prefix}_apogee'] = aerotech
    lookup['isp'] = aerotech
    lookup['aerotech/rcs'] = aerotech
    lookup['rcs/aerotech'] = aerotech
    
    # Alpha Hybrid Rocketry
    alpha = ('Alpha Hybrids', 'Alpha')
    for alias in ['ahr', 'alpha', 'alpha hybrid', 'alpha hybrids', 
                  'alpha hybrids rocketry', 'alpha hybrid rocketry llc',
                  'alpha hybrid rocketry']:
        lookup[alias] = alpha
    
    # Animal Motor Works
    amw = ('Animal Motor Works', 'AMW')
    for alias in ['amw', 'aw', 'animal', 'animal motor works', 'animal_motor_works',
                  'amw/prox', 'amw-prox', 'amw_prox', 'prox']:
        lookup[alias] = amw
    
    # Apogee
    apogee = ('Apogee Components', 'Apogee')
    for alias in ['ap', 'apog', 'p', 'apogee']:
        lookup[alias] = apogee
    
    # Cesaroni Technology
    cesaroni = ('Cesaroni Technology', 'Cesaroni')
    for alias in ['ces', 'cesaroni', 'cesaroni technology incorporated', 'cti',
                  'cs', 'csr', 'pro38', 'abc', 'cesaroni technology', 
                  'cesaroni technology inc.', 'cesaroni technology inc',
                  'cesaroni_technology', 'cesaroni_technology_inc.',
                  'cesaroni_technology_inc', 'cesароnitechnology']:
        lookup[alias] = cesaroni
    
    # Contrail Rockets
    contrail = ('Contrail Rockets', 'Contrail')
    for alias in ['cr', 'contr', 'contrail', 'contrail rocket', 'contrail rockets']:
        lookup[alias] = contrail
    
    # Estes
    estes = ('Estes Industries', 'Estes')
    for alias in ['e', 'es', 'estes', 'estes industries']:
        lookup[alias] = estes
    
    # Ellis Mountain
    ellis = ('Ellis Mountain', 'Ellis')
    for alias in ['em', 'ellis', 'ellis mountain rocket', 'ellis mountain rockets',
                  'ellis mountain']:
        lookup[alias] = ellis
    
    # Gorilla Rocket Motors
    gorilla = ('Gorilla Rocket Motors', 'Gorilla')
    for alias in ['gr', 'gm', 'gorilla', 'gorilla rocket', 'gorilla rockets', 
                  'gorilla motor', 'gorilla motors', 'gorilla rocket motor',
                  'gorilla rocket motors', 'gorilla_rocket_motors', 
                  'gorilla_rocket_motors_', 'gorilla_motors', 'gorillarocketmotors']:
        lookup[alias] = gorilla
    
    # Hypertek
    hypertek = ('Hypertek', 'Hypertek')
    for alias in ['h', 'ht', 'hyper', 'hypertek', 'hypertec']:
        lookup[alias] = hypertek
    
    # Kosdon by AeroTech
    kosdon = ('Kosdon by AeroTech', 'KBA')
    for alias in ['k', 'kba', 'k-at', 'kos', 'kosdon', 'kosdon/at', 
                  'kosdon/aerotech', 'kosdon by aerotech']:
        lookup[alias] = kosdon
    
    # Kosdon TRM (separate from Kosdon by AeroTech)
    kosdon_trm = ('Kosdon TRM', 'Kosdon')
    lookup['kosdon trm'] = kosdon_trm
    
    # Loki Research
    loki = ('Loki Research', 'Loki')
    for alias in ['loki', 'lr', 'ct', 'loki research']:
        lookup[alias] = loki
    
    # Loki Research EX (experimental)
    loki_ex = ('Loki Research', 'Loki')  # Map to standard Loki
    for alias in ['lr-ex', 'loki ex', 'loki research ex']:
        lookup[alias] = loki_ex
    
    # Public Missiles Ltd
    pml = ('Public Missiles, Ltd.', 'PML')
    for alias in ['pm', 'pml', 'public missiles limited', 'public missiles',
                  'public missiles, ltd.', 'public missiles ltd']:
        lookup[alias] = pml
    
    # Propulsion Polymers
    pp = ('Propulsion Polymers', 'PP')
    for alias in ['pp', 'prop', 'propulsion', 'propulsion polymers',
                  'propulsion-polymers']:
        lookup[alias] = pp
    
    # Quest
    quest = ('Quest Aerospace', 'Quest')
    for alias in ['q', 'qu', 'quest', 'quest aerospace']:
        lookup[alias] = quest
    
    # RATT Works
    ratt = ('R.A.T.T. Works', 'RATT')
    for alias in ['ratt', 'rt', 'rtw', 'ratt works', 'r.a.t.t. works',
                  'ratt_works', 'rattworks']:
        lookup[alias] = ratt
    
    # Roadrunner Rocketry
    roadrunner = ('Roadrunner Rocketry', 'Roadrunner')
    for alias in ['rr', 'roadrunner', 'roadrunner rocketry']:
        lookup[alias] = roadrunner
    
    # Rocketvision
    rocketvision = ('Rocketvision Flight-Star', 'RV')
    for alias in ['rv', 'rocket vision', 'rocketvision', 'rocketvision flight-star']:
        lookup[alias] = rocketvision
    
    # Sky Ripper Systems
    skyripper = ('Sky Ripper Systems', 'SkyR')
    for alias in ['sr', 'srs', 'skyr', 'skyripper', 'sky ripper', 
                  'skyripper systems', 'sky ripper systems']:
        lookup[alias] = skyripper
    
    # West Coast Hybrids
    wch = ('West Coast Hybrids', 'WCH')
    for alias in ['wch', 'wcr', 'west coast', 'west coast hybrid', 
                  'west coast hybrids']:
        lookup[alias] = wch
    
    # WECO Feuerwerk / Sachsen Feuerwerk
    weco = ('Raketenmodellbau Klima', 'Klima')  # Map to Klima as closest match
    for alias in ['weco', 'weco feuerwerk', 'weco feuerwerks', 'sf', 
                  'sachsen', 'sachsen feuerwerk', 'sachsen feuerwerks']:
        lookup[alias] = weco
    
    # Raketenmodellbau Klima
    klima = ('Raketenmodellbau Klima', 'Klima')
    for alias in ['klima', 'raketenmodellbau klima']:
        lookup[alias] = klima
    
    # Southern Cross Rocketry
    scr = ('Southern Cross Rocketry', 'SCR')
    for alias in ['scr', 'southern cross', 'southern cross rocketry']:
        lookup[alias] = scr
    
    # LOC/Precision
    loc = ('LOC/Precision', 'LOC')
    for alias in ['loc', 'loc precision', 'loc/precision']:
        lookup[alias] = loc
    
    # Piotr Tendera / TSP
    tsp = ('Piotr Tendera Rocket Motors', 'TSP')
    for alias in ['tsp', 'tendera', 'piotr tendera', 'piotr tendera rocket motors']:
        lookup[alias] = tsp
    
    # AMW ProX (Animal Motor Works ProX line)
    amw_prox = ('AMW ProX', 'AMW/ProX')
    for alias in ['amw/prox', 'amw-prox', 'amw_prox', 'amw prox', 'prox']:
        lookup[alias] = amw_prox
    
    # Historical motors (discontinued/legacy)
    historical = ('Historical', 'Hist')
    for alias in ['hist', 'historical']:
        lookup[alias] = historical
    
    # NoThrust (test/dummy motors)
    nothrust = ('NoThrust', 'NoThrust')
    for alias in ['nothrust', 'no thrust', 'no-thrust']:
        lookup[alias] = nothrust
    
    # Derek Deville DEAP EX (experimental)
    deap_ex = ('Derek Deville DEAP EX', 'DEAP-EX')
    for alias in ['deap-ex', 'deap ex', 'deap', 'derek deville', 'derek deville deap ex']:
        lookup[alias] = deap_ex
    
    return lookup


def parse_rasp(filepath):
    """
    Parses standard RASP (.eng/.rasp) files - only the FIRST motor if file contains multiple.
    
    RASP header format (7+ fields, space-separated):
      1. Common name (impulse class + avg thrust, e.g. "F32")
      2. Casing diameter in mm
      3. Casing length in mm  
      4. Available delays (e.g. "5-10-15", "0" for none, "P" for plugged)
      5. Propellant weight in kg
      6. Total weight in kg
      7+ Manufacturer name (may contain spaces)
    
    Note: Weights are converted from kg (RASP format) to grams (DB format).
    """
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
                    # Parse delays: "0" means no delay, "P" means plugged (no ejection)
                    delays_raw = parts[3]
                    if delays_raw == '0' or delays_raw.upper() == 'P':
                        delays = None
                    else:
                        delays = delays_raw
                    
                    # RASP weights are in kg, convert to grams for DB consistency
                    prop_weight_kg = float(parts[4])
                    total_weight_kg = float(parts[5])
                    
                    metadata = {
                        'common_name': parts[0],           # e.g. "F32" (impulse class + avg thrust)
                        'designation': parts[0],           # Use common_name as fallback designation
                        'diameter': float(parts[1]),       # mm
                        'length': float(parts[2]),         # mm
                        'delays': delays,                  # e.g. "5-10-15" or None
                        'prop_weight': prop_weight_kg * 1000,   # Convert kg -> grams
                        'total_weight': total_weight_kg * 1000, # Convert kg -> grams
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
                        
                        # If thrust is 0, we've reached the end of this motor's data
                        # (RASP format ends with time thrust=0)
                        if f_n == 0:
                            break
                except ValueError:
                    # Non-numeric line after header = probably a new motor header
                    # This handles multi-motor files like RASAero_Motors.eng
                    if len(parts) >= 7:
                        break  # Stop parsing, we hit a new motor header

    return metadata, data_points


def parse_rse(filepath):
    """
    Parses RockSim (.rse) XML files.
    
    RSE engine attributes:
      - code: Motor designation (e.g. "H128W")
      - mfg: Manufacturer name
      - dia: Casing diameter in mm
      - len: Casing length in mm
      - propWt: Propellant weight in grams
      - initWt: Total/initial weight in grams
      - delays: Available delays (e.g. "6,10,14")
    
    Note: RSE weights are already in grams (unlike RASP which uses kg).
    """
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        # RSE structure: <engine-database> -> <engine-list> -> <engine>
        engine = root.find(".//engine")
        if engine is None:
            return None, None

        # Extract Metadata
        delays_raw = engine.get('delays', '')
        if delays_raw == '0' or delays_raw.upper() == 'P' or not delays_raw:
            delays = None
        else:
            delays = delays_raw
        
        designation = engine.get('code', 'Unknown')
        # Extract common name from designation (strip propellant suffix letters)
        # e.g. "H128W" -> "H128", "K550W-L" -> "K550"
        common_name_match = re.match(r'^([A-Z][0-9]+)', designation)
        common_name = common_name_match.group(1) if common_name_match else designation
        
        metadata = {
            'designation': designation,
            'common_name': common_name,
            'manufacturer': engine.get('mfg', 'Unknown'),
            'diameter': float(engine.get('dia', 0.0)),
            'length': float(engine.get('len', 0.0)),
            # RSE weights are already in grams
            'prop_weight': float(engine.get('propWt', 0.0)),
            'total_weight': float(engine.get('initWt', 0.0)),
            'delays': delays,
            'type': 'SU'
        }

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


def calculate_thrust_stats(points):
    """Calculate impulse, avg thrust, max thrust, and burn time from thrust data."""
    if not points:
        return 0, 0, 0, 0
    
    burn_time = points[-1][0] if points else 0
    max_thrust = max(p[1] for p in points) if points else 0
    
    impulse = 0.0
    if len(points) > 1:
        for i in range(1, len(points)):
            dt = points[i][0] - points[i - 1][0]
            avg_f = (points[i][1] + points[i - 1][1]) / 2.0
            impulse += avg_f * dt
    
    avg_thrust = impulse / burn_time if burn_time > 0 else 0
    
    return impulse, avg_thrust, max_thrust, burn_time


def extract_simfile_info_from_filename(filename, simfile_mapping):
    """Extract simfile info from filename using simfile mapping."""
    base = os.path.splitext(filename)[0]
    matches = re.findall(r'[a-f0-9]{24}', base, re.IGNORECASE)
    for match in matches:
        if match in simfile_mapping:
            info = simfile_mapping[match]
            if isinstance(info, str):
                return match, {'motorId': info}
            return match, info
    return None, None


def build():
    print(f"Building database from '{DATA_DIR}'...")
    conn = init_db()
    cursor = conn.cursor()

    # Load canonical manufacturers and insert them first
    canonical_manufacturers = load_manufacturers()
    print(f"Loaded {len(canonical_manufacturers)} canonical manufacturers")
    
    # Load simfileId -> motorId mapping
    simfile_mapping = load_simfile_mapping()
    print(f"Loaded {len(simfile_mapping)} simfile->motor mappings")
    
    mfr_name_to_id = {}  # name -> db id
    for mfr in canonical_manufacturers:
        name = mfr.get('name')
        abbrev = mfr.get('abbrev')
        if name:
            cursor.execute("INSERT OR IGNORE INTO manufacturers (name, abbrev) VALUES (?, ?)",
                           (name, abbrev))
            cursor.execute("SELECT id FROM manufacturers WHERE name = ?", (name,))
            mfr_name_to_id[name] = cursor.fetchone()[0]
    
    # Build lookup for normalizing manufacturer names from files
    mfr_lookup = build_manufacturer_lookup(canonical_manufacturers)

    # Load ThrustCurve motor metadata
    tc_metadata = load_motors_metadata()
    tc_motors = tc_metadata.get('motors', {})
    print(f"Loaded metadata for {len(tc_motors)} motors from ThrustCurve")

    # Build lookup by (manufacturer, designation) for matching
    metadata_lookup = {}
    for motor_id, motor_meta in tc_motors.items():
        mfr_name = motor_meta.get('manufacturer', '').lower()
        mfr_abbrev = motor_meta.get('manufacturerAbbrev', '').lower()
        designation = motor_meta.get('designation', '').lower()
        common_name = motor_meta.get('commonName', '').lower()
        
        for mfr_key in [mfr_name, mfr_abbrev]:
            if mfr_key:
                if designation:
                    metadata_lookup[(mfr_key, designation)] = motor_meta
                if common_name:
                    metadata_lookup[(mfr_key, common_name)] = motor_meta

    motor_count = 0
    curve_count = 0
    files_found = 0

    # Track inserted motors: tc_motor_id -> db_motor_id
    inserted_motors_by_tc_id = {}
    # Fallback: (mfr_id, designation) -> db_motor_id  
    inserted_motors_by_key = {}
    # Track inserted curves to avoid duplicates: tc_simfile_id -> db_curve_id
    inserted_curves = {}
    
    # Track stats by source directory
    source_stats = {}  # source_dir -> {'files': 0, 'motors': 0, 'curves': 0}

    # Traverse directory
    for root_dir, dirs, files in os.walk(DATA_DIR):
        for file in files:
            path = os.path.join(root_dir, file)
            lower_file = file.lower()

            # Determine source directory (first subdirectory under DATA_DIR)
            rel_path = os.path.relpath(root_dir, DATA_DIR)
            source_dir = rel_path.split(os.sep)[0] if rel_path != '.' else 'root'
            
            # Initialize source stats if needed
            if source_dir not in source_stats:
                source_stats[source_dir] = {'files': 0, 'motors': 0, 'curves': 0}

            parsed_meta = None
            points = None
            file_fmt = None

            # 1. Determine parser based on extension
            if lower_file.endswith(".eng") or lower_file.endswith(".rasp"):
                files_found += 1
                source_stats[source_dir]['files'] += 1
                parsed_meta, points = parse_rasp(path)
                file_fmt = 'RASP'
            elif lower_file.endswith(".rse"):
                files_found += 1
                source_stats[source_dir]['files'] += 1
                parsed_meta, points = parse_rse(path)
                file_fmt = 'RSE'
            else:
                continue

            if not parsed_meta or not points:
                print(f"  [Skipped] Unparseable: {file}")
                continue

            try:
                # Get parsed values
                parsed_mfr = parsed_meta['manufacturer'].lower().strip()
                parsed_designation = parsed_meta['designation'].lower().strip()
                
                # Extract simfile info from filename
                simfile_id, simfile_info = extract_simfile_info_from_filename(file, simfile_mapping)
                
                # Try to find ThrustCurve motor metadata
                tc_meta = None
                tc_motor_id = None
                
                if simfile_info and simfile_info.get('motorId'):
                    tc_motor_id = simfile_info['motorId']
                    if tc_motor_id in tc_motors:
                        tc_meta = tc_motors[tc_motor_id]
                
                # Fallback: try manufacturer + designation lookup
                if not tc_meta:
                    normalized_mfr = parsed_mfr.replace('_', ' ').strip()
                    for mfr_key in [parsed_mfr, normalized_mfr, parsed_mfr.split()[0], normalized_mfr.split()[0]]:
                        lookup_key = (mfr_key, parsed_designation)
                        if lookup_key in metadata_lookup:
                            tc_meta = metadata_lookup[lookup_key]
                            tc_motor_id = tc_meta.get('motorId')
                            break
                
                # Normalize manufacturer name
                normalized_mfr = parsed_mfr.replace('_', ' ').strip()
                canonical = mfr_lookup.get(parsed_mfr)
                if not canonical:
                    canonical = mfr_lookup.get(normalized_mfr)
                if not canonical:
                    canonical = mfr_lookup.get(parsed_mfr.split()[0])
                if not canonical:
                    canonical = mfr_lookup.get(normalized_mfr.split()[0])
                
                # Get manufacturer info
                if tc_meta and tc_meta.get('manufacturer'):
                    mfr_name = tc_meta.get('manufacturer')
                    mfr_abbrev = tc_meta.get('manufacturerAbbrev')
                elif canonical:
                    mfr_name, mfr_abbrev = canonical
                else:
                    # Unknown manufacturer - assign to "Unknown" category
                    print(f"  [Warning] Unknown manufacturer '{parsed_meta['manufacturer']}' in {file} -> assigning to 'Unknown'")
                    mfr_name = 'Unknown'
                    mfr_abbrev = 'UNK'

                # Get manufacturer ID
                if mfr_name in mfr_name_to_id:
                    mfr_id = mfr_name_to_id[mfr_name]
                else:
                    cursor.execute("INSERT OR IGNORE INTO manufacturers (name, abbrev) VALUES (?, ?)",
                                   (mfr_name, mfr_abbrev))
                    cursor.execute("SELECT id FROM manufacturers WHERE name = ?", (mfr_name,))
                    result = cursor.fetchone()
                    if result is None:
                        print(f"  [Skipped] Failed to insert manufacturer '{mfr_name}' for {file}")
                        continue
                    mfr_id = result[0]
                    mfr_name_to_id[mfr_name] = mfr_id

                designation = tc_meta.get('designation', parsed_meta['designation']) if tc_meta else parsed_meta['designation']
                motor_key = (mfr_id, designation)
                
                # Check if motor already exists
                db_motor_id = None
                if tc_motor_id and tc_motor_id in inserted_motors_by_tc_id:
                    db_motor_id = inserted_motors_by_tc_id[tc_motor_id]
                elif motor_key in inserted_motors_by_key:
                    db_motor_id = inserted_motors_by_key[motor_key]
                
                # Insert motor if not exists
                if db_motor_id is None:
                    # RASP/RSE header values ALWAYS override API data for these fields:
                    # - common_name, diameter, length, delays, propellant_weight, total_weight
                    # This is because the API data can be missing or incorrect, while the
                    # header line in the actual data file is authoritative.
                    
                    if tc_meta:
                        cursor.execute("""
                            INSERT INTO motors
                            (manufacturer_id, tc_motor_id, designation, common_name, impulse_class,
                             diameter, length, total_impulse, avg_thrust, max_thrust, burn_time,
                             propellant_weight, total_weight, type, delays, case_info, prop_info,
                             sparky, info_url, data_files, updated_on)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            mfr_id,
                            tc_meta.get('motorId'),
                            tc_meta.get('designation', parsed_meta['designation']),
                            # Override from parsed header:
                            parsed_meta.get('common_name') or tc_meta.get('commonName'),
                            tc_meta.get('impulseClass'),
                            # Override from parsed header:
                            parsed_meta['diameter'],
                            parsed_meta['length'],
                            # Impulse/thrust stats from API (calculated from official data)
                            tc_meta.get('totImpulseNs'),
                            tc_meta.get('avgThrustN'),
                            tc_meta.get('maxThrustN'),
                            tc_meta.get('burnTimeS'),
                            # Override from parsed header:
                            parsed_meta.get('prop_weight') or tc_meta.get('propWeightG'),
                            parsed_meta.get('total_weight') or tc_meta.get('totalWeightG'),
                            tc_meta.get('type', parsed_meta.get('type', 'SU')),
                            # Override from parsed header:
                            parsed_meta.get('delays') or tc_meta.get('delays'),
                            tc_meta.get('caseInfo'),
                            tc_meta.get('propInfo'),
                            1 if tc_meta.get('sparky') else 0,
                            tc_meta.get('infoUrl'),
                            tc_meta.get('dataFiles'),
                            tc_meta.get('updatedOn'),
                        ))
                    else:
                        # No TC metadata - use all parsed values
                        calc_impulse, calc_avg_thrust, calc_max_thrust, calc_burn_time = calculate_thrust_stats(points)
                        cursor.execute("""
                            INSERT INTO motors
                            (manufacturer_id, tc_motor_id, designation, common_name, impulse_class,
                             diameter, length, total_impulse, avg_thrust, max_thrust, burn_time,
                             propellant_weight, total_weight, type, delays, case_info, prop_info,
                             sparky, info_url, data_files, updated_on)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            mfr_id, None,
                            parsed_meta['designation'],
                            parsed_meta.get('common_name'),
                            None,
                            parsed_meta['diameter'],
                            parsed_meta['length'],
                            calc_impulse, calc_avg_thrust, calc_max_thrust, calc_burn_time,
                            parsed_meta.get('prop_weight'),
                            parsed_meta.get('total_weight'),
                            parsed_meta.get('type', 'SU'),
                            parsed_meta.get('delays'),
                            None, None, 0, None, None, None,
                        ))
                    
                    db_motor_id = cursor.lastrowid
                    if tc_motor_id:
                        inserted_motors_by_tc_id[tc_motor_id] = db_motor_id
                    inserted_motors_by_key[motor_key] = db_motor_id
                    motor_count += 1
                    source_stats[source_dir]['motors'] += 1

                # Skip if this simfile was already inserted
                if simfile_id and simfile_id in inserted_curves:
                    continue
                
                # Calculate curve-specific stats
                calc_impulse, calc_avg_thrust, calc_max_thrust, calc_burn_time = calculate_thrust_stats(points)
                
                # Insert thrust curve
                cursor.execute("""
                    INSERT INTO thrust_curves
                    (motor_id, tc_simfile_id, source, format, license, info_url, data_url,
                     total_impulse, avg_thrust, max_thrust, burn_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    db_motor_id,
                    simfile_id,
                    simfile_info.get('source') if simfile_info else None,
                    simfile_info.get('format', file_fmt) if simfile_info else file_fmt,
                    simfile_info.get('license') if simfile_info else None,
                    simfile_info.get('infoUrl') if simfile_info else None,
                    simfile_info.get('dataUrl') if simfile_info else None,
                    calc_impulse,
                    calc_avg_thrust,
                    calc_max_thrust,
                    calc_burn_time,
                ))
                
                curve_id = cursor.lastrowid
                if simfile_id:
                    inserted_curves[simfile_id] = curve_id
                curve_count += 1
                source_stats[source_dir]['curves'] += 1

                # Insert thrust data points
                data_rows = [(curve_id, p[0], p[1]) for p in points]
                cursor.executemany(
                    "INSERT INTO thrust_data (curve_id, time_seconds, force_newtons) VALUES (?,?,?)",
                                   data_rows)

            except Exception as e:
                import traceback
                print(f"  [Error] Failed to insert {file}: {e}")
                traceback.print_exc()

    # Print summary
    print(f"\n{'='*60}")
    print(f"BUILD SUMMARY")
    print(f"{'='*60}")
    print(f"{'Source':<25} {'Files':>8} {'Motors':>8} {'Curves':>8}")
    print(f"{'-'*60}")
    for source, stats in sorted(source_stats.items()):
        print(f"{source:<25} {stats['files']:>8} {stats['motors']:>8} {stats['curves']:>8}")
    print(f"{'-'*60}")
    print(f"{'TOTAL':<25} {files_found:>8} {motor_count:>8} {curve_count:>8}")
    print(f"{'='*60}\n")

    if motor_count == 0:
        print("Warning: No motors imported. Check your data directory contents.")

    schema_version = 2  # Bumped for new thrust_curves table
    database_version = int(datetime.now().strftime("%Y%m%d%H%M%S"))
    generated_at = datetime.now().isoformat()

    cursor.executemany(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        [
            ("schema_version", str(schema_version)),
            ("database_version", str(database_version)),
            ("generated_at", generated_at),
            ("motor_count", str(motor_count)),
            ("curve_count", str(curve_count)),
        ],
    )

    # Commit the transaction before running VACUUM
    conn.commit()

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
        "schema_version": schema_version,
        "database_version": database_version,
        "generated_at": generated_at,
        "motor_count": motor_count,
        "curve_count": curve_count,
        "sha256": sha256.hexdigest(),
        "download_url": "https://openrocket.github.io/motor-database/motors.db.gz"
    }

    with open(METADATA_FILE, 'w') as f:
        json.dump(meta, f, indent=2)

    print(f"Build complete: {GZ_NAME}")


if __name__ == "__main__":
    build()
