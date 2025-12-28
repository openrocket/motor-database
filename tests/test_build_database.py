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
    assert meta["delays"] == "5-10-15"
    assert meta["prop_weight"] == pytest.approx(53.0)
    assert meta["total_weight"] == pytest.approx(68.0)
    assert meta["manufacturer"] == "Test Motors"
    assert points == [(0.0, 5.0), (0.5, 0.0)]


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
    assert meta0["delays"] is None
    assert meta1["description"] == "Next motor"
    assert meta1["delays"] is None


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


def test_calculate_thrust_stats():
    points = [(0.0, 0.0), (1.0, 10.0), (2.0, 0.0)]
    impulse, avg_thrust, max_thrust, burn_time = build_db.calculate_thrust_stats(points)

    assert impulse == pytest.approx(10.0)
    assert avg_thrust == pytest.approx(5.0)
    assert max_thrust == pytest.approx(10.0)
    assert burn_time == pytest.approx(2.0)


def test_extract_simfile_info_from_filename():
    mapping = {"abcdef123456abcdef123456": "motor-1"}
    sim_id, info = build_db.extract_simfile_info_from_filename(
        "foo_abcdef123456abcdef123456.eng", mapping
    )
    assert sim_id == "abcdef123456abcdef123456"
    assert info == {"motorId": "motor-1"}


def test_build_creates_database_and_metadata(tmp_path, monkeypatch):
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
