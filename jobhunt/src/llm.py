"""
llm.py — pluggable text generation for cover letters.

Four backends, tried in order unless you pin one in config/profile.yaml:

    claude_code   the Claude Code CLI you already have installed. No API key,
                  no per-token cost. Runs `claude -p` headless.
    ollama        a local model over http://localhost:11434. Free, offline,
                  and no data leaves your machine.
    anthropic     the API. Best quality, needs ANTHROPIC_API_KEY, costs cents.
    template      deterministic fallback in cover_letter.py. Always works.

Pick one:
    cover_letter:
      provider: ollama          # or claude_code / anthropic / auto
      ollama_model: llama3.1:8b

Every backend gets the same system prompt and returns plain text, so the
grounding and tone rules in the fact bank apply identically to all of them.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")


class LLMUnavailable(Exception):
    """Backend isn't usable right now. Caller should fall through."""


# ---------------------------------------------------------------------------
# availability probes — cheap, never raise
# ---------------------------------------------------------------------------

def claude_code_available() -> bool:
    return shutil.which("claude") is not None


def claude_code_logged_in(timeout: int = 25) -> tuple[bool, str]:
    """
    Cheap auth probe: one trivial prompt. Returns (ok, human explanation).
    Used by the dashboard so it can say 'log in' rather than just 'off'.
    """
    if not claude_code_available():
        return False, "claude CLI not on PATH"
    try:
        with tempfile.TemporaryDirectory(prefix="jobhunt-probe-") as workdir:
            proc = subprocess.run(
                ["claude", "-p", "--output-format", "text",
                 "--disallowedTools", _NO_TOOLS, "--no-session-persistence"],
                input="Reply with the single word: ready",
                capture_output=True, text=True, timeout=timeout, cwd=workdir,
            )
    except Exception as exc:  # noqa: BLE001
        return False, f"probe failed: {exc!r}"[:80]

    blob = f"{proc.stdout} {proc.stderr}".strip()
    if "not logged in" in blob.lower() or "/login" in blob:
        return False, "installed but not logged in — run `claude` then /login"
    if "rate limit" in blob.lower():
        return False, "rate limited"
    if proc.returncode != 0:
        return False, f"exited {proc.returncode}: {blob[:60]}"
    return True, "logged in and ready"


def ollama_available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def ollama_models() -> list[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001
        return []


def anthropic_available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------

# Claude Code is an agentic coding tool: left alone it will happily read files
# and search the web. For drafting a letter that's slow, non-deterministic, and
# a way for stray repo content to leak into the output. Turn the tools off.
_NO_TOOLS = (
    "Bash Edit Write Read Glob Grep WebFetch WebSearch Task "
    "NotebookEdit TodoWrite MultiEdit"
)


def generate_claude_code(
    system: str,
    user: str,
    model: str | None = None,
    timeout: int = 180,
) -> str:
    """
    Drive the Claude Code CLI in headless mode.

    Verified against CLI v2.1.222. Notes that matter:

    * `--system-prompt` exists, so the system prompt goes in properly rather
      than being folded into the user message.
    * Tools are disabled. This is a text generation, not an agent run.
    * `--bare` is deliberately NOT used: it reads auth strictly from
      ANTHROPIC_API_KEY and never touches OAuth or the keychain, so it breaks
      exactly the `claude /login` setup this backend exists to use.
    * Runs from a temp directory so CLAUDE.md auto-discovery doesn't pull the
      jobhunt repo into context.
    * "Not logged in" is printed to STDOUT and the process can still exit 0,
      so success cannot be inferred from the exit code alone.
    """
    if not claude_code_available():
        raise LLMUnavailable("`claude` CLI not on PATH")

    cmd = [
        "claude", "-p",
        "--system-prompt", system,
        "--output-format", "text",
        "--disallowedTools", _NO_TOOLS,
        "--no-session-persistence",
    ]
    if model:
        cmd += ["--model", model]

    try:
        with tempfile.TemporaryDirectory(prefix="jobhunt-cc-") as workdir:
            proc = subprocess.run(
                cmd,
                input=user,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir,
            )
    except FileNotFoundError as exc:
        raise LLMUnavailable("`claude` CLI not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise LLMUnavailable(f"claude CLI timed out after {timeout}s") from exc

    # The CLI writes its diagnostics to STDOUT, not stderr, so an error looks
    # like a very short successful reply. Check both streams.
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    combined = f"{out} {err}".strip()

    if "not logged in" in combined.lower() or "/login" in combined:
        raise LLMUnavailable("claude CLI is not logged in — run `claude` then /login")
    if "rate limit" in combined.lower():
        raise LLMUnavailable("claude CLI is rate limited — try again later")

    if proc.returncode != 0:
        raise LLMUnavailable(
            f"claude CLI exited {proc.returncode}: {(combined or '(no output)')[:200]}"
        )
    if len(out) < 80:
        raise LLMUnavailable(
            f"claude CLI returned too little text ({len(out)} chars): {combined[:160]!r}"
        )
    return _strip_fences(out)


def generate_ollama(system: str, user: str, model: str | None = None,
                    timeout: int = 240) -> str:
    """Local model via Ollama's /api/chat. No key, no network egress."""
    model = model or DEFAULT_OLLAMA_MODEL
    payload = json.dumps(
        {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.4, "num_ctx": 8192},
        }
    ).encode()

    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:200]
        if exc.code == 404:
            raise LLMUnavailable(
                f"model {model!r} not pulled. Run: ollama pull {model}"
            ) from exc
        raise LLMUnavailable(f"ollama HTTP {exc.code}: {body}") from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"ollama unreachable at {OLLAMA_HOST}: {exc!r}") from exc

    text = ((data.get("message") or {}).get("content") or "").strip()
    if len(text) < 80:
        raise LLMUnavailable(f"ollama returned too little text ({len(text)} chars)")
    return _strip_fences(text)


def generate_anthropic(system: str, user: str, model: str | None = None) -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailable("ANTHROPIC_API_KEY not set")
    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailable("anthropic package not installed") from exc

    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"anthropic call failed: {exc!r}") from exc
    return _strip_fences(resp.content[0].text.strip())


# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Local models love wrapping prose in ``` fences. Take them off."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    for lead in ("Here is the cover letter:", "Here's the cover letter:",
                 "Cover letter:", "Sure, here"):
        if t.lower().startswith(lead.lower()):
            t = t[len(lead):].lstrip(" :\n")
    return t.strip()


ORDER = ["claude_code", "ollama", "anthropic"]

BACKENDS = {
    "claude_code": generate_claude_code,
    "ollama": generate_ollama,
    "anthropic": generate_anthropic,
}


def describe() -> dict:
    """What's usable on this machine right now. Used by the dashboard.

    Does not run a Claude prompt. That probe takes up to 25s and was
    stalling every page load on the single dev server.
    """
    models = ollama_models()
    cc = claude_code_available()
    cc_detail = "claude CLI on PATH" if cc else "claude CLI not on PATH"
    return {
        "claude_code": {"available": cc, "detail": cc_detail},
        "ollama": {
            "available": bool(models),
            "detail": f"{len(models)} model(s): {', '.join(models[:4])}" if models
                      else f"not reachable at {OLLAMA_HOST}",
        },
        "anthropic": {
            "available": anthropic_available(),
            "detail": "ANTHROPIC_API_KEY set" if os.environ.get("ANTHROPIC_API_KEY")
                      else "no API key",
        },
        "template": {"available": True, "detail": "always works, no LLM"},
    }


def generate(system: str, user: str, cfg: dict | None = None) -> tuple[str, str]:
    """
    Produce text with the first backend that works.

    Returns (text, backend_name). Raises LLMUnavailable only if every
    candidate failed, so the caller can fall back to the template.
    """
    cfg = cfg or {}
    pinned = (cfg.get("provider") or "auto").strip().lower()

    if pinned in BACKENDS:
        candidates = [pinned]
    elif pinned in ("template", "none"):
        raise LLMUnavailable("provider pinned to template")
    else:
        candidates = ORDER

    errors = []
    for name in candidates:
        fn = BACKENDS[name]
        try:
            if name == "ollama":
                text = fn(system, user, cfg.get("ollama_model"))  # type: ignore[call-arg]
            elif name == "anthropic":
                text = fn(system, user, cfg.get("anthropic_model"))  # type: ignore[call-arg]
            else:
                text = fn(system, user, cfg.get("claude_code_model"))  # type: ignore[call-arg]
            log.info("cover letter generated via %s", name)
            return text, name
        except LLMUnavailable as exc:
            errors.append(f"{name}: {exc}")
            log.info("  %s unavailable (%s)", name, exc)

    raise LLMUnavailable("; ".join(errors) or "no backend configured")
