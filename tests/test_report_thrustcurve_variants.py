import base64
import importlib.util
from pathlib import Path

import requests


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "report_thrustcurve_variants.py"
spec = importlib.util.spec_from_file_location("report_thrustcurve_variants", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load report_thrustcurve_variants module")
report_variants = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report_variants)


class DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def encode_text(text):
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def test_build_variant_summary_uses_file_delays_and_curve_stats():
    motor_meta = {
        "designation": "F32",
        "commonName": "F32",
        "manufacturer": "Test Motors",
        "diameter": 29,
        "length": 124,
        "delays": "0,3,5",
        "propWeightG": 50,
        "totalWeightG": 70,
    }
    result = {
        "simfileId": "sim-1",
        "format": "RASP",
        "source": "cert",
        "license": "PD",
        "dataUrl": "https://example.com/download/Test_F32.eng",
        "data": encode_text("F32 29 124 0-5 0.05 0.07 Test Motors\n0 5\n0.5 0\n"),
        "samples": [{"time": 0.0, "thrust": 5.0}, {"time": 0.5, "thrust": 0.0}],
    }

    summary = report_variants.build_variant_summary(result, motor_meta)

    assert summary["delays"] == "0,5"
    assert summary["filename"] == "Test_F32.eng"
    assert summary["point_count"] == 2
    assert summary["burn_time_s"] == 0.5
    assert summary["total_impulse_ns"] == 1.25
    assert summary["curve_fingerprint"] is not None


def test_build_variant_summary_absolutizes_thrustcurve_urls():
    motor_meta = {
        "designation": "F32",
        "commonName": "F32",
        "manufacturer": "Test Motors",
    }
    result = {
        "simfileId": "sim-1",
        "format": "RASP",
        "infoUrl": "/simfiles/sim-1/",
        "dataUrl": "/simfiles/sim-1/download/data.eng",
        "data": encode_text("F32 29 124 0 0.05 0.07 Test Motors\n0 5\n0.5 0\n"),
    }

    summary = report_variants.build_variant_summary(result, motor_meta)

    assert summary["info_url"] == "https://www.thrustcurve.org/simfiles/sim-1/"
    assert summary["data_url"] == "https://www.thrustcurve.org/simfiles/sim-1/download/data.eng"


def test_collect_variant_differences_flags_only_focused_fields():
    variants = [
        {
            "format": "RASP",
            "source": "cert",
            "license": "PD",
            "designation": "F32",
            "common_name": "F32",
            "manufacturer": "Test Motors",
            "diameter_mm": 29.0,
            "length_mm": 124.0,
            "delays": "0,3,5",
            "propellant_weight_g": 50.0,
            "total_weight_g": 70.0,
            "point_count": 10,
            "burn_time_s": 1.2,
            "total_impulse_ns": 42.1,
            "avg_thrust_n": 35.08,
            "max_thrust_n": 55.0,
            "curve_fingerprint": "abc123",
        },
        {
            "format": "RockSim",
            "source": "user",
            "license": "free",
            "designation": "F32",
            "common_name": "F32",
            "manufacturer": "Test Motors",
            "diameter_mm": 29.0,
            "length_mm": 124.0,
            "delays": "0,5",
            "propellant_weight_g": 50.0,
            "total_weight_g": 70.0,
            "point_count": 12,
            "burn_time_s": 1.15,
            "total_impulse_ns": 41.5,
            "avg_thrust_n": 36.08,
            "max_thrust_n": 57.0,
            "curve_fingerprint": "def456",
        },
    ]

    focused = report_variants.summarize_focused_differences(variants)
    differences = {difference["key"] for difference in focused}

    assert "delays" in differences
    assert "designation" not in differences
    assert "burn_time_s" in differences
    assert "total_impulse_ns" in differences
    assert "curve_fingerprint" in differences


def test_collect_variant_differences_ignores_sub_percent_burn_and_impulse_changes():
    variants = [
        {"designation": "F32", "delays": "0,3,5", "burn_time_s": 1.0, "total_impulse_ns": 40.0},
        {"designation": "F32", "delays": "0,3,5", "burn_time_s": 1.009, "total_impulse_ns": 40.39},
    ]

    focused = report_variants.summarize_focused_differences(variants)
    differences = {difference["key"] for difference in focused}

    assert "burn_time_s" not in differences
    assert "total_impulse_ns" not in differences


def test_generate_report_writes_html(tmp_path, monkeypatch):
    metadata_path = tmp_path / "motors_metadata.json"
    output_path = tmp_path / "report.html"
    metadata_path.write_text(
        """
        {
          "motors": {
            "motor-1": {
              "motorId": "motor-1",
              "manufacturer": "Test Motors",
              "manufacturerAbbrev": "TM",
              "designation": "F32",
              "commonName": "F32",
              "diameter": 29,
              "length": 124,
              "delays": "0,3,5",
              "propWeightG": 50,
              "totalWeightG": 70,
              "dataFiles": 2
            }
          }
        }
        """
    )

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url == report_variants.TC_API_DOWNLOAD
        assert json["motorIds"] == ["motor-1"]
        return DummyResponse(
            200,
            {
                "results": [
                    {
                        "motorId": "motor-1",
                        "simfileId": "sim-rasp",
                        "format": "RASP",
                        "source": "cert",
                        "license": "PD",
                        "dataUrl": "https://example.com/F32.eng",
                        "data": encode_text("F32 29 124 0-3-5 0.05 0.07 Test Motors\n0 5\n0.5 0\n"),
                        "samples": [{"time": 0.0, "thrust": 5.0}, {"time": 0.5, "thrust": 0.0}],
                    },
                    {
                        "motorId": "motor-1",
                        "simfileId": "sim-rse",
                        "format": "RockSim",
                        "source": "user",
                        "license": "free",
                        "dataUrl": "https://example.com/F32.rse",
                        "data": encode_text(
                            "<engine-database><engine-list><engine code=\"F32W\" mfg=\"Test Motors\" "
                            "dia=\"29\" len=\"124\" delays=\"0,5\" propWt=\"50\" initWt=\"70\">"
                            "<data><eng-data t=\"0.0\" f=\"5.0\" /><eng-data t=\"0.4\" f=\"0.0\" /></data>"
                            "</engine></engine-list></engine-database>"
                        ),
                        "samples": [{"time": 0.0, "thrust": 5.0}, {"time": 0.4, "thrust": 0.0}],
                    },
                ]
            },
        )

    monkeypatch.setattr(report_variants, "MOTORS_METADATA_FILE", str(metadata_path))
    monkeypatch.setattr(report_variants.requests, "post", fake_post)

    entries = report_variants.generate_report(str(output_path))

    assert len(entries) == 1
    assert entries[0]["has_differences"] is True
    content = output_path.read_text()
    assert "ThrustCurve Variant Report" in content
    assert "More details" in content
    assert "Test Motors" in content
    assert "F32" in content
    assert "Delays" in content
    assert "Curve" in content
    assert "Thrust curve comparison" in content
    assert "curve-plot" in content
    assert "F32.eng" in content
    assert "F32.rse" in content


def test_fetch_motor_variants_retries_transient_request_failures(monkeypatch):
    calls = {"count": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.exceptions.SSLError("EOF occurred in violation of protocol")
        return DummyResponse(200, {"results": [{"simfileId": "ok"}]})

    monkeypatch.setattr(report_variants.requests, "post", fake_post)
    monkeypatch.setattr(report_variants.time, "sleep", lambda _: None)

    results = report_variants.fetch_motor_variants("motor-1", max_results=5)

    assert calls["count"] == 3
    assert results == [{"simfileId": "ok"}]


def test_generate_report_skips_failed_motors(tmp_path, monkeypatch):
    metadata_path = tmp_path / "motors_metadata.json"
    output_path = tmp_path / "report.html"
    metadata_path.write_text(
        """
        {
          "motors": {
            "motor-1": {
              "motorId": "motor-1",
              "manufacturer": "Test Motors",
              "designation": "F32",
              "commonName": "F32",
              "dataFiles": 2
            },
            "motor-2": {
              "motorId": "motor-2",
              "manufacturer": "Bad Motors",
              "designation": "X1",
              "commonName": "X1",
              "dataFiles": 2
            }
          }
        }
        """
    )

    def fake_analyze_motor(motor_id, motor_meta, max_results):
        if motor_id == "motor-2":
            raise RuntimeError("TLS failure")
        return {
            "motor_id": motor_id,
            "motor_meta": motor_meta,
            "variants": [],
            "differences": [],
            "focused_differences": [],
            "difference_summary": "No differences",
            "has_differences": False,
        }

    monkeypatch.setattr(report_variants, "MOTORS_METADATA_FILE", str(metadata_path))
    monkeypatch.setattr(report_variants, "analyze_motor", fake_analyze_motor)

    entries = report_variants.generate_report(str(output_path))

    assert len(entries) == 1
    assert entries[0]["motor_id"] == "motor-1"
    assert output_path.exists()
