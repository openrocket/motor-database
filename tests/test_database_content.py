"""
Integration tests that verify the content of the built motors.db.
These tests guard against regressions in motor deduplication and common-name
normalization introduced by build_database.py.

The tests run against the motors.db produced by `build_database.py`.  If the
database has not been built yet the tests are skipped automatically.
"""
import sqlite3
from pathlib import Path

import pytest

DB_PATH = Path(__file__).resolve().parents[1] / "motors.db"


@pytest.fixture(scope="module")
def db_conn():
    if not DB_PATH.exists():
        pytest.skip(f"motors.db not found at {DB_PATH} — run build_database.py first")
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()


def test_estes_b6_single_entry_with_correct_common_name(db_conn):
    """
    The Estes B6 motor must appear as exactly one row with designation 'B6' and
    common_name 'B6'.  Before the build-pipeline fix, two rows existed — one with
    designation 'B6' and one with 'B6-0' — because some source files embedded the
    ejection delay in the designation.  The common name was also incorrectly stored
    as 'B6-0' rather than 'B6'.
    """
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT m.designation, m.common_name
        FROM motors m
        JOIN manufacturers mfr ON m.manufacturer_id = mfr.id
        WHERE (mfr.abbrev = 'Estes' OR mfr.name LIKE '%Estes%')
          AND m.designation = 'B6'
    """)
    rows = cursor.fetchall()

    assert len(rows) == 1, (
        f"Expected exactly one Estes motor with designation 'B6', found {len(rows)}: {rows}"
    )
    designation, common_name = rows[0]
    assert common_name == "B6", (
        f"Estes B6 common_name should be 'B6', got '{common_name}'"
    )


def test_quest_b6w_common_name(db_conn):
    """
    The Quest B6W motor must have designation 'B6W' and common_name 'B6'.
    The propellant-code suffix ('W' = White Lightning) must not appear in the
    common name.
    """
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT m.designation, m.common_name
        FROM motors m
        JOIN manufacturers mfr ON m.manufacturer_id = mfr.id
        WHERE (mfr.abbrev = 'Quest' OR mfr.name LIKE '%Quest%')
          AND m.designation = 'B6W'
    """)
    rows = cursor.fetchall()

    assert len(rows) >= 1, "No Quest motor with designation 'B6W' found in motors.db"
    for designation, common_name in rows:
        assert common_name == "B6", (
            f"Quest B6W common_name should be 'B6', got '{common_name}'"
        )
