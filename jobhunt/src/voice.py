"""
voice.py — text-to-speech for the mock interview: the "interviewer" asks each question out loud, and reads back
your score and top tip after you answer. Local, via Kokoro (the same engine the app-walkthrough skill uses for
narration) — no API key, nothing leaves your machine.

Optional by design, like every other AI feature here. Two ways to run the same Kokoro model, tried in this order:

    pip install kokoro-onnx soundfile          # ONNX Runtime: no torch, works on Python 3.14, fast on CPU
    python -m src.voice --download             # the model (~325 MB) + voice pack (~28 MB) into output/models/

    pip install kokoro soundfile numpy         # or the PyTorch package (needs spaCy: Python <= 3.13 today)

    brew install espeak-ng   # pronunciation; apt install espeak-ng on Linux

Without it, the interview section still works exactly the same, just as text (this was already true — see
ai_features.interview_feedback). status() tells the UI which is the case so it can show or hide the voice controls.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading

from src import config

log = logging.getLogger(__name__)

CACHE_DIR = config.ROOT / "output" / "tts_cache"
MAX_CHARS = 600           # a question or a feedback summary, never a whole cover letter — keeps synthesis fast
_pipeline = None
_pipeline_lock = threading.Lock()
# the natural-sounding Kokoro voices, by accent. a = American English, b = British English
VOICE_LABELS = {
    "af_heart": "Heart · American, warm", "af_bella": "Bella · American, bright", "af_nicole": "Nicole · American, soft",
    "af_sarah": "Sarah · American, clear", "am_michael": "Michael · American, calm", "am_adam": "Adam · American, deep",
    "am_puck": "Puck · American, lively", "bf_emma": "Emma · British, crisp", "bf_isabella": "Isabella · British, warm",
    "bm_george": "George · British, measured", "bm_lewis": "Lewis · British, deep",
}
DEFAULT_VOICE = "af_heart"
VOICES = frozenset(VOICE_LABELS)
MODEL_DIR = config.ROOT / "output" / "models"
ONNX_MODEL, ONNX_VOICES = MODEL_DIR / "kokoro-v1.0.onnx", MODEL_DIR / "voices-v1.0.bin"
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
_onnx = None
CACHE_MAX_FILES = 400     # every interview result is unique text: without a cap the cache grows forever


def safe_voice(voice: str | None) -> str:
    """Only known voice names reach Kokoro (it would otherwise try to load an arbitrary name as a voice file)."""
    return voice if voice in VOICES else DEFAULT_VOICE


def safe_speed(speed) -> float:
    try:
        s = float(speed)
    except (TypeError, ValueError):
        return 1.05
    return min(1.6, max(0.6, s)) if s == s else 1.05   # s == s is False for NaN


def prune_cache(keep: int = CACHE_MAX_FILES) -> int:
    """Drop the least recently used clips beyond `keep`. Returns how many were removed."""
    if not CACHE_DIR.exists():
        return 0
    files = sorted((p for p in CACHE_DIR.iterdir() if p.suffix in (".mp3", ".wav")), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[keep:]:
        p.unlink(missing_ok=True)
    return max(0, len(files) - keep)


class VoiceUnavailable(RuntimeError):
    pass


def _importable(name: str) -> bool:
    import importlib.util
    import sys
    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def backend() -> str | None:
    """'onnx' (kokoro-onnx + downloaded model), 'torch' (the kokoro package), or None."""
    if not _importable("soundfile"):
        return None
    if _importable("kokoro_onnx") and ONNX_MODEL.exists() and ONNX_VOICES.exists():
        return "onnx"
    if _importable("kokoro"):
        return "torch"
    return None


def available() -> bool:
    return backend() is not None


def download_models(progress=print) -> None:
    """Fetch the ONNX model and voice pack (from the kokoro-onnx project's release) into output/models/."""
    import urllib.request
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for path in (ONNX_MODEL, ONNX_VOICES):
        if path.exists() and path.stat().st_size > 1_000_000:
            progress(f"already have {path.name}")
            continue
        tmp = path.with_suffix(path.suffix + ".part")
        progress(f"downloading {path.name}…")
        urllib.request.urlretrieve(MODEL_URL + path.name, tmp)
        tmp.replace(path)
    progress("done")


def status() -> dict:
    """What the UI needs to decide whether to show voice controls."""
    b = backend()
    missing_model = b is None and _importable("kokoro_onnx")
    return {"available": b is not None, "backend": b,
            "detail": ("Kokoro installed — questions and results are read aloud by a natural local voice." if b else
                       "Kokoro is installed but its model isn't downloaded yet: python -m src.voice --download" if missing_model else
                       "Not installed. pip install kokoro-onnx soundfile, then python -m src.voice --download (plus espeak-ng)."),
            "voices": [{"id": v, "label": VOICE_LABELS[v]} for v in VOICE_LABELS] if b else [], "default": DEFAULT_VOICE}


def _get_onnx():
    global _onnx
    with _pipeline_lock:
        if _onnx is None:
            from kokoro_onnx import Kokoro
            _onnx = Kokoro(str(ONNX_MODEL), str(ONNX_VOICES))
        return _onnx


def _render(text: str, voice: str, speed: float):
    """-> (samples, sample_rate) from whichever backend is installed."""
    if backend() == "onnx":
        samples, sr = _get_onnx().create(text, voice=voice, speed=speed, lang="en-gb" if voice.startswith("b") else "en-us")
        return samples, sr
    import numpy as np
    chunks = [audio for _, _, audio in _get_pipeline(voice)(text, voice=voice, speed=speed)]
    if not chunks:
        return None, 24000
    return (np.concatenate(chunks) if len(chunks) > 1 else chunks[0]), 24000


def _get_pipeline(voice: str):
    global _pipeline
    lang = "b" if voice.startswith("b") else "a"
    with _pipeline_lock:
        if _pipeline is None or _pipeline[0] != lang:
            from kokoro import KPipeline
            _pipeline = (lang, KPipeline(lang_code=lang))
        return _pipeline[1]


def _cache_path(text: str, voice: str, speed: float):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{voice}|{speed}|{text}".encode()).hexdigest()[:24]
    return CACHE_DIR / f"{key}.mp3"


def clean_for_speech(text: str) -> str:
    """Strip the markdown/symbols that read badly aloud ("asterisk asterisk", raw URLs…)."""
    text = re.sub(r"[*_`#]+", "", text or "")
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CHARS]


def synthesize(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.05) -> bytes:
    """Text -> MP3 bytes. Cached on disk by (text, voice, speed) — the same question gets asked more than once.
    Raises VoiceUnavailable if Kokoro isn't installed; callers fall back to text-only (see ai/views.py)."""
    if not available():
        raise VoiceUnavailable(status()["detail"])
    voice, speed = safe_voice(voice), safe_speed(speed)
    text = clean_for_speech(text)
    if not text:
        raise VoiceUnavailable("nothing to say")
    path = _cache_path(text, voice, speed)
    if path.exists():
        path.touch()   # recently used: keep it when pruning
        return path.read_bytes()
    prune_cache(CACHE_MAX_FILES - 1)
    import subprocess
    import soundfile as sf
    full, sr = _render(text, voice, speed)
    if full is None or not len(full):
        raise VoiceUnavailable("Kokoro produced no audio for that text")
    wav_path = path.with_suffix(".wav")
    sf.write(wav_path, full, sr)
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame", "-qscale:a", "4", str(path)],
                       check=True, capture_output=True, timeout=30)
        wav_path.unlink(missing_ok=True)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return wav_path.read_bytes()   # no ffmpeg on this machine — serve the wav as-is; callers set the right content-type
    return path.read_bytes()


def synthesized_content_type(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.05) -> tuple[bytes, str]:
    """Like synthesize(), but also reports whether it actually got mp3 or had to fall back to wav."""
    voice, speed = safe_voice(voice), safe_speed(speed)
    path = _cache_path(clean_for_speech(text), voice, speed)
    data = synthesize(text, voice, speed)
    ct = "audio/mpeg" if path.exists() else "audio/wav"
    return data, ct


if __name__ == "__main__":
    import sys
    if "--download" in sys.argv:
        download_models()
    else:
        print(status())
