import base64
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_updates.py"
spec = importlib.util.spec_from_file_location("fetch_updates", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load fetch_updates module")
fetch_updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_updates)


class DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_load_state_handles_missing_and_corrupt(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(fetch_updates, "STATE_LAST_UPDATE_FILE", str(state_file))

    state = fetch_updates.load_state()
    assert state["last_updated"] == "1970-01-01"

    state_file.write_text("{")
    state = fetch_updates.load_state()
    assert state["last_updated"] == "1970-01-01"


def test_save_and_load_motors_metadata(tmp_path, monkeypatch):
    meta_file = tmp_path / "data" / "motors_metadata.json"
    monkeypatch.setattr(fetch_updates, "MOTORS_METADATA_FILE", str(meta_file))

    payload = {"motors": {"m1": {"motorId": "m1"}}}
    fetch_updates.save_motors_metadata(payload)

    loaded = fetch_updates.load_motors_metadata()
    assert loaded == payload


def test_get_manufacturers_saves_list(tmp_path, monkeypatch):
    manuf_file = tmp_path / "data" / "manufacturers.json"
    monkeypatch.setattr(fetch_updates, "MANUFACTURERS_FILE", str(manuf_file))

    def fake_get(url, json=None, headers=None):
        assert url == fetch_updates.TC_API_METADATA
        return DummyResponse(200, {"manufacturers": [{"name": "Acme", "abbrev": "AC"}]})

    monkeypatch.setattr(fetch_updates.requests, "get", fake_get)

    names = fetch_updates.get_manufacturers()

    assert names == ["Acme"]
    saved = json.loads(manuf_file.read_text())
    assert saved["manufacturers"][0]["name"] == "Acme"


def test_download_motor_data_writes_files_and_mapping(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(fetch_updates, "DATA_DIR", str(data_dir))

    content = "F32 29 124 0 0.05 0.07 Test Motors\n0 5\n0.5 0\n"
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    def fake_post(url, json=None, headers=None):
        assert url == fetch_updates.TC_API_DOWNLOAD
        return DummyResponse(
            200,
            {
                "results": [
                    {
                        "data": encoded,
                        "simfileId": "abcdef123456abcdef123456",
                        "format": "RASP",
                        "source": "cert",
                        "license": "PD",
                        "infoUrl": "https://example.com/info",
                        "dataUrl": "https://example.com/data",
                    }
                ]
            },
        )

    monkeypatch.setattr(fetch_updates.requests, "post", fake_post)

    mapping = {}
    saved_count, simfile_ids = fetch_updates.download_motor_data(
        "motor-1", "Test Motors", "F32", mapping
    )

    assert saved_count == 1
    assert simfile_ids == ["abcdef123456abcdef123456"]
    assert "abcdef123456abcdef123456" in mapping

    saved_path = data_dir / "Test Motors" / "F32_abcdef123456abcdef123456.rasp"
    assert saved_path.exists()
    assert saved_path.read_text() == content


def test_fetch_motors_saves_metadata_mapping_and_state(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "thrustcurve.org"
    state_dir = tmp_path / "state"
    data_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)

    monkeypatch.setattr(fetch_updates, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(fetch_updates, "STATE_LAST_UPDATE_FILE", str(state_dir / "last_update.json"))
    monkeypatch.setattr(fetch_updates, "STATE_LAST_CHECK_FILE", str(state_dir / "last_check.json"))
    monkeypatch.setattr(
        fetch_updates,
        "MOTORS_METADATA_FILE",
        str(data_dir / "motors_metadata.json"),
    )
    monkeypatch.setattr(
        fetch_updates,
        "SIMFILE_MAPPING_FILE",
        str(data_dir / "simfile_to_motor.json"),
    )
    monkeypatch.setattr(
        fetch_updates,
        "MANUFACTURERS_FILE",
        str(data_dir / "manufacturers.json"),
    )

    def fake_get(url, json=None, headers=None):
        assert url == fetch_updates.TC_API_METADATA
        return DummyResponse(200, {"manufacturers": [{"name": "Acme", "abbrev": "AC"}]})

    content = "G64 29 150 0 0.08 0.1 Acme\n0 10\n0.6 0\n"
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    def fake_post(url, json=None, headers=None):
        if url == fetch_updates.TC_API_SEARCH:
            return DummyResponse(
                200,
                {
                    "results": [
                        {
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
                            "dataFiles": 1,
                            "infoUrl": "https://example.com/motor",
                            "totalWeightG": 100,
                            "propWeightG": 60,
                            "delays": "0",
                            "caseInfo": "single use",
                            "propInfo": "White",
                            "sparky": False,
                            "updatedOn": "2025-01-01",
                        }
                    ]
                },
            )
        if url == fetch_updates.TC_API_DOWNLOAD:
            return DummyResponse(
                200,
                {
                    "results": [
                        {
                            "data": encoded,
                            "simfileId": "abcdef123456abcdef123456",
                            "format": "RASP",
                            "source": "cert",
                            "license": "PD",
                            "infoUrl": "https://example.com/info",
                            "dataUrl": "https://example.com/data",
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(fetch_updates.requests, "get", fake_get)
    monkeypatch.setattr(fetch_updates.requests, "post", fake_post)
    monkeypatch.setattr(fetch_updates.time, "sleep", lambda _: None)

    fetch_updates.fetch_motors()

    metadata = json.loads((data_dir / "motors_metadata.json").read_text())
    assert "motor-1" in metadata["motors"]

    mapping = json.loads((data_dir / "simfile_to_motor.json").read_text())
    assert mapping["abcdef123456abcdef123456"]["motorId"] == "motor-1"

    saved_path = data_dir / "Acme" / "G64_abcdef123456abcdef123456.rasp"
    assert saved_path.exists()

    assert (state_dir / "last_update.json").exists()
    assert (state_dir / "last_check.json").exists()
