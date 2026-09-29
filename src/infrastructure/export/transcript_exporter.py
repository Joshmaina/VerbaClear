"""
Transcript Exporter for VerbaClear.
Provides zero-dependency conversion of live transcribed segments into:
- WebVTT (.vtt) subtitle files for HTML5 video players and streaming platforms
- SubRip (.srt) subtitle files for broadcast editors (Premiere, DaVinci, Final Cut)
- Formatted Plain Text (.txt) transcripts with session timestamps
"""

from typing import List, Union
from src.domain.models import TranscribedSegment


def _format_timestamp(seconds: float, separator: str = ".") -> str:
    """
    Formats a floating-point seconds value into standard subtitle timecode:
    HH:MM:SS.mmm (WebVTT) or HH:MM:SS,mmm (SRT).
    """
    total_seconds = max(0.0, float(seconds))
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = int(total_seconds % 60)
    millis = int(round((total_seconds - int(total_seconds)) * 1000.0))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def generate_vtt(segments: List[Union[TranscribedSegment, dict]]) -> str:
    """
    Generates a standard W3C WebVTT document (.vtt) from transcribed speech segments.
    """
    lines = [
        "WEBVTT - VerbaClear Live Presentation Transcript",
        "",
    ]

    for idx, seg in enumerate(segments, start=1):
        if isinstance(seg, dict):
            text = seg.get("text", "").strip()
            start = seg.get("start_time_s", 0.0)
            end = seg.get("end_time_s", start + 2.0)
        else:
            text = getattr(seg, "text", "").strip()
            start = getattr(seg, "start_time_s", 0.0)
            end = getattr(seg, "end_time_s", start + 2.0)

        if not text:
            continue

        if end <= start:
            end = start + 1.5

        t_start = _format_timestamp(start, separator=".")
        t_end = _format_timestamp(end, separator=".")

        lines.append(f"{idx}")
        lines.append(f"{t_start} --> {t_end}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


def generate_srt(segments: List[Union[TranscribedSegment, dict]]) -> str:
    """
    Generates a standard SubRip subtitle document (.srt) from transcribed speech segments.
    """
    blocks = []

    for idx, seg in enumerate(segments, start=1):
        if isinstance(seg, dict):
            text = seg.get("text", "").strip()
            start = seg.get("start_time_s", 0.0)
            end = seg.get("end_time_s", start + 2.0)
        else:
            text = getattr(seg, "text", "").strip()
            start = getattr(seg, "start_time_s", 0.0)
            end = getattr(seg, "end_time_s", start + 2.0)

        if not text:
            continue

        if end <= start:
            end = start + 1.5

        t_start = _format_timestamp(start, separator=",")
        t_end = _format_timestamp(end, separator=",")

        block = f"{idx}\n{t_start} --> {t_end}\n{text}\n"
        blocks.append(block)

    return "\n".join(blocks)


def generate_plain_transcript(segments: List[Union[TranscribedSegment, dict]]) -> str:
    """
    Generates a clean human-readable plain text transcript with relative time markers.
    """
    lines = [
        "============================================================",
        "VerbaClear Session Presentation Transcript",
        "============================================================",
        "",
    ]

    for seg in segments:
        if isinstance(seg, dict):
            text = seg.get("text", "").strip()
            start = seg.get("start_time_s", 0.0)
        else:
            text = getattr(seg, "text", "").strip()
            start = getattr(seg, "start_time_s", 0.0)

        if not text:
            continue

        hours = int(start // 3600)
        minutes = int((start % 3600) // 60)
        secs = int(start % 60)
        timestamp = f"[{hours:02d}:{minutes:02d}:{secs:02d}]"

        lines.append(f"{timestamp} {text}")

    lines.append("")
    return "\n".join(lines)
