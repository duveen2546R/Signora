from types import SimpleNamespace
import struct

from fastapi.testclient import TestClient
import pytest

from app.services.streaming_speech import LexicalCommitter, SpeechSession, word_timings


def words(text, offset=0):
    return [{"text": word, "startMs": offset + i * 200, "endMs": offset + (i + 1) * 200}
            for i, word in enumerate(text.split())]


def test_only_new_decoder_results_stabilize_and_final_does_not_duplicate():
    state = LexicalCommitter()
    assert state.update(words("hello"), 200) == ([], False)
    units, _ = state.update(words("hello father"), 400)
    assert [unit["text"] for unit in units] == ["hello"]
    units, _ = state.update(words("hello father"), 500, final=True)
    assert [unit["text"] for unit in units] == ["father"]
    assert state.update(words("hello father"), 600, final=True) == ([], False)


def test_multiword_lookahead_is_bounded_and_repetitions_survive():
    state = LexicalCommitter([("good", "morning")])
    state.update(words("good"), 200)
    assert state.update(words("good"), 300)[0] == []
    state.update(words("good morning hello hello"), 400)
    units, _ = state.update(words("good morning hello hello"), 600)
    assert [unit["text"] for unit in units] == ["good morning", "hello", "hello"]
    timeout = LexicalCommitter([("good", "morning")])
    timeout.update(words("good"), 200)
    assert timeout.update(words("good"), 500)[0][0]["text"] == "good"


def test_correction_is_reported_once_without_replaying_committed_words():
    state = LexicalCommitter()
    state.update(words("hello father"), 400, final=True)
    assert state.update(words("hello mother"), 600) == ([], True)
    assert state.update(words("hello mother"), 800, final=True) == ([], False)


def test_token_timing_is_audio_based_and_unknown_alignment_is_explicit():
    result = SimpleNamespace(text="HELLO FATHER", tokens=["▁HE", "LLO", "▁FATHER"],
                             timestamps=[0.1, 0.2, 0.4], start_time=2)
    result_words = word_timings(result, 2500)
    assert result_words[0]["startMs"] == 2100
    assert result_words[1]["endMs"] == 2440
    result.tokens = ["HELLOFATHER"]
    assert word_timings(result, 2500)[0]["startMs"] is None


class FakeRecognizer:
    def create_stream(self):
        return SimpleNamespace(accept_waveform=lambda *_: None, input_finished=lambda: None)
    def is_ready(self, _stream):
        return False
    def is_endpoint(self, _stream):
        return False
    def get_result_all(self, _stream):
        return SimpleNamespace(text="", tokens=[], timestamps=[], start_time=0)


def test_decoder_flush_padding_does_not_advance_audio_clock():
    session = SpeechSession(FakeRecognizer())
    session.accept(bytes(640))
    session.accept(b"", final=True)
    assert session.samples == 320


def test_socket_rejects_foreign_origins():
    from app.main import app
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect('/api/v1/live/session', headers={'origin': 'https://foreign.invalid'}):
            pytest.fail("foreign origin accepted")


def test_socket_detects_packet_discontinuity_and_drains_stop(monkeypatch):
    from app.main import app
    from app.api.v1 import speech
    monkeypatch.setattr(speech.engine, "status", lambda: {"warm": True})
    monkeypatch.setattr(speech.engine, "recognizer", FakeRecognizer())
    monkeypatch.setattr(speech, "session_forms", lambda _: [])
    client = TestClient(app)
    with client.websocket_connect('/api/v1/live/session', headers={'origin': 'http://localhost:5173'}) as ws:
        ws.send_json({'type': 'start', 'streamId': 'test', 'generation': 0, 'libraryVersion': 'v'})
        assert ws.receive_json()['type'] == 'ready'
        ws.send_bytes(struct.pack('<Id', 0, 0) + bytes(640))
        ws.send_json({'type': 'stop'})
        assert ws.receive_json()['type'] == 'transcript'
        assert ws.receive_json()['type'] == 'stopped'
    with client.websocket_connect('/api/v1/live/session', headers={'origin': 'http://localhost:5173'}) as ws:
        ws.send_json({'type': 'start', 'streamId': 'test', 'generation': 0, 'libraryVersion': 'v'})
        ws.receive_json()
        ws.send_bytes(struct.pack('<Id', 1, 0) + bytes(640))
        assert 'discontinuity' in ws.receive_json()['message']
