"""
voice.py — text-to-speech for the mock interview: the "interviewer" asks each question out loud, and reads back
your score and top tip after you answer. Local, via Kokoro (the same engine the app-walkthrough skill uses for
narration) — no API key, nothing leaves your machine.

Optional by design, like every other AI feature here: Kokoro is not in requirements.txt (it pulls in torch, a
few hundred MB — too heavy to force on everyone for one feature). Install it only if you want voice:

    pip install kokoro soundfile numpy
    brew install espeak-ng   # macOS phonemizer fallback; apt install espeak-ng on Linux

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
_VOICE_BY_LANG = {"a": ("af_heart", "am_michael"), "b": ("bf_emma", "bm_george")}
DEFAULT_VOICE = "af_heart"


class VoiceUnavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        import kokoro  # noqa: F401
        import soundfile  # noqa: F401
    except ImportError:
        return False
    return True


def status() -> dict:
    """What the UI needs to decide whether to show voice controls."""
    ok = available()
    return {"available": ok,
            "detail": "Kokoro installed — questions and results can be read aloud." if ok else
                      "Not installed. pip install kokoro soundfile numpy (plus espeak-ng) for a spoken interviewer.",
            "voices": [v for pair in _VOICE_BY_LANG.values() for v in pair] if ok else []}


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
        raise VoiceUnavailable("Kokoro is not installed — pip install kokoro soundfile numpy")
    text = clean_for_speech(text)
    if not text:
        raise VoiceUnavailable("nothing to say")
    path = _cache_path(text, voice, speed)
    if path.exists():
        return path.read_bytes()
    import subprocess
    import numpy as np
    import soundfile as sf
    pipeline = _get_pipeline(voice)
    chunks = [audio for _, _, audio in pipeline(text, voice=voice, speed=speed)]
    if not chunks:
        raise VoiceUnavailable("Kokoro produced no audio for that text")
    full = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    wav_path = path.with_suffix(".wav")
    sf.write(wav_path, full, 24000)
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame", "-qscale:a", "4", str(path)],
                       check=True, capture_output=True, timeout=30)
        wav_path.unlink(missing_ok=True)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return wav_path.read_bytes()   # no ffmpeg on this machine — serve the wav as-is; callers set the right content-type
    return path.read_bytes()


def synthesized_content_type(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.05) -> tuple[bytes, str]:
    """Like synthesize(), but also reports whether it actually got mp3 or had to fall back to wav."""
    path = _cache_path(clean_for_speech(text), voice, speed)
    data = synthesize(text, voice, speed)
    ct = "audio/mpeg" if path.exists() else "audio/wav"
    return data, ct

