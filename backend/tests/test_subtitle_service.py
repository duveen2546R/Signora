import pytest

from app.services.subtitle_service import SubtitleError, build_translation_units, parse_subtitles


def test_srt_parses_bom_multiline_and_deduplicates_rolling_captions():
    data = ("\ufeff1\n00:00:01,000 --> 00:00:02,000\nHello\n\n"
            "2\n00:00:01,800 --> 00:00:03,000\nHello world\n").encode()
    cues = parse_subtitles("captions.srt", data)
    assert [cue.text for cue in cues] == ["Hello", "world"]
    units = build_translation_units(cues)
    assert len(units) == 1
    assert units[0].text == "Hello world"
    assert units[0].start_ms == 1000 and units[0].end_ms == 3000


def test_webvtt_handles_voice_tags_settings_and_non_speech():
    data = b"""WEBVTT\n\nintro\n00:00.000 --> 00:01.000 align:start\n<v Sam>Hello &amp; welcome</v>\n\n00:01.100 --> 00:02.000\n[Music]\n"""
    cues = parse_subtitles("captions.vtt", data)
    assert [(cue.text, cue.speaker) for cue in cues] == [("Hello & welcome", "Sam")]


@pytest.mark.parametrize("name,data", [
    ("captions.txt", b"text"),
    ("captions.srt", b"1\n00:00:02,000 --> 00:00:01,000\nWrong\n"),
])
def test_invalid_subtitles_are_rejected(name, data):
    with pytest.raises(SubtitleError):
        parse_subtitles(name, data)


def test_unit_boundaries_respect_punctuation_speaker_and_gap():
    data = b"""WEBVTT\n\n00:00.000 --> 00:01.000\nHello.\n\n00:01.050 --> 00:02.000\nFather\n\n00:03.000 --> 00:04.000\nThank you\n"""
    units = build_translation_units(parse_subtitles("x.vtt", data))
    assert [unit.text for unit in units] == ["Hello.", "Father", "Thank you"]


def test_one_oversized_caption_is_split_into_bounded_units():
    text = " ".join(["caption"] * 50)
    data = f"1\n00:00:00,000 --> 00:00:20,000\n{text}\n".encode()
    units = build_translation_units(parse_subtitles("x.srt", data))
    assert len(units) > 1
    assert all(len(unit.text) <= 120 and unit.end_ms - unit.start_ms <= 8_000 for unit in units)
