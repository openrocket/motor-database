-- Enable foreign keys
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS manufacturers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    abbrev TEXT
);

CREATE TABLE IF NOT EXISTS motors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL,
    designation TEXT NOT NULL,
    common_name TEXT,
    diameter REAL, -- mm
    length REAL, -- mm
    impulse REAL, -- Ns
    avg_thrust REAL, -- N
    burn_time REAL, -- s
    propellant_weight REAL, -- kg
    total_weight REAL, -- kg
    type TEXT, -- e.g. SU (Single Use), RE (Reload)
    data_file_format TEXT, -- 'RASP', 'RSE', etc.
    last_updated_source TEXT,
    FOREIGN KEY (manufacturer_id) REFERENCES manufacturers(id)
);

CREATE TABLE IF NOT EXISTS thrust_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motor_id INTEGER NOT NULL,
    time_seconds REAL NOT NULL,
    force_newtons REAL NOT NULL,
    FOREIGN KEY (motor_id) REFERENCES motors(id) ON DELETE CASCADE
);

-- Indices for fast lookups in OpenRocket
CREATE INDEX idx_motor_mfr ON motors(manufacturer_id);
CREATE INDEX idx_motor_diameter ON motors(diameter);
CREATE INDEX idx_motor_impulse ON motors(impulse);