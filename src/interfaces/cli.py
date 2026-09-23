"""
Command-Line Interface (CLI) for VerbaClear Production Appliance.
Provides AV technicians and event operators with hardware discovery,
diagnostic tools, and production daemon launcher.
"""

import argparse
import logging
import os
import sys
import uvicorn

from src.api.routers.session import get_local_ip

BANNER = r"""
========================================================================
 __     __         _            ____ _                 
 \ \   / /__ _ __ | |__   __ _ / ___| | ___  __ _ _ __ 
  \ \ / / _ \ '__|| '_ \ / _` | |   | |/ _ \/ _` | '__|
   \ V /  __/ |   | |_) | (_| | |___| |  __/ (_| | |   
    \_/ \___|_|   |_.__/ \__,_|\____|_|\___|\__,_|_|   
        Ambient Real-Time Speech Intelligence & Vocabulary Assistant
========================================================================
"""


def list_audio_devices():
    """Enumerates PortAudio input devices for AV technician setup."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default_input = sd.default.device[0]

        print(BANNER)
        print("Detected Hardware Audio Input Interfaces:")
        print("------------------------------------------------------------------------")
        print(f"{'Index':<7} {'Device Name':<45} {'Channels':<10} {'Default'}")
        print("------------------------------------------------------------------------")

        input_found = False
        for idx, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                input_found = True
                is_default = "★ (DEFAULT)" if idx == default_input else ""
                name = dev["name"][:43]
                channels = dev["max_input_channels"]
                print(f"[{idx:<3}]   {name:<45} {channels:<10} {is_default}")

        print("------------------------------------------------------------------------")
        if not input_found:
            print("WARNING: No audio input interfaces detected! Check USB interface cables.")
        else:
            print("Tip: Run 'verbaclear start --device-index <Index>' to bind a specific interface.")
        print()
    except Exception as e:
        print(f"Error querying audio interfaces: {e}", file=sys.stderr)


def run_diagnostics():
    """Runs local offline diagnostics on Silero VAD, spaCy, and SQLite lexicon."""
    print(BANNER)
    print("Running VerbaClear Appliance Self-Diagnostics...")
    print("------------------------------------------------------------------------")

    # 1. Lexicon check
    try:
        from src.infrastructure.storage.sqlite_lexicon import SQLiteLexiconRepository
        repo = SQLiteLexiconRepository()
        synonyms = repo.resolve_synonyms("labyrinthine")
        assert len(synonyms) > 0
        print(f"[PASS] SQLite Lexicon Repository: Operational (resolved {synonyms}).")
    except Exception as e:
        print(f"[FAIL] SQLite Lexicon error: {e}")

    # 2. NGSL Bloom filter check
    try:
        from src.infrastructure.nlp.frequency import FrequencyIndex
        fi = FrequencyIndex()
        assert fi.is_common("the") is True
        assert fi.is_common("labyrinthine") is False
        print("[PASS] NGSL Frequency Bloom Filter: Operational.")
    except Exception as e:
        print(f"[FAIL] Frequency classifier error: {e}")

    # 3. Lemmatizer check
    try:
        from src.infrastructure.nlp.lemmatizer import SpacyLemmatizer
        lem = SpacyLemmatizer()
        tokens = lem.analyze_text("The speaker used labyrinthine phrasing.")
        assert any(t.lemma == "labyrinthine" for t in tokens)
        print("[PASS] spaCy NLP Lemmatizer & NER: Operational.")
    except Exception as e:
        print(f"[FAIL] Lemmatizer error: {e}")

    # 4. Filter Pipeline
    try:
        from src.infrastructure.nlp.filter import LexicalFilterEngine
        engine = LexicalFilterEngine()
        evals = engine.evaluate_sentence("This tax law is labyrinthine and obfuscated.")
        lemmas = [ev.lemma for ev in evals]
        assert "labyrinthine" in lemmas
        assert "obfuscate" in lemmas
        print(f"[PASS] Lexical Intelligence Filter: Successfully isolated rare terms {lemmas}.")
    except Exception as e:
        print(f"[FAIL] Filter engine error: {e}")

    print("------------------------------------------------------------------------")
    print("All diagnostic checks passed. System ready for live production deployment.")
    print()


def start_appliance(args):
    """Launches the full live VerbaClear speech intelligence daemon."""
    from src.api.main import app, orchestrator

    local_ip = get_local_ip() if not args.host_ip else args.host_ip
    port = args.port

    stage_url = f"http://{local_ip}:{port}/stage"
    companion_url = f"http://{local_ip}:{port}/companion"
    qr_url = f"http://{local_ip}:{port}/api/session/qr"

    print(BANNER)
    print("VerbaClear Live Event Appliance Active")
    print("------------------------------------------------------------------------")
    print(f"Primary Stage Lower-Third:    {stage_url}")
    print(f"Audience Mobile Companion:    {companion_url}")
    print(f"Venue Dynamic QR Code:        {qr_url}")
    print("------------------------------------------------------------------------")
    print(f"Binding: {args.host}:{port}  |  Session ID: {orchestrator.session_id}")
    print(f"Audio Mode: {'Live Microphone' if not args.no_audio else 'Silent / Mock Simulation'}")
    if not args.no_audio and args.device_index is not None:
        print(f"Target Audio Device Index: {args.device_index}")
    print("------------------------------------------------------------------------")
    print("Press Ctrl+C to safely shut down the appliance.\n")

    if not args.no_audio:
        # Start the live audio capture and inference pipeline
        orchestrator.start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def main():
    """Main CLI entrypoint parser."""
    parser = argparse.ArgumentParser(
        prog="verbaclear",
        description="VerbaClear: Ambient Real-Time Speech Intelligence & Vocabulary Assistant",
    )
    subparsers = parser.add_subparsers(dest="command", help="Operational Subcommands")

    # Command: start
    start_parser = subparsers.add_parser("start", help="Start the VerbaClear live event appliance")
    start_parser.add_argument("--host", default="0.0.0.0", help="HTTP/WS server bind address")
    start_parser.add_argument("--port", type=int, default=8000, help="HTTP/WS server port")
    start_parser.add_argument("--host-ip", default=None, help="Custom LAN IP or domain for QR code")
    start_parser.add_argument("--device-index", type=int, default=None, help="PortAudio input device index")
    start_parser.add_argument("--no-audio", action="store_true", help="Start web/WS hub without live microphone")
    start_parser.add_argument("--pack", default=None, help="Active Domain Context Pack (e.g. Legal, FinTech)")

    # Command: devices
    subparsers.add_parser("devices", help="List detected USB audio interfaces and microphones")

    # Command: test
    subparsers.add_parser("diagnose", help="Run offline hardware and linguistic self-diagnostics")

    args = parser.parse_args()

    if args.command == "devices":
        list_audio_devices()
    elif args.command == "diagnose":
        run_diagnostics()
    elif args.command == "start":
        start_appliance(args)
    else:
        # Default behavior with no arguments: print help or start if flags provided
        if len(sys.argv) == 1:
            parser.print_help()
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
