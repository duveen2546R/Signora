"""Byte-bounded immutable motion responses; no transcripts or audio stored here."""
from collections import OrderedDict
import hashlib
import json
import threading

_entries = OrderedDict()
_bytes = 0
_lock = threading.Lock()
MAX_BYTES = 32 * 1024 * 1024


def put(payload):
    global _bytes
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_BYTES:
        raise ValueError("Motion chunk exceeds live cache budget; use shorter lexical units")
    key = hashlib.sha256(encoded).hexdigest()
    with _lock:
        if key not in _entries:
            while _entries and _bytes + len(encoded) > MAX_BYTES:
                _, old = _entries.popitem(last=False)
                _bytes -= len(old)
            _entries[key] = encoded
            _bytes += len(encoded)
        _entries.move_to_end(key)
    return {"key": key, "byteSize": len(encoded), "url": f"/api/v1/live/motion/{key}"}


def get(key):
    with _lock:
        value = _entries.get(key)
        if value is not None:
            _entries.move_to_end(key)
        return value
