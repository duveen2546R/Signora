from __future__ import annotations

import html
import re
from dataclasses import dataclass


MAX_SUBTITLE_BYTES = 5 * 1024 * 1024
MAX_CUES = 20_000
MAX_DURATION_MS = 4 * 60 * 60 * 1000
_TIMESTAMP = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{3})")
_TAG = re.compile(r"<[^>]+>")


class SubtitleError(ValueError):
    pass


@dataclass(frozen=True)
class CaptionCue:
    cue_id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str = ""


@dataclass(frozen=True)
class TranslationUnit:
    ordinal: int
    start_ms: int
    end_ms: int
    text: str
    normalized_text: str
    cue_ids: list[str]


def _time_ms(value: str) -> int:
    match = _TIMESTAMP.fullmatch(value.strip())
    if not match:
        raise SubtitleError(f"Invalid subtitle timestamp: {value}")
    hours = int(match.group(1) or 0)
    minutes, seconds, millis = map(int, match.groups()[1:])
    if minutes > 59 or seconds > 59:
        raise SubtitleError(f"Invalid subtitle timestamp: {value}")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def _clean_text(lines: list[str]) -> tuple[str, str]:
    raw = " ".join(line.strip() for line in lines if line.strip())
    speaker_match = re.search(r"<v(?:\.[^ >]+)?\s+([^>]+)>", raw, re.IGNORECASE)
    speaker = speaker_match.group(1).strip() if speaker_match else ""
    raw = re.sub(r"<br\s*/?>", " ", raw, flags=re.IGNORECASE)
    value = html.unescape(_TAG.sub("", raw))
    value = re.sub(r"\s+", " ", value).strip()
    if not speaker:
        named = re.match(r"^([A-Z][A-Z0-9 _-]{1,30}):\s+", value)
        speaker = named.group(1).strip() if named else ""
    return value, speaker


def _is_non_speech(text: str) -> bool:
    value = text.strip()
    return bool(
        re.fullmatch(r"(?:\[[^]]+]|\([^)]*\)|[♪♫♬\s]+)", value)
        or re.fullmatch(r"(?:music|applause|laughter|silence)", value, re.IGNORECASE)
    )


def parse_subtitles(filename: str, payload: bytes) -> list[CaptionCue]:
    if len(payload) > MAX_SUBTITLE_BYTES:
        raise SubtitleError("Subtitle file is larger than 5 MB.")
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in {"srt", "vtt"}:
        raise SubtitleError("Upload an SRT or WebVTT subtitle file.")
    try:
        source = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SubtitleError("Subtitle file must use UTF-8 encoding.") from exc
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", source.strip())
    cues: list[CaptionCue] = []
    for block_index, block in enumerate(blocks, start=1):
        lines = [line.strip("\ufeff") for line in block.splitlines()]
        if not lines or lines[0].strip().upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            if suffix == "srt":
                raise SubtitleError(f"Subtitle block {block_index} has no timing line.")
            continue
        timing = lines[timing_index].split("-->", 1)
        start_token = timing[0].strip()
        end_token = timing[1].strip().split()[0]
        start_ms, end_ms = _time_ms(start_token), _time_ms(end_token)
        if end_ms <= start_ms:
            raise SubtitleError(f"Subtitle block {block_index} ends before it starts.")
        cue_id = lines[0].strip() if timing_index else str(block_index)
        text, speaker = _clean_text(lines[timing_index + 1 :])
        if text and not _is_non_speech(text):
            cues.append(CaptionCue(cue_id, start_ms, end_ms, text, speaker))
    if not cues:
        raise SubtitleError("The subtitle file has no spoken captions.")
    if len(cues) > MAX_CUES:
        raise SubtitleError("Subtitle file contains more than 20,000 cues.")
    if max(cue.end_ms for cue in cues) > MAX_DURATION_MS:
        raise SubtitleError("Subtitle timeline is longer than four hours.")
    return _dedupe_rolling(sorted(cues, key=lambda cue: (cue.start_ms, cue.end_ms)))


def _dedupe_rolling(cues: list[CaptionCue]) -> list[CaptionCue]:
    result: list[CaptionCue] = []
    previous_words: list[str] = []
    previous_end = -1
    for cue in cues:
        words = cue.text.split()
        if previous_words and cue.start_ms <= previous_end + 250:
            overlap = 0
            for size in range(1, min(len(previous_words), len(words)) + 1):
                if [w.casefold() for w in previous_words[-size:]] == [w.casefold() for w in words[:size]]:
                    overlap = size
            words = words[overlap:]
        previous_words = cue.text.split()
        previous_end = max(previous_end, cue.end_ms)
        text = " ".join(words).strip()
        if text:
            result.append(CaptionCue(cue.cue_id, cue.start_ms, cue.end_ms, text, cue.speaker))
    return result


def build_translation_units(cues: list[CaptionCue]) -> list[TranslationUnit]:
    expanded: list[CaptionCue] = []
    for cue in cues:
        words = cue.text.split()
        if not words:
            continue
        chunk: list[str] = []
        chunk_start = cue.start_ms
        duration = cue.end_ms - cue.start_ms
        for index, word in enumerate(words):
            word_start = cue.start_ms + round(duration * index / len(words))
            candidate = " ".join([*chunk, word])
            if chunk and (len(candidate) > 120 or word_start - chunk_start >= 8_000):
                expanded.append(CaptionCue(cue.cue_id, chunk_start, word_start, " ".join(chunk), cue.speaker))
                chunk, chunk_start = [], word_start
            chunk.append(word)
        if chunk:
            expanded.append(CaptionCue(cue.cue_id, chunk_start, cue.end_ms, " ".join(chunk), cue.speaker))

    groups: list[list[CaptionCue]] = []
    for cue in expanded:
        if not groups:
            groups.append([cue])
            continue
        current = groups[-1]
        first, previous = current[0], current[-1]
        combined = " ".join([*(item.text for item in current), cue.text])
        can_join = (
            cue.start_ms - previous.end_ms < 700
            and cue.end_ms - first.start_ms <= 8_000
            and len(combined) <= 120
            and cue.speaker == previous.speaker
            and not re.search(r"[.!?][\"']?$", previous.text)
        )
        (current if can_join else groups.append([cue]))
        if can_join:
            current.append(cue)
    units: list[TranslationUnit] = []
    for ordinal, group in enumerate(groups):
        text = re.sub(r"\s+", " ", " ".join(cue.text for cue in group)).strip()
        normalized = re.sub(r"[^a-z0-9' ]+", " ", text.casefold())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        units.append(TranslationUnit(
            ordinal, group[0].start_ms, max(c.end_ms for c in group), text, normalized,
            [cue.cue_id for cue in group],
        ))
    return units
