-- Enable foreign keys
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manufacturers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    abbrev TEXT
);

CREATE TABLE IF NOT EXISTS motors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL,
    tc_motor_id TEXT,              -- ThrustCurve.org motor ID for reference
    designation TEXT NOT NULL,
    common_name TEXT,
    impulse_class TEXT,            -- e.g. "A", "B", "C", "D"
    diameter REAL,                 -- mm
    length REAL,                   -- mm
    total_impulse REAL,            -- Ns (totImpulseNs from ThrustCurve)
    avg_thrust REAL,               -- N (avgThrustN)
    max_thrust REAL,               -- N (maxThrustN)
    burn_time REAL,                -- s (burnTimeS)
    propellant_weight REAL,        -- g (propWeightG)
    total_weight REAL,             -- g (totalWeightG)
    type TEXT,                     -- e.g. "SU" (Single Use), "reload", "hybrid"
    delays TEXT,                   -- e.g. "0,3,5,7"
    case_info TEXT,                -- e.g. "RMS 40/120"
    prop_info TEXT,                -- e.g. "Blue Thunder"
    sparky INTEGER,                -- 0 or 1
    info_url TEXT,                 -- URL to more info (NAR, etc.)
    data_files INTEGER,            -- number of data files on ThrustCurve
    updated_on TEXT,               -- last update date from ThrustCurve
    FOREIGN KEY (manufacturer_id) REFERENCES manufacturers(id)
);

-- Each motor can have multiple thrust curves (simfiles)
CREATE TABLE IF NOT EXISTS thrust_curves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motor_id INTEGER NOT NULL,
    tc_simfile_id TEXT,            -- ThrustCurve.org simfile ID
    source TEXT,                   -- 'cert', 'mfr', 'user'
    format TEXT,                   -- 'RASP', 'RSE', etc.
    license TEXT,                  -- 'PD', 'free', 'other'
    info_url TEXT,                 -- ThrustCurve data info page
    data_url TEXT,                 -- ThrustCurve data download URL
    -- Calculated/parsed values from this specific curve
    total_impulse REAL,            -- Ns (calculated from curve)
    avg_thrust REAL,               -- N (calculated)
    max_thrust REAL,               -- N (calculated)
    burn_time REAL,                -- s (calculated)
    FOREIGN KEY (motor_id) REFERENCES motors(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS thrust_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    curve_id INTEGER NOT NULL,     -- Now references thrust_curves, not motors
    time_seconds REAL NOT NULL,
    force_newtons REAL NOT NULL,
    FOREIGN KEY (curve_id) REFERENCES thrust_curves(id) ON DELETE CASCADE
);

-- Indices for fast lookups
CREATE INDEX idx_motor_mfr ON motors(manufacturer_id);
CREATE INDEX idx_motor_diameter ON motors(diameter);
CREATE INDEX idx_motor_impulse ON motors(total_impulse);
CREATE INDEX idx_motor_impulse_class ON motors(impulse_class);
CREATE INDEX idx_motor_tc_id ON motors(tc_motor_id);
CREATE INDEX idx_curve_motor ON thrust_curves(motor_id);
CREATE INDEX idx_curve_simfile ON thrust_curves(tc_simfile_id);
CREATE INDEX idx_thrust_curve ON thrust_data(curve_id);
