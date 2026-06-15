from oer_ingestion.adapters.khan import _cdn_url, _grade_band
from oer_ingestion.vtt import vtt_to_text

SAMPLE_VTT = """WEBVTT

NOTE this is a note

1
00:00.518 --> 00:03.350
- [Voiceover] Put seven
squirrels in the box.

2
00:03.350 --> 00:04.917
All right, so that's

3
00:04.917 --> 00:07.857
All right, so that's
"""


def test_vtt_strips_timestamps_speakers_and_dupes():
    out = vtt_to_text(SAMPLE_VTT)
    assert "-->" not in out and "WEBVTT" not in out
    assert "[Voiceover]" not in out  # speaker tag stripped
    assert out.startswith("Put seven squirrels in the box.")
    # consecutive duplicate cue collapsed to one
    assert out.count("All right, so that's") == 1


def test_vtt_empty():
    assert vtt_to_text("WEBVTT\n\n") == ""


def test_grade_band_mapping():
    assert _grade_band("Kindergarten") == "K-5"
    assert _grade_band("3rd grade") == "K-5"
    assert _grade_band("5th grade") == "K-5"
    assert _grade_band("6th grade") == "6-8"
    assert _grade_band("8th grade") == "6-8"
    assert _grade_band("Get ready for 6th grade") == "6-8"
    assert _grade_band("Algebra 1") == "9-12"
    assert _grade_band("High school geometry") == "9-12"
    assert _grade_band("Arithmetic") is None  # topic course, not grade-tagged


def test_cdn_url_sharding():
    assert _cdn_url("82e501e6b837cfb3232fbd7d4f1c319b") == (
        "https://studio.learningequality.org/content/storage/"
        "8/2/82e501e6b837cfb3232fbd7d4f1c319b.vtt"
    )
