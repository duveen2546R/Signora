#!/usr/bin/env python3
"""Download the fixed Apache-2.0 English streaming model; never run on a live request."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.services.streaming_speech import MODEL_FILES, MODEL_ID, engine


def main():
    destination = settings.speech_model_dir
    destination.mkdir(parents=True, exist_ok=True)
    if not all((destination / name).is_file() for name in MODEL_FILES.values()):
        url = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{MODEL_ID}.tar.bz2"
        print(f"Downloading {MODEL_ID} from its publisher…", flush=True)
        with tempfile.TemporaryDirectory(prefix="signsure-asr-") as temporary:
            archive = Path(temporary) / "model.tar.bz2"
            with urllib.request.urlopen(url, timeout=60) as source, archive.open("wb") as target:
                shutil.copyfileobj(source, target)
            with tarfile.open(archive) as bundle:
                # Extract only named regular files, never archive paths or links.
                for name in MODEL_FILES.values():
                    member = bundle.getmember(f"{MODEL_ID}/{name}")
                    if not member.isfile() or member.size > 512 * 1024 * 1024:
                        raise ValueError(f"Invalid model member: {name}")
                    with bundle.extractfile(member) as source, (destination / f".{name}.tmp").open("wb") as target:
                        shutil.copyfileobj(source, target)
                    (destination / f".{name}.tmp").replace(destination / name)
    manifest = {"modelId": MODEL_ID, "license": "Apache-2.0", "sha256": {
        name: hashlib.sha256((destination / name).read_bytes()).hexdigest() for name in MODEL_FILES.values()
    }}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    result = engine.warm()
    print(json.dumps(result, indent=2))
    return 0 if result["warm"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
