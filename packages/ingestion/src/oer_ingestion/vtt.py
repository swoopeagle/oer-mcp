"""WebVTT subtitle → plain transcript text.

Khan video transcripts (Kolibri, S2/D16) arrive as WebVTT. Strip the header,
cue numbers, timestamps, and speaker tags ("- [Voiceover]"); join cue text into
readable prose, collapsing the consecutive duplicate lines VTT often carries.
"""

from __future__ import annotations

import re

_TS = re.compile(r"-->")
_SPEAKER = re.compile(r"^-?\s*\[[^\]]+\]\s*")  # "- [Voiceover] ", "[instructor] "
_TAG = re.compile(r"</?[^>]+>")  # inline <c>/<i> style tags


def vtt_to_text(vtt: str) -> str:
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or _TS.search(line):
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            continue
        if line.isdigit():  # cue sequence number
            continue
        line = _TAG.sub("", line)
        line = _SPEAKER.sub("", line).strip()
        if line:
            lines.append(line)

    # Join cue lines into text; drop immediate duplicates (common in VTT).
    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return " ".join(out).strip()
