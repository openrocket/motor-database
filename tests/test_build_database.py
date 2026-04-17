import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_database.py"
spec = importlib.util.spec_from_file_location("build_database", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load build_database module")
build_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_db)


def setup_sample_data(tmp_path):
    data_dir = tmp_path / "data"
    manual_dir = data_dir / "manual"
    manual_dir.mkdir(parents=True)

    rasp_content = (
        "; First line\n"
        "; Second line\n"
        "F32 29 124 0 0.05 0.07 Test Motors\n"
        "0 5\n"
        "0.5 0\n"
    )
    (manual_dir / "test.eng").write_text(rasp_content)

    rse_content = (
        "<engine-database>"
        "<engine-list>"
        "<engine code=\"G64W\" mfg=\"RSE Co\" dia=\"29\" len=\"150\" "
        "propWt=\"30\" initWt=\"60\" delays=\"0\">"
        "<data>"
        "<eng-data t=\"0.0\" f=\"0.0\" />"
        "<eng-data t=\"0.2\" f=\"20.0\" />"
        "<eng-data t=\"0.4\" f=\"0.0\" />"
        "</data>"
        "</engine>"
        "</engine-list>"
        "</engine-database>"
    )
    (manual_dir / "test.rse").write_text(rse_content)

    tc_dir = data_dir / "thrustcurve.org"
    tc_dir.mkdir(parents=True)
    (tc_dir / "motors_metadata.json").write_text('{"motors": {}}')
    (tc_dir / "simfile_to_motor.json").write_text("{}")
    (tc_dir / "manufacturers.json").write_text(
        json.dumps(
            {
                "manufacturers": [
                    {"name": "Test Motors", "abbrev": "TM"},
                    {"name": "RSE Co", "abbrev": "RSE"},
                ]
            }
        )
    )

    return data_dir, tc_dir


def test_parse_rasp_parses_header_and_data(tmp_path):
    content = (
        "; comment\n"
        "F32 29 124 5-10-15 0.053 0.068 Test Motors\n"
        "0.0 5\n"
        "0.5 0\n"
    )
    path = tmp_path / "motor.eng"
    path.write_text(content)

    meta, points = build_db.parse_rasp(str(path))

    assert meta["common_name"] == "F32"
    assert meta["diameter"] == 29.0
    assert meta["delays"] == "5,10,15"
    assert meta["prop_weight"] == pytest.approx(53.0)
    assert meta["total_weight"] == pytest.approx(68.0)
    assert meta["manufacturer"] == "Test Motors"
    assert points == [(0.0, 0.0), (0.0, 5.0), (0.5, 0.0)]


def test_parse_rasp_prepends_zero_point_when_missing(tmp_path):
    content = (
        "F32 29 124 5-10-15 0.053 0.068 Test Motors\n"
        "0.05 5\n"
        "0.5 0\n"
    )
    path = tmp_path / "motor.eng"
    path.write_text(content)

    _, points = build_db.parse_rasp(str(path))

    assert points == [(0.0, 0.0), (0.05, 5.0), (0.5, 0.0)]


def test_parse_rasp_all_handles_multiple_motors_and_comments(tmp_path):
    content = (
        "; First line\n"
        "; Second line\n"
        "F32 29 124 0 0.05 0.07 Test Motors\n"
        "0 5\n"
        "0.5 0\n"
        "; Next motor\n"
        "G64 29 150 P 0.08 0.1 Test Motors\n"
        "0 10\n"
        "0.6 0\n"
    )
    path = tmp_path / "multi.eng"
    path.write_text(content)

    motors = build_db.parse_rasp_all(str(path))

    assert len(motors) == 2
    meta0 = motors[0][0]
    meta1 = motors[1][0]
    assert meta0["description"] == "First line Second line"
    assert meta0["delays"] == "0"
    assert meta1["description"] == "Next motor"
    assert meta1["delays"] == "P"
    assert motors[0][1][0] == (0.0, 0.0)
    assert motors[1][1][0] == (0.0, 0.0)


def test_parse_rse_parses_single_engine(tmp_path):
    content = (
        "<engine-database>"
        "<engine-list>"
        "<engine code=\"H128W\" mfg=\"RSE Co\" dia=\"38\" len=\"200\" "
        "propWt=\"50\" initWt=\"90\" delays=\"6,10\">"
        "<data>"
        "<eng-data t=\"0.0\" f=\"0.0\" />"
        "<eng-data t=\"0.3\" f=\"15.0\" />"
        "<eng-data t=\"0.6\" f=\"0.0\" />"
        "</data>"
        "</engine>"
        "</engine-list>"
        "</engine-database>"
    )
    path = tmp_path / "motor.rse"
    path.write_text(content)

    meta, points = build_db.parse_rse(str(path))

    assert meta["designation"] == "H128W"
    assert meta["common_name"] == "H128"
    assert meta["manufacturer"] == "RSE Co"
    assert meta["diameter"] == 38.0
    assert meta["length"] == 200.0
    assert meta["prop_weight"] == 50.0
    assert meta["total_weight"] == 90.0
    assert meta["delays"] == "6,10"
    assert len(points) == 3


def test_parse_rse_all_parses_multiple_engines(tmp_path):
    content = (
        "<engine-database>"
        "<engine-list>"
        "<engine code=\"G64W\" mfg=\"RSE Co\" dia=\"29\" len=\"150\" "
        "propWt=\"30\" initWt=\"60\" delays=\"0\">"
        "<data>"
        "<eng-data t=\"0.0\" f=\"0.0\" />"
        "<eng-data t=\"0.2\" f=\"20.0\" />"
        "<eng-data t=\"0.4\" f=\"0.0\" />"
        "</data>"
        "</engine>"
        "<engine code=\"H128W\" mfg=\"RSE Co\" dia=\"38\" len=\"200\" "
        "propWt=\"50\" initWt=\"90\" delays=\"6,10\">"
        "<data>"
        "<eng-data t=\"0.0\" f=\"0.0\" />"
        "<eng-data t=\"0.3\" f=\"15.0\" />"
        "<eng-data t=\"0.6\" f=\"0.0\" />"
        "</data>"
        "</engine>"
        "</engine-list>"
        "</engine-database>"
    )
    path = tmp_path / "multi.rse"
    path.write_text(content)

    motors = build_db.parse_rse_all(str(path))

    assert len(motors) == 2
    assert motors[0][0]["designation"] == "G64W"
    assert motors[1][0]["designation"] == "H128W"


def test_simplify_common_name():
    assert build_db.simplify_common_name("B6-0") == "B6"
    assert build_db.simplify_common_name("B6W") == "B6"
    assert build_db.simplify_common_name("H128W") == "H128"
    assert build_db.simplify_common_name("B6") == "B6"
    assert build_db.simplify_common_name("C6") == "C6"
    assert build_db.simplify_common_name("RCS 18/20") == "RCS 18/20"
    assert build_db.simplify_common_name(None) is None
    assert build_db.simplify_common_name("") == ""


def test_normalize_designation_strips_delay_suffix():
    assert build_db.normalize_designation("B6-0") == "B6"
    assert build_db.normalize_designation("C6-3") == "C6"
    assert build_db.normalize_designation("B6-P") == "B6"
    assert build_db.normalize_designation("B6") == "B6"
    assert build_db.normalize_designation("RCS 18/20") == "RCS 18/20"
    assert build_db.normalize_designation(None) is None


def test_parse_rasp_delays_normalized(tmp_path):
    cases = [
        ("5-10-15", "5,10,15"),
        ("0", "0"),
        ("P", "P"),
        ("p", "P"),
        ("3", "3"),
    ]
    for raw, expected in cases:
        content = f"F32 29 124 {raw} 0.05 0.07 Test Motors\n0 5\n0.5 0\n"
        path = tmp_path / f"motor_{raw}.eng"
        path.write_text(content)
        meta, _ = build_db.parse_rasp(str(path))
        assert meta["delays"] == expected, f"Expected {expected!r} for input {raw!r}, got {meta['delays']!r}"


def test_parse_rse_delays_normalized(tmp_path):
    def make_rse(delays_attr):
        return (
            "<engine-database><engine-list>"
            f"<engine code=\"G64W\" mfg=\"RSE Co\" dia=\"29\" len=\"150\" "
            f"propWt=\"30\" initWt=\"60\" delays=\"{delays_attr}\">"
            "<data><eng-data t=\"0.0\" f=\"0.0\" /><eng-data t=\"0.2\" f=\"20.0\" />"
            "<eng-data t=\"0.4\" f=\"0.0\" /></data></engine>"
            "</engine-list></engine-database>"
        )
    cases = [("5-10-15", "5,10,15"), ("0", "0"), ("P", "P"), ("6,10", "6,10")]
    for raw, expected in cases:
        path = tmp_path / f"motor_{raw}.rse"
        path.write_text(make_rse(raw))
        meta, _ = build_db.parse_rse(str(path))
        assert meta["delays"] == expected, f"Expected {expected!r} for input {raw!r}, got {meta['delays']!r}"


def test_calculate_thrust_stats():
    points = [(0.0, 0.0), (1.0, 10.0), (2.0, 0.0)]
    impulse, avg_thrust, max_thrust, burn_time = build_db.calculate_thrust_stats(points)

    assert impulse == pytest.approx(10.0)
    assert avg_thrust == pytest.approx(5.0)
    assert max_thrust == pytest.approx(10.0)
    assert burn_time == pytest.approx(2.0)


def test_merge_delays_combines_unique_values():
    assert build_db.merge_delays("0,5", "5-10", "P") == "0,5,10,P"
    assert build_db.merge_delays(None, "", "0") == "0"
    assert build_db.merge_delays(None, "") is None


def test_extract_simfile_info_from_filename():
    mapping = {"abcdef123456abcdef123456": "motor-1"}
    sim_id, info = build_db.extract_simfile_info_from_filename(
        "foo_abcdef123456abcdef123456.eng", mapping
    )
    assert sim_id == "abcdef123456abcdef123456"
    assert info == {"motorId": "motor-1"}


def test_build_creates_database_and_metadata(tmp_path, monkeypatch):
    data_dir, tc_dir = setup_sample_data(tmp_path)

    db_path = tmp_path / "motors.db"
    gz_path = tmp_path / "motors.db.gz"
    meta_path = tmp_path / "metadata.json"
    build_state_path = tmp_path / "state" / "last_build.json"
    schema_path = Path(__file__).resolve().parents[1] / "schema" / "V1__initial_schema.sql"

    monkeypatch.setattr(build_db, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(build_db, "DB_NAME", str(db_path))
    monkeypatch.setattr(build_db, "GZ_NAME", str(gz_path))
    monkeypatch.setattr(build_db, "METADATA_FILE", str(meta_path))
    monkeypatch.setattr(build_db, "BUILD_STATE_FILE", str(build_state_path))
    monkeypatch.setattr(build_db, "SCHEMA_FILE", str(schema_path))
    monkeypatch.setattr(build_db, "MOTORS_METADATA_FILE", str(tc_dir / "motors_metadata.json"))
    monkeypatch.setattr(build_db, "MANUFACTURERS_FILE", str(tc_dir / "manufacturers.json"))
    monkeypatch.setattr(build_db, "SIMFILE_MAPPING_FILE", str(tc_dir / "simfile_to_motor.json"))

    build_db.build()

    assert db_path.exists()
    assert gz_path.exists()
    assert meta_path.exists()

    metadata = json.loads(meta_path.read_text())
    assert metadata["motor_count"] == 2
    assert metadata["curve_count"] == 2
    assert "last_checked" in metadata

    sha = hashlib.sha256(gz_path.read_bytes()).hexdigest()
    assert metadata["sha256"] == sha

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM motors")
        assert cursor.fetchone()[0] == 2
        cursor.execute("SELECT COUNT(*) FROM thrust_curves")
        assert cursor.fetchone()[0] == 2
        cursor.execute("SELECT description, source FROM motors WHERE designation = 'F32'")
        description, source = cursor.fetchone()
        assert description == "First line Second line"
        assert source == "manual"


def test_build_reuses_version_when_state_matches(tmp_path, monkeypatch):
    data_dir, tc_dir = setup_sample_data(tmp_path)

    db_path = tmp_path / "motors.db"
    gz_path = tmp_path / "motors.db.gz"
    meta_path = tmp_path / "metadata.json"
    build_state_path = tmp_path / "state" / "last_build.json"
    schema_path = Path(__file__).resolve().parents[1] / "schema" / "V1__initial_schema.sql"

    monkeypatch.setattr(build_db, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(build_db, "DB_NAME", str(db_path))
    monkeypatch.setattr(build_db, "GZ_NAME", str(gz_path))
    monkeypatch.setattr(build_db, "METADATA_FILE", str(meta_path))
    monkeypatch.setattr(build_db, "BUILD_STATE_FILE", str(build_state_path))
    monkeypatch.setattr(build_db, "SCHEMA_FILE", str(schema_path))
    monkeypatch.setattr(build_db, "MOTORS_METADATA_FILE", str(tc_dir / "motors_metadata.json"))
    monkeypatch.setattr(build_db, "MANUFACTURERS_FILE", str(tc_dir / "manufacturers.json"))
    monkeypatch.setattr(build_db, "SIMFILE_MAPPING_FILE", str(tc_dir / "simfile_to_motor.json"))

    source_hash = build_db.compute_source_hash()
    build_state_path.parent.mkdir(parents=True, exist_ok=True)
    build_state = {
        "source_hash": source_hash,
        "database_version": 20240102030405,
        "generated_at": "2024-01-02T03:04:05",
        "motor_count": 2,
        "curve_count": 2,
        "sha256": "deadbeef",
    }
    build_state_path.write_text(json.dumps(build_state))

    build_db.build()

    metadata = json.loads(meta_path.read_text())
    assert metadata["database_version"] == build_state["database_version"]
    assert metadata["generated_at"] == build_state["generated_at"]


def test_build_force_rebuilds_when_state_matches(tmp_path, monkeypatch):
    data_dir, tc_dir = setup_sample_data(tmp_path)

    db_path = tmp_path / "motors.db"
    gz_path = tmp_path / "motors.db.gz"
    meta_path = tmp_path / "metadata.json"
    build_state_path = tmp_path / "state" / "last_build.json"
    schema_path = Path(__file__).resolve().parents[1] / "schema" / "V1__initial_schema.sql"

    monkeypatch.setattr(build_db, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(build_db, "DB_NAME", str(db_path))
    monkeypatch.setattr(build_db, "GZ_NAME", str(gz_path))
    monkeypatch.setattr(build_db, "METADATA_FILE", str(meta_path))
    monkeypatch.setattr(build_db, "BUILD_STATE_FILE", str(build_state_path))
    monkeypatch.setattr(build_db, "SCHEMA_FILE", str(schema_path))
    monkeypatch.setattr(build_db, "MOTORS_METADATA_FILE", str(tc_dir / "motors_metadata.json"))
    monkeypatch.setattr(build_db, "MANUFACTURERS_FILE", str(tc_dir / "manufacturers.json"))
    monkeypatch.setattr(build_db, "SIMFILE_MAPPING_FILE", str(tc_dir / "simfile_to_motor.json"))

    source_hash = build_db.compute_source_hash()
    build_state_path.parent.mkdir(parents=True, exist_ok=True)
    build_state_path.write_text(
        json.dumps(
            {
                "source_hash": source_hash,
                "database_version": 20240102030405,
                "generated_at": "2024-01-02T03:04:05",
                "motor_count": 2,
                "curve_count": 2,
                "sha256": "deadbeef",
            }
        )
    )

    db_path.write_text("not a sqlite database")
    gz_path.write_text("not a gzip file")

    build_db.build(force=True)

    metadata = json.loads(meta_path.read_text())
    assert metadata["database_version"] != 20240102030405
    assert metadata["generated_at"] != "2024-01-02T03:04:05"
    assert metadata["sha256"] != "deadbeef"

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM motors")
        assert cursor.fetchone()[0] == 2


def test_build_merges_delays_and_keeps_distinct_tc_curves(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    tc_dir = data_dir / "thrustcurve.org" / "Acme"
    tc_dir.mkdir(parents=True)

    (data_dir / "thrustcurve.org" / "motors_metadata.json").write_text(
        json.dumps(
            {
                "motors": {
                    "motor-1": {
                        "motorId": "motor-1",
                        "manufacturer": "Acme",
                        "manufacturerAbbrev": "AC",
                        "designation": "G64W",
                        "commonName": "G64",
                        "impulseClass": "G",
                        "diameter": 29,
                        "length": 150,
                        "type": "SU",
                        "avgThrustN": 64,
                        "maxThrustN": 100,
                        "totImpulseNs": 120,
                        "burnTimeS": 1.9,
                        "dataFiles": 2,
                        "delays": "0",
                        "updatedOn": "2025-01-01",
                    }
                }
            }
        )
    )
    (data_dir / "thrustcurve.org" / "manufacturers.json").write_text(
        json.dumps({"manufacturers": [{"name": "Acme", "abbrev": "AC"}]})
    )
    (data_dir / "thrustcurve.org" / "simfile_to_motor.json").write_text(
        json.dumps(
            {
                "abcdef123456abcdef123456": {
                    "motorId": "motor-1",
                    "format": "RASP",
                    "source": "cert",
                },
                "fedcba654321fedcba654321": {
                    "motorId": "motor-1",
                    "format": "RockSim",
                    "source": "mfr",
                },
            }
        )
    )
    (tc_dir / "G64_abcdef123456abcdef123456.eng").write_text(
        "G64 29 150 0 0.08 0.10 Acme\n0.0 10\n0.6 0\n"
    )
    (tc_dir / "G64_fedcba654321fedcba654321.rse").write_text(
        "<engine-database><engine-list><engine code=\"G64W\" mfg=\"Acme\" dia=\"29\" len=\"150\" "
        "propWt=\"80\" initWt=\"100\" delays=\"4,7\"><data>"
        "<eng-data t=\"0.0\" f=\"12.0\" /><eng-data t=\"0.7\" f=\"0.0\" />"
        "</data></engine></engine-list></engine-database>"
    )

    db_path = tmp_path / "motors.db"
    gz_path = tmp_path / "motors.db.gz"
    meta_path = tmp_path / "metadata.json"
    build_state_path = tmp_path / "state" / "last_build.json"
    schema_path = Path(__file__).resolve().parents[1] / "schema" / "V1__initial_schema.sql"

    monkeypatch.setattr(build_db, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(build_db, "DB_NAME", str(db_path))
    monkeypatch.setattr(build_db, "GZ_NAME", str(gz_path))
    monkeypatch.setattr(build_db, "METADATA_FILE", str(meta_path))
    monkeypatch.setattr(build_db, "BUILD_STATE_FILE", str(build_state_path))
    monkeypatch.setattr(build_db, "SCHEMA_FILE", str(schema_path))
    monkeypatch.setattr(build_db, "MOTORS_METADATA_FILE", str(data_dir / "thrustcurve.org" / "motors_metadata.json"))
    monkeypatch.setattr(build_db, "MANUFACTURERS_FILE", str(data_dir / "thrustcurve.org" / "manufacturers.json"))
    monkeypatch.setattr(build_db, "SIMFILE_MAPPING_FILE", str(data_dir / "thrustcurve.org" / "simfile_to_motor.json"))

    build_db.build()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT delays FROM motors WHERE tc_motor_id = 'motor-1'")
        assert cursor.fetchone()[0] == "0,4,7"
        cursor.execute("SELECT COUNT(*) FROM thrust_curves WHERE motor_id = (SELECT id FROM motors WHERE tc_motor_id = 'motor-1')")
        assert cursor.fetchone()[0] == 2


def test_build_deduplicates_identical_tc_curves(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    tc_dir = data_dir / "thrustcurve.org" / "Acme"
    tc_dir.mkdir(parents=True)

    (data_dir / "thrustcurve.org" / "motors_metadata.json").write_text(
        json.dumps(
            {
                "motors": {
                    "motor-1": {
                        "motorId": "motor-1",
                        "manufacturer": "Acme",
                        "manufacturerAbbrev": "AC",
                        "designation": "G64W",
                        "commonName": "G64",
                        "dataFiles": 2,
                        "delays": "0",
                    }
                }
            }
        )
    )
    (data_dir / "thrustcurve.org" / "manufacturers.json").write_text(
        json.dumps({"manufacturers": [{"name": "Acme", "abbrev": "AC"}]})
    )
    (data_dir / "thrustcurve.org" / "simfile_to_motor.json").write_text(
        json.dumps(
            {
                "abcdef123456abcdef123456": {"motorId": "motor-1", "format": "RASP"},
                "fedcba654321fedcba654321": {"motorId": "motor-1", "format": "RockSim"},
            }
        )
    )
    curve_points = "0.0 10\n0.6 0\n"
    (tc_dir / "G64_abcdef123456abcdef123456.eng").write_text(
        "G64 29 150 0 0.08 0.10 Acme\n" + curve_points
    )
    (tc_dir / "G64_fedcba654321fedcba654321.rse").write_text(
        "<engine-database><engine-list><engine code=\"G64W\" mfg=\"Acme\" dia=\"29\" len=\"150\" "
        "propWt=\"80\" initWt=\"100\" delays=\"7\"><data>"
        "<eng-data t=\"0.0\" f=\"10.0\" /><eng-data t=\"0.6\" f=\"0.0\" />"
        "</data></engine></engine-list></engine-database>"
    )

    db_path = tmp_path / "motors.db"
    gz_path = tmp_path / "motors.db.gz"
    meta_path = tmp_path / "metadata.json"
    build_state_path = tmp_path / "state" / "last_build.json"
    schema_path = Path(__file__).resolve().parents[1] / "schema" / "V1__initial_schema.sql"

    monkeypatch.setattr(build_db, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(build_db, "DB_NAME", str(db_path))
    monkeypatch.setattr(build_db, "GZ_NAME", str(gz_path))
    monkeypatch.setattr(build_db, "METADATA_FILE", str(meta_path))
    monkeypatch.setattr(build_db, "BUILD_STATE_FILE", str(build_state_path))
    monkeypatch.setattr(build_db, "SCHEMA_FILE", str(schema_path))
    monkeypatch.setattr(build_db, "MOTORS_METADATA_FILE", str(data_dir / "thrustcurve.org" / "motors_metadata.json"))
    monkeypatch.setattr(build_db, "MANUFACTURERS_FILE", str(data_dir / "thrustcurve.org" / "manufacturers.json"))
    monkeypatch.setattr(build_db, "SIMFILE_MAPPING_FILE", str(data_dir / "thrustcurve.org" / "simfile_to_motor.json"))

    build_db.build()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT delays FROM motors WHERE tc_motor_id = 'motor-1'")
        assert cursor.fetchone()[0] == "0,7"
        cursor.execute("SELECT COUNT(*) FROM thrust_curves WHERE motor_id = (SELECT id FROM motors WHERE tc_motor_id = 'motor-1')")
        assert cursor.fetchone()[0] == 1


def test_build_estes_e6_merges_delays_and_keeps_two_distinct_curves(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    tc_dir = data_dir / "thrustcurve.org" / "Estes Industries"
    tc_dir.mkdir(parents=True)

    (data_dir / "thrustcurve.org" / "motors_metadata.json").write_text(
        json.dumps(
            {
                "motors": {
                    "estes-e6": {
                        "motorId": "estes-e6",
                        "manufacturer": "Estes Industries",
                        "manufacturerAbbrev": "Estes",
                        "designation": "E6",
                        "commonName": "E6",
                        "impulseClass": "E",
                        "diameter": 24,
                        "length": 95,
                        "type": "SU",
                        "avgThrustN": 6,
                        "maxThrustN": 13,
                        "totImpulseNs": 28,
                        "burnTimeS": 4.5,
                        "dataFiles": 2,
                        "delays": "P",
                        "updatedOn": "2026-04-18",
                    }
                }
            }
        )
    )
    (data_dir / "thrustcurve.org" / "manufacturers.json").write_text(
        json.dumps({"manufacturers": [{"name": "Estes Industries", "abbrev": "Estes"}]})
    )
    (data_dir / "thrustcurve.org" / "simfile_to_motor.json").write_text(
        json.dumps(
            {
                "abcdef123456abcdef123456": {
                    "motorId": "estes-e6",
                    "format": "RASP",
                    "source": "cert",
                },
                "fedcba654321fedcba654321": {
                    "motorId": "estes-e6",
                    "format": "RockSim",
                    "source": "mfr",
                },
            }
        )
    )
    (tc_dir / "E6_abcdef123456abcdef123456.eng").write_text(
        "E6 24 95 0-3-5-7 0.021 0.043 Estes\n"
        "0.0 8.0\n"
        "0.8 12.0\n"
        "4.0 0.0\n"
    )
    (tc_dir / "E6_fedcba654321fedcba654321.rse").write_text(
        "<engine-database><engine-list><engine code=\"E6\" mfg=\"Estes\" dia=\"24\" len=\"95\" "
        "propWt=\"21\" initWt=\"43\" delays=\"P\"><data>"
        "<eng-data t=\"0.0\" f=\"6.5\" />"
        "<eng-data t=\"1.0\" f=\"10.5\" />"
        "<eng-data t=\"4.6\" f=\"0.0\" />"
        "</data></engine></engine-list></engine-database>"
    )

    db_path = tmp_path / "motors.db"
    gz_path = tmp_path / "motors.db.gz"
    meta_path = tmp_path / "metadata.json"
    build_state_path = tmp_path / "state" / "last_build.json"
    schema_path = Path(__file__).resolve().parents[1] / "schema" / "V1__initial_schema.sql"

    monkeypatch.setattr(build_db, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(build_db, "DB_NAME", str(db_path))
    monkeypatch.setattr(build_db, "GZ_NAME", str(gz_path))
    monkeypatch.setattr(build_db, "METADATA_FILE", str(meta_path))
    monkeypatch.setattr(build_db, "BUILD_STATE_FILE", str(build_state_path))
    monkeypatch.setattr(build_db, "SCHEMA_FILE", str(schema_path))
    monkeypatch.setattr(build_db, "MOTORS_METADATA_FILE", str(data_dir / "thrustcurve.org" / "motors_metadata.json"))
    monkeypatch.setattr(build_db, "MANUFACTURERS_FILE", str(data_dir / "thrustcurve.org" / "manufacturers.json"))
    monkeypatch.setattr(build_db, "SIMFILE_MAPPING_FILE", str(data_dir / "thrustcurve.org" / "simfile_to_motor.json"))

    build_db.build()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.delays, COUNT(tc.id)
            FROM motors m
            JOIN thrust_curves tc ON tc.motor_id = m.id
            WHERE m.tc_motor_id = 'estes-e6'
            GROUP BY m.id
            """
        )
        delays, curve_count = cursor.fetchone()

    assert delays == "0,3,5,7,P"
    assert curve_count == 2
