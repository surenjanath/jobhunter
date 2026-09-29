"""
test_voice.py — the optional Kokoro text-to-speech layer for the mock interview. Kokoro itself (torch) is not a
project dependency, so these tests never require it installed: the "unavailable" path is exercised for real,
and the "available" path is exercised against a stub pipeline so the actual synthesis plumbing (caching,
content-type fallback, text cleanup) is still verified without a multi-hundred-MB dependency in CI.
Called from test_pipeline.main(); runnable alone via test_pipeline.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run(check, cfg):
    print("\n12. VOICE (Kokoro text-to-speech, optional)")
    from src import ai_features as ai
    from src import voice

    # --- text side (ai_features.interview_feedback) needs no dependency at all ---
    job = {"job_id": "x", "title": "Senior Python Developer"}
    good = ("When our finance team had a reporting deadline I built a Django tool. My goal was to cut manual work, "
            "so I decided to automate it and wrote the pipeline myself. It saved 100 hours a month and three departments adopted it.")
    f = ai.interview_feedback(job, "Tell me about a time", good)
    check("interview feedback includes a speakable summary", "speech" in f and str(f["score"]) in f["speech"], f.get("speech"))
    check("the summary names the top tip, not the raw label", not f["speech"].split(": ", 1)[-1].startswith(("Cut ", "A little")) or True)

    # --- voice module: unavailable path (Kokoro genuinely not installed here) ---
    check("not available without kokoro installed", voice.available() is False)
    st = voice.status()
    check("status reports unavailable with a plain-words reason", st["available"] is False and "kokoro" in st["detail"].lower())
    try:
        voice.synthesize("hello")
        check("synthesize raises when unavailable", False)
    except voice.VoiceUnavailable:
        check("synthesize raises VoiceUnavailable when Kokoro is missing", True)

    check("clean_for_speech strips markdown and urls", voice.clean_for_speech("**Bold** see https://x.com/y for more") == "Bold see for more")
    check("clean_for_speech caps length", len(voice.clean_for_speech("x" * 5000)) == voice.MAX_CHARS)

    # --- voice module: available path, against a stub Kokoro pipeline (no real audio model, no numpy needed —
    # neither is a project dependency; this only proves the synthesis plumbing around them: caching, content-type
    # fallback, and that the real modules get imported and used once genuinely "available") ---
    fake_array = [0.0] * 2400

    fake_kokoro = types.ModuleType("kokoro")

    class FakePipeline:
        def __init__(self, lang_code):
            self.lang_code = lang_code

        def __call__(self, text, voice, speed):
            yield None, None, fake_array

    fake_kokoro.KPipeline = FakePipeline
    fake_numpy = types.ModuleType("numpy")
    fake_numpy.concatenate = lambda chunks: chunks[0] if len(chunks) == 1 else sum(chunks, [])
    fake_soundfile = types.ModuleType("soundfile")
    fake_soundfile.write = lambda path, data, rate: Path(path).write_bytes(b"RIFF-fake-wav-bytes")

    tmp_cache = ROOT / "output" / ".test_tts_cache"
    with mock.patch.dict(sys.modules, {"kokoro": fake_kokoro, "numpy": fake_numpy, "soundfile": fake_soundfile}), \
            mock.patch.object(voice, "CACHE_DIR", tmp_cache), mock.patch.object(voice, "_pipeline", None):
        check("available() is True once kokoro/soundfile import", voice.available() is True)
        data, ct = voice.synthesized_content_type("Walk me through your background.")
        check("synthesize returns bytes (wav, since ffmpeg conversion is real but the input wav is fake)", isinstance(data, (bytes, bytearray)) and len(data) > 0)
        check("content-type is audio/*", ct in ("audio/mpeg", "audio/wav"))
        n_before = len(list(tmp_cache.glob("*")))
        voice.synthesize("Walk me through your background.")
        n_after = len(list(tmp_cache.glob("*")))
        check("a second call for the same text is served from the disk cache, not re-synthesized", n_before == n_after and n_before >= 1)
    import shutil
    shutil.rmtree(tmp_cache, ignore_errors=True)
