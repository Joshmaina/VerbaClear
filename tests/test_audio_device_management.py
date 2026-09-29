"""
Unit and Integration Tests for Hardware Audio Device Management,
Real-Time Waveform Visualizer Telemetry, and Transcript Exporters.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, orchestrator
from src.domain.models import TranscribedSegment
from src.infrastructure.audio.capture import PortAudioSource
from src.infrastructure.export.transcript_exporter import (
    generate_plain_transcript,
    generate_srt,
    generate_vtt,
)


@pytest.fixture(autouse=True)
def reset_orchestrator():
    """Ensure clean orchestrator state before each test."""
    orchestrator.is_stage_blackout = False
    with orchestrator._history_lock:
        orchestrator._session_history.clear()
        orchestrator._transcript_segments.clear()
    yield


def test_portaudio_device_enumeration_and_info():
    """Tests that audio devices can be queried safely without crashing headless runners."""
    devices = PortAudioSource.list_devices()
    assert isinstance(devices, list)

    source = PortAudioSource(device_index=None)
    info = source.get_current_device_info()
    assert isinstance(info, dict)
    assert "name" in info


def test_audio_device_selection_in_orchestrator():
    """Tests that the orchestrator can list and switch devices."""
    devices = orchestrator.list_audio_devices()
    assert isinstance(devices, list)

    # Setting None selects default input
    success = orchestrator.select_audio_device(None)
    assert success is True


def test_rest_api_audio_device_endpoints():
    """Tests GET /api/control/audio/devices and POST /api/control/audio/device."""
    with TestClient(app) as client:
        # GET devices
        res = client.get("/api/control/audio/devices")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert "devices" in data
        assert "currentDeviceName" in data

        # POST select device
        res = client.post("/api/control/audio/device", json={"deviceIndex": None})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["deviceIndex"] is None
        assert "deviceName" in data


def test_telemetry_contains_waveform_and_device_info():
    """Tests that telemetry includes real-time waveform array and device metadata."""
    telemetry = orchestrator.get_telemetry()
    assert "waveform" in telemetry
    assert isinstance(telemetry["waveform"], list)
    assert len(telemetry["waveform"]) == 32
    assert "currentDeviceName" in telemetry
    assert "totalTranscriptSegments" in telemetry


def test_transcript_exporters_unit():
    """Tests VTT, SRT, and plain text transcript generators with precise formatting."""
    segments = [
        TranscribedSegment(
            text="Welcome to the keynote symposium.",
            start_time_s=1.5,
            end_time_s=4.2,
            confidence=0.98,
            words=["Welcome", "to", "the", "keynote", "symposium."],
        ),
        TranscribedSegment(
            text="The fiscal topology is remarkably labyrinthine.",
            start_time_s=5.0,
            end_time_s=9.75,
            confidence=0.95,
            words=["The", "fiscal", "topology", "is", "remarkably", "labyrinthine."],
        ),
    ]

    # 1. WebVTT
    vtt = generate_vtt(segments)
    assert "WEBVTT" in vtt
    assert "00:00:01.500 --> 00:00:04.200" in vtt
    assert "Welcome to the keynote symposium." in vtt
    assert "00:00:05.000 --> 00:00:09.750" in vtt
    assert "The fiscal topology is remarkably labyrinthine." in vtt

    # 2. SubRip (SRT)
    srt = generate_srt(segments)
    assert "1\n00:00:01,500 --> 00:00:04,200\nWelcome to the keynote symposium." in srt
    assert "2\n00:00:05,000 --> 00:00:09,750\nThe fiscal topology is remarkably labyrinthine." in srt

    # 3. Plain Text
    txt = generate_plain_transcript(segments)
    assert "[00:00:01] Welcome to the keynote symposium." in txt
    assert "[00:00:05] The fiscal topology is remarkably labyrinthine." in txt


def test_rest_api_transcript_and_session_report():
    """Tests GET /api/export/session-report and GET /api/export/transcript endpoints."""
    with TestClient(app) as client:
        # Initially empty transcript -> 400
        res = client.get("/api/export/transcript?format=vtt")
        assert res.status_code == 400

        # Inject synthetic segments
        seg1 = TranscribedSegment(
            text="The enterprise platform architecture is robust.",
            start_time_s=0.5,
            end_time_s=3.0,
            confidence=0.99,
            words=["The", "enterprise", "platform", "architecture", "is", "robust."],
        )
        seg2 = TranscribedSegment(
            text="It operates with obfuscated cryptographic protocols.",
            start_time_s=3.5,
            end_time_s=7.0,
            confidence=0.97,
            words=["It", "operates", "with", "obfuscated", "cryptographic", "protocols."],
        )
        orchestrator.add_transcript_segment(seg1)
        orchestrator.add_transcript_segment(seg2)

        # GET session report
        res = client.get("/api/export/session-report")
        assert res.status_code == 200
        report = res.json()
        assert report["totalSpeechSegments"] == 2
        assert report["totalWordsSpoken"] == 12
        assert report["uniqueWordsSpoken"] >= 10
        assert report["lexicalDiversityTTR"] > 0.0

        # GET transcript VTT
        res = client.get("/api/export/transcript?format=vtt")
        assert res.status_code == 200
        assert "text/vtt" in res.headers["content-type"]
        assert "WEBVTT" in res.text
        assert "enterprise platform architecture" in res.text

        # GET transcript SRT
        res = client.get("/api/export/transcript?format=srt")
        assert res.status_code == 200
        assert "00:00:00,500 --> 00:00:03,000" in res.text

        # GET transcript TXT
        res = client.get("/api/export/transcript?format=txt")
        assert res.status_code == 200
        assert "[00:00:00] The enterprise platform architecture is robust." in res.text
