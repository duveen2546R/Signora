"""Local, incremental ASR. Audio time, not callback arrival time, drives signing.

The optional recognizer is loaded once. Each connection owns its own decoder state.
No microphone audio is persisted. Token timestamps are estimates, not aligner truth.
"""
from __future__ import annotations

import importlib.util
import threading

import numpy as np

from app.core.config import settings

MODEL_ID = "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17"
MODEL_FILES = {
    "encoder": "encoder-epoch-99-avg-1.int8.onnx",
    "decoder": "decoder-epoch-99-avg-1.onnx",
    "joiner": "joiner-epoch-99-avg-1.int8.onnx",
    "tokens": "tokens.txt",
}


class SpeechEngine:
    def __init__(self):
        self.recognizer = None
        self.error = None
        self.loading = False
        self.lock = threading.Lock()

    def status(self):
        missing = [name for name in MODEL_FILES.values()
                   if not (settings.speech_model_dir / name).is_file()]
        installed = importlib.util.find_spec("sherpa_onnx") is not None
        return {
            "modelId": MODEL_ID, "installed": installed, "missingFiles": missing,
            "state": "ready" if self.recognizer else "warming" if self.loading else
                     "error" if self.error else "not-installed" if missing or not installed else "cold",
            "warm": self.recognizer is not None, "error": self.error,
            "sampleRate": 16000, "packetMs": 20, "timestampQuality": "estimated-token-alignment",
            "latencyVerified": False,
        }

    def warm(self):
        with self.lock:
            if self.recognizer is not None:
                return self.status()
            if self.status()["missingFiles"] or not self.status()["installed"]:
                return self.status()
            self.loading = True
            try:
                import sherpa_onnx
                paths = {key: str(settings.speech_model_dir / name) for key, name in MODEL_FILES.items()}
                recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                    **paths, num_threads=settings.speech_threads, sample_rate=16000,
                    feature_dim=80, decoding_method="greedy_search", provider="cpu",
                    enable_endpoint_detection=True, rule1_min_trailing_silence=2.4,
                    rule2_min_trailing_silence=0.8, rule3_min_utterance_length=20,
                )
                stream = recognizer.create_stream()
                stream.accept_waveform(16000, np.zeros(16000, dtype=np.float32))
                while recognizer.is_ready(stream):
                    recognizer.decode_stream(stream)
                self.recognizer = recognizer
                self.error = None
            except Exception as exc:
                self.error = f"Local recognizer could not start: {exc}"
            finally:
                self.loading = False
        return self.status()


engine = SpeechEngine()


def word_timings(result, audio_ms):
    """Group BPE token times into words; do not invent exact acoustic endpoints."""
    words = result.text.lower().strip().split()
    if not words:
        return []
    starts = []
    base = float(getattr(result, "start_time", 0)) * 1000
    for token, timestamp in zip(result.tokens, result.timestamps):
        if not starts or token.startswith(("▁", " ")):
            starts.append(base + float(timestamp) * 1000)
    if len(starts) != len(words):
        # Some models expose character tokens rather than word boundaries. Mark uncertainty;
        # never present callback time as accurate word timing.
        return [{"text": word, "startMs": None, "endMs": audio_ms} for word in words]
    ends = starts[1:] + [min(audio_ms, base + float(result.timestamps[-1]) * 1000 + 40)]
    return [{"text": word, "startMs": start, "endMs": max(start, end)}
            for word, start, end in zip(words, starts, ends)]


class LexicalCommitter:
    """Stable prefix across actual decoder updates, with bounded alias lookahead."""
    def __init__(self, forms=()):
        self.forms = sorted(set(tuple(f) for f in forms if len(f) > 1), key=lambda f: (-len(f), f))
        self.previous = []
        self.committed = []
        self.seen_at = []
        self.conflict_reported = False

    def update(self, words, audio_ms, final=False):
        text = [word["text"] for word in words]
        shared = 0
        while shared < min(len(text), len(self.previous)) and text[shared] == self.previous[shared]:
            shared += 1
        self.seen_at = [self.seen_at[i] if i < shared else audio_ms for i in range(len(text))]
        correction = text[:len(self.committed)] != self.committed
        if correction:
            notify = not self.conflict_reported
            self.conflict_reported = True
            self.previous = text
            return [], notify
        limit = len(text) if final else shared
        at = len(self.committed)
        units = []
        while at < limit:
            form = next((f for f in self.forms if tuple(text[at:at + len(f)]) == f
                         and at + len(f) <= limit), None)
            if not final and not form:
                suffix = text[at:limit]
                if any(len(f) > len(suffix) and list(f[:len(suffix)]) == suffix for f in self.forms):
                    if audio_ms - self.seen_at[at] < 300:
                        break
            count = len(form) if form else 1
            group = words[at:at + count]
            units.append({"text": " ".join(w["text"] for w in group), "words": group,
                          "sourceStartMs": group[0]["startMs"], "sourceEndMs": group[-1]["endMs"],
                          "observedAudioMs": self.seen_at[at], "early": not final})
            self.committed.extend(text[at:at + count])
            at += count
        self.previous = text
        return units, False


class SpeechSession:
    def __init__(self, recognizer, forms=()):
        self.recognizer = recognizer
        self.stream = recognizer.create_stream()
        self.forms = forms
        self.committer = LexicalCommitter(forms)
        self.samples = 0
        self.segment = 0
        self.sequence = 0

    def accept(self, pcm: bytes, final=False):
        if pcm:
            self.stream.accept_waveform(16000, np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768)
            self.samples += len(pcm) // 2
        if final:
            # Required decoder lookahead, excluded from the source audio clock.
            self.stream.accept_waveform(16000, np.zeros(8000, dtype=np.float32))
            self.stream.input_finished()
        events = []
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
            events.extend(self._result(False))
        endpoint = self.recognizer.is_endpoint(self.stream)
        if final or endpoint:
            events.extend(self._result(True))
            if not final:
                self.recognizer.reset(self.stream)
                self.committer = LexicalCommitter(self.forms)
                self.segment += 1
        return events

    def _result(self, final):
        result = self.recognizer.get_result_all(self.stream)
        audio_ms = self.samples / 16
        words = word_timings(result, audio_ms)
        units, correction = self.committer.update(words, audio_ms, final)
        events = [{"type": "transcript", "text": result.text, "final": final,
                   "segment": self.segment, "audioMs": audio_ms}]
        if correction:
            events.append({"type": "correction", "message":
                           "Recognition revised committed words. Corrected text is shown; signs were not replayed."})
        for unit in units:
            events.append({"type": "commit", "sequence": self.sequence, **unit})
            self.sequence += 1
        return events
