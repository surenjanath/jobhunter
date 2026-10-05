"""
llm.py — pluggable text generation for cover letters.

Backends, tried in order unless you pin one in config/profile.yaml:

    claude_code   the Claude Code CLI you already have installed. No API key,
                  no per-token cost. Runs `claude -p` headless.
    ollama        a local model over http://localhost:11434. Free, offline,
                  and no data leaves your machine.
    anthropic     the API. Best quality, needs ANTHROPIC_API_KEY, costs cents.
    openai, gemini, groq, openrouter, mistral, deepseek, xai, together, cerebras, fireworks
                  hosted APIs that speak the OpenAI chat-completions format. Each needs its own key.
    custom        any other OpenAI-compatible endpoint: LM Studio, vLLM, LiteLLM, a company gateway…
                  You give the base URL and model; the key is optional.
    template      deterministic fallback in cover_letter.py. Always works.

API keys come from the Settings page (stored in config/llm_keys.json, git-ignored, never sent back to the
browser) or from the environment (OPENAI_API_KEY, GEMINI_API_KEY…). A saved key wins over the environment.

Pick one:
    cover_letter:
      provider: ollama          # or claude_code / anthropic / auto
      ollama_model: llama3.1:8b

Every backend gets the same system prompt and returns plain text, so the
grounding and tone rules in the fact bank apply identically to all of them.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import shutil
import subprocess
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")


CONFIG = Path(__file__).resolve().parent.parent / "config"
KEYS_FILE = CONFIG / "llm_keys.json"
PROFILE_FILE = CONFIG / "profile.yaml"

# Providers reached over the OpenAI chat-completions format. `model` is only a starting point: any model the
# provider offers can be typed (or picked from its live list) on the Settings page.
OPENAI_COMPAT = {
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY",
               "model": "gpt-4o-mini", "keys_url": "https://platform.openai.com/api-keys"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "env": "GEMINI_API_KEY", "model": "gemini-2.5-flash", "keys_url": "https://aistudio.google.com/apikey"},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1", "env": "GROQ_API_KEY",
             "model": "llama-3.3-70b-versatile", "keys_url": "https://console.groq.com/keys"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "env": "OPENROUTER_API_KEY",
                   "model": "openrouter/auto", "keys_url": "https://openrouter.ai/keys"},
    "mistral": {"label": "Mistral", "base_url": "https://api.mistral.ai/v1", "env": "MISTRAL_API_KEY",
                "model": "mistral-small-latest", "keys_url": "https://console.mistral.ai/api-keys"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "env": "DEEPSEEK_API_KEY",
                 "model": "deepseek-chat", "keys_url": "https://platform.deepseek.com/api_keys"},
    "xai": {"label": "xAI", "base_url": "https://api.x.ai/v1", "env": "XAI_API_KEY",
            "model": "grok-3-mini", "keys_url": "https://console.x.ai"},
    "together": {"label": "Together AI", "base_url": "https://api.together.xyz/v1", "env": "TOGETHER_API_KEY",
                 "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "keys_url": "https://api.together.ai/settings/api-keys"},
    "cerebras": {"label": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "env": "CEREBRAS_API_KEY",
                 "model": "llama-3.3-70b", "keys_url": "https://cloud.cerebras.ai"},
    "fireworks": {"label": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1", "env": "FIREWORKS_API_KEY",
                  "model": "accounts/fireworks/models/llama-v3p3-70b-instruct", "keys_url": "https://fireworks.ai/account/api-keys"},
    # base URL and model come from Settings (or LLM_BASE_URL / LLM_MODEL); the key is optional
    "custom": {"label": "Custom endpoint", "base_url": "", "env": "LLM_API_KEY", "model": "", "keys_url": ""},
}
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", **{k: v["env"] for k, v in OPENAI_COMPAT.items()}}
LABELS = {"claude_code": "Claude Code", "ollama": "Ollama", "anthropic": "Anthropic API",
          **{k: v["label"] for k, v in OPENAI_COMPAT.items()}}


class LLMUnavailable(Exception):
    """Backend isn't usable right now. Caller should fall through."""


class LLMNotSetUp(LLMUnavailable):
    """Nobody configured this backend (no key, not installed, not running): expected, so not counted as a failure."""


# ---------------------------------------------------------------------------
# generation options and the usage log
# ---------------------------------------------------------------------------

# name: (default, lowest, highest). Saved under cover_letter in profile.yaml, edited on the Settings page.
OPTION_LIMITS = {"temperature": (0.4, 0.0, 1.5), "max_tokens": (1500, 200, 8000), "timeout": (120, 10, 600)}


def options(cfg: dict | None = None) -> dict:
    """Effective generation options: what's saved, clamped to sane limits, else the defaults."""
    cfg = effective(cfg)
    out = {}
    for key, (default, lo, hi) in OPTION_LIMITS.items():
        try:
            v = type(default)(cfg.get(key, default))
        except (TypeError, ValueError):
            v = default
        out[key] = min(max(v, lo), hi)
    out["fallback"] = bool(cfg.get("fallback"))
    return out


USAGE_FILE = Path(__file__).resolve().parent.parent / "output" / "llm_usage.json"
_usage_lock = threading.Lock()
_last = threading.local()   # token counts of the call just made on this thread, set by the backends


def _note_tokens(tokens_in, tokens_out) -> None:
    _last.tokens = (int(tokens_in or 0), int(tokens_out or 0))


def usage() -> dict:
    """Per provider: calls, failures, tokens in/out, total ms, last_used, last_error. Counts only, never any text."""
    try:
        data = json.loads(USAGE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def reset_usage() -> None:
    with _usage_lock:
        try:
            USAGE_FILE.unlink()
        except OSError:
            pass


def _record(name: str, ms: int, error: str = "") -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _usage_lock:
        data = usage()
        row = {"calls": 0, "failures": 0, "tokens_in": 0, "tokens_out": 0, "ms": 0, "last_used": "", "last_error": "",
               "last_error_at": "", **(data.get(name) or {})}
        if error:
            row.update(failures=row["failures"] + 1, last_error=error[:200], last_error_at=now)
        else:
            tin, tout = getattr(_last, "tokens", (0, 0))
            row.update(calls=row["calls"] + 1, tokens_in=row["tokens_in"] + tin, tokens_out=row["tokens_out"] + tout,
                       ms=row["ms"] + ms, last_used=now)
        data[name] = row
        try:
            USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            USAGE_FILE.write_text(json.dumps(data, indent=2))
        except OSError:   # read-only disk: the log is a nicety, never a reason to fail a request
            pass


# ---------------------------------------------------------------------------
# settings and API keys
# ---------------------------------------------------------------------------

def site_cfg() -> dict:
    """The `cover_letter` block of config/profile.yaml: the site-wide provider, models, custom endpoint and options."""
    try:
        import yaml
        return (yaml.safe_load(PROFILE_FILE.read_text()) or {}).get("cover_letter") or {}
    except Exception:  # noqa: BLE001
        return {}


# A signed-in account's own AI settings, for the length of one request: {"keys": {provider: key}, "cfg": {...}}.
# Set by accounts.middleware; a ContextVar, so never shared between requests. Empty for guests and for the scanner.
_account: contextvars.ContextVar = contextvars.ContextVar("llm_account", default=None)


def account() -> dict:
    return _account.get() or {}


@contextlib.contextmanager
def scoped(settings: dict | None):
    """Run a block as one account (its keys and choices first, the site's as the fallback), or with None as the site."""
    token = _account.set(settings or None)
    try:
        yield
    finally:
        _account.reset(token)


def carry(fn):
    """Wrap `fn` for a worker thread, which does not inherit the request's account on its own."""
    settings = _account.get()

    def run(*args, **kwargs):
        with scoped(settings):
            return fn(*args, **kwargs)
    return run


def effective(cfg: dict | None = None) -> dict:
    """The settings a request really runs with: site-wide, then whatever the caller passed, then the account's own.
    A caller that must force one provider for one call passes `provider_override`."""
    cfg = cfg or {}
    out = {**site_cfg(), **cfg, **(account().get("cfg") or {})}
    if cfg.get("provider_override"):
        out["provider"] = cfg["provider_override"]
    return out


profile_cfg = effective


def saved_keys() -> dict:
    try:
        data = json.loads(KEYS_FILE.read_text())
        return {k: str(v) for k, v in data.items() if v} if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def set_key(provider: str, key: str) -> None:
    """Save (or, with an empty key, forget) a provider's API key. The file is readable by this user only."""
    if provider not in KEY_ENV:
        raise ValueError(f"{provider} does not take an API key")
    keys = saved_keys()
    key = (key or "").strip()
    if key:
        keys[provider] = key
    else:
        keys.pop(provider, None)
    KEYS_FILE.write_text(json.dumps(keys, indent=2))
    try:
        os.chmod(KEYS_FILE, 0o600)
    except OSError:
        pass


def api_key(provider: str) -> tuple[str, str]:
    """(key, where it came from: "account" (this person's own) | "saved" (site-wide) | "env" | "")."""
    own = (account().get("keys") or {}).get(provider)
    if own:
        return own, "account"
    saved = saved_keys().get(provider)
    if saved:
        return saved, "saved"
    env = os.environ.get(KEY_ENV.get(provider, ""), "").strip()
    return (env, "env") if env else ("", "")


def clean_base_url(url: str) -> str:
    """Accepts what people paste: trailing slashes or the full .../chat/completions URL. Raises ValueError if not http(s)."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    url = re.sub(r"/(chat/completions|completions|models)$", "", url)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("base URL must start with http:// or https://")
    return url


def endpoint(name: str, cfg: dict | None = None) -> dict:
    """Where an OpenAI-compatible provider lives and what to send it."""
    cfg = effective(cfg)
    spec = OPENAI_COMPAT[name]
    base = spec["base_url"]
    model = cfg.get(f"{name}_model") or spec["model"]
    if name == "custom":
        try:
            base = clean_base_url(cfg.get("custom_base_url") or os.environ.get("LLM_BASE_URL", ""))
        except ValueError:
            base = ""
        model = cfg.get("custom_model") or os.environ.get("LLM_MODEL", "")
    key, source = api_key(name)
    return {"name": name, "label": spec["label"], "base_url": base, "model": model, "key": key, "key_source": source}


def _is_local(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in ("localhost", "::1", "0.0.0.0", "host.docker.internal") or host.startswith("127.")


def privacy(cfg: dict | None = None) -> dict:
    """Per provider: where your text goes if you use it."""
    cfg = effective(cfg)
    out = {"ollama": "stays on this machine", "claude_code": "sent to Anthropic via the Claude Code CLI",
           "anthropic": "sent to the Anthropic API"}
    for name, spec in OPENAI_COMPAT.items():
        out[name] = f"sent to {spec['label']}"
    base = endpoint("custom", cfg)["base_url"]
    if base:
        out["custom"] = "stays on this machine" if _is_local(base) else f"sent to {urllib.parse.urlsplit(base).hostname}"
    else:
        out["custom"] = "sent to the endpoint you set"
    return out


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
    if not api_key("anthropic")[0]:
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
        raise LLMNotSetUp("`claude` CLI not on PATH")

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
        raise LLMNotSetUp("`claude` CLI not found") from exc
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
                    timeout: int = 240, think: bool = False, temperature: float = 0.4) -> str:
    """Local model via Ollama's /api/chat. No key, no network egress.

    think=False by default: "thinking" models (qwen3.x, gemma4, deepseek-r1…) otherwise spend most of their time on
    hidden reasoning — measured here at 41s vs 1.2s for the same one-line answer. Models without a thinking mode ignore
    the flag. Set cover_letter.ollama_think: true in profile.yaml to trade speed for that extra reasoning."""
    model = model or DEFAULT_OLLAMA_MODEL
    payload = json.dumps(
        {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": temperature, "num_ctx": 8192},
            "think": bool(think),
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
        raise LLMNotSetUp(f"ollama unreachable at {OLLAMA_HOST}: {exc!r}") from exc

    _note_tokens(data.get("prompt_eval_count"), data.get("eval_count"))
    text = ((data.get("message") or {}).get("content") or "").strip()
    if len(text) < 80:
        raise LLMUnavailable(f"ollama returned too little text ({len(text)} chars)")
    return _strip_fences(text)


def generate_anthropic(system: str, user: str, model: str | None = None, max_tokens: int = 1200,
                       timeout: int = 120) -> str:
    key = api_key("anthropic")[0]
    if not key:
        raise LLMNotSetUp("no Anthropic API key (add one in Settings or set ANTHROPIC_API_KEY)")
    try:
        import anthropic
    except ImportError as exc:
        raise LLMNotSetUp("anthropic package not installed") from exc

    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    try:
        client = anthropic.Anthropic(api_key=key, timeout=timeout)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"anthropic call failed: {exc!r}") from exc
    _note_tokens(getattr(resp.usage, "input_tokens", 0), getattr(resp.usage, "output_tokens", 0))
    return _strip_fences(resp.content[0].text.strip())


class _HTTPFailure(Exception):
    def __init__(self, code: int, body: str):
        super().__init__(f"HTTP {code}")
        self.code, self.body = code, body


def _http_json(url: str, key: str = "", payload: dict | None = None, timeout: int = 120,
               headers: dict | None = None) -> dict:
    """GET (no payload) or POST JSON. Raises _HTTPFailure on an HTTP error status, LLMUnavailable if unreachable."""
    # a named User-Agent: some providers sit behind a CDN that rejects Python's default one
    h = {"Accept": "application/json", "User-Agent": "JobHunter/1.0", **(headers or {})}
    if key and "x-api-key" not in h:
        h["Authorization"] = f"Bearer {key}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise _HTTPFailure(exc.code, exc.read().decode(errors="replace")) from exc
    except Exception as exc:  # noqa: BLE001  (DNS, refused, timeout, not JSON)
        host = urllib.parse.urlsplit(url).netloc
        raise LLMUnavailable(f"could not reach {host}: {str(getattr(exc, 'reason', exc))[:120]}") from exc


def _explain(label: str, exc: _HTTPFailure, key: str = "", model: str = "") -> str:
    """One plain sentence for an API error, with the provider's own message and never the key."""
    msg = exc.body
    try:
        err = json.loads(exc.body)
        err = err[0] if isinstance(err, list) and err else err
        e = err.get("error", err) if isinstance(err, dict) else err
        msg = (e.get("message") if isinstance(e, dict) else str(e)) or exc.body
    except Exception:  # noqa: BLE001
        pass
    msg = " ".join(str(msg).split())[:200]
    if key:
        msg = msg.replace(key, "…")
    lead = {401: "the API key was rejected", 403: "the API key is not allowed to do this",
            404: f"model {model!r} or the URL was not found" if model else "the URL was not found",
            429: "rate limited or out of credit"}.get(exc.code, f"HTTP {exc.code}")
    return f"{label}: {lead} ({msg})" if msg else f"{label}: {lead}"


def _message_text(data: dict) -> str:
    msg = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
    content = msg.get("content") or ""
    if isinstance(content, list):   # some servers answer in parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    # reasoning models served through plain endpoints leave their scratchpad inline
    return re.sub(r"<think>.*?</think>", "", str(content), flags=re.S).strip()


def generate_openai_compat(name: str, system: str, user: str, cfg: dict | None = None, timeout: int | None = None,
                           max_tokens: int | None = None) -> str:
    """Any provider that speaks POST {base}/chat/completions (see OPENAI_COMPAT)."""
    ep = endpoint(name, cfg)
    opt = options(cfg)
    timeout, max_tokens = timeout or opt["timeout"], max_tokens or opt["max_tokens"]
    label = ep["label"]
    if not ep["base_url"]:
        raise LLMNotSetUp(f"{label}: no base URL set (Settings → AI providers)")
    if not ep["model"]:
        raise LLMNotSetUp(f"{label}: no model set (Settings → AI providers)")
    if name != "custom" and not ep["key"]:
        raise LLMNotSetUp(f"{label}: no API key (add one in Settings or set {KEY_ENV[name]})")

    url = f"{ep['base_url']}/chat/completions"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        try:
            data = _http_json(url, ep["key"], {"model": ep["model"], "messages": messages, "temperature": opt["temperature"],
                                               "max_tokens": max_tokens}, timeout)
        except _HTTPFailure as exc:
            # newer reasoning models take max_completion_tokens and a fixed temperature; give them room to think
            if exc.code != 400 or not re.search(r"max_completion_tokens|max_tokens|temperature", exc.body):
                raise
            data = _http_json(url, ep["key"], {"model": ep["model"], "messages": messages,
                                               "max_completion_tokens": max(max_tokens * 3, 2000)}, timeout)
    except _HTTPFailure as exc:
        raise LLMUnavailable(_explain(label, exc, ep["key"], ep["model"])) from exc

    use = data.get("usage") or {}
    _note_tokens(use.get("prompt_tokens"), use.get("completion_tokens"))
    text = _message_text(data)
    if not text:
        raise LLMUnavailable(f"{label}: the model returned no text")
    return _strip_fences(text)


def list_models(name: str, cfg: dict | None = None, timeout: int = 15) -> list[str]:
    """The models a provider offers right now, so nobody has to guess a model id."""
    if name == "ollama":
        return sorted(ollama_models())
    try:
        if name == "anthropic":
            key = api_key("anthropic")[0]
            if not key:
                raise LLMUnavailable("Anthropic API: no API key")
            data = _http_json("https://api.anthropic.com/v1/models?limit=100", timeout=timeout,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        elif name in OPENAI_COMPAT:
            ep = endpoint(name, cfg)
            if not ep["base_url"]:
                raise LLMUnavailable(f"{ep['label']}: no base URL set")
            if name != "custom" and not ep["key"]:
                raise LLMUnavailable(f"{ep['label']}: no API key")
            data = _http_json(f"{ep['base_url']}/models", ep["key"], timeout=timeout)
        else:
            raise LLMUnavailable(f"{LABELS.get(name, name)} has no model list")
    except _HTTPFailure as exc:
        raise LLMUnavailable(_explain(LABELS.get(name, name), exc, api_key(name)[0])) from exc
    rows = data.get("data") or data.get("models") or [] if isinstance(data, dict) else data
    ids = [str(m.get("id") or m.get("name") or "") if isinstance(m, dict) else str(m) for m in rows]
    return sorted({i.removeprefix("models/") for i in ids if i})


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


# "auto" tries these in turn: no-cost and local first, then whichever APIs have a key
ORDER = ["claude_code", "ollama", "anthropic", *OPENAI_COMPAT]

BACKENDS = {
    "claude_code": generate_claude_code,
    "ollama": generate_ollama,
    "anthropic": generate_anthropic,
    **{name: generate_openai_compat for name in OPENAI_COMPAT},
}
PROVIDERS = ("auto", *ORDER, "template")   # every value `cover_letter.provider` may take


def _describe_compat(name: str, cfg: dict) -> dict:
    ep = endpoint(name, cfg)
    if name == "custom":
        ok = bool(ep["base_url"] and ep["model"])
        detail = f"{ep['model']} at {ep['base_url']}" if ok else "set a base URL and model"
    else:
        ok = bool(ep["key"])
        how = {"account": "your own key", "saved": "site key", "env": "key from " + KEY_ENV[name]}.get(ep["key_source"], "")
        detail = f"{ep['model']}, {how}" if ok else "no API key"
    return {"available": ok, "detail": detail}


def describe(cfg: dict | None = None) -> dict:
    """What's usable on this machine right now. Used by the dashboard.

    Does not run a Claude prompt. That probe takes up to 25s and was
    stalling every page load on the single dev server.
    """
    cfg = effective(cfg)
    models = ollama_models()
    cc = claude_code_available()
    cc_detail = "claude CLI on PATH" if cc else "claude CLI not on PATH"
    akey, asrc = api_key("anthropic")
    return {
        "claude_code": {"available": cc, "detail": cc_detail},
        "ollama": {
            "available": bool(models),
            "detail": f"{len(models)} model(s): {', '.join(models[:4])}" if models
                      else f"not reachable at {OLLAMA_HOST}",
        },
        "anthropic": {
            "available": anthropic_available(),
            "detail": {"account": "your own key", "saved": "site key"}.get(asrc, "ANTHROPIC_API_KEY set") if akey else "no API key",
        },
        **{name: _describe_compat(name, cfg) for name in OPENAI_COMPAT},
        "template": {"available": True, "detail": "always works, no LLM"},
    }


def candidates(cfg: dict | None = None) -> list[str]:
    """The providers a request may try, in order: the pinned one (then the rest, if fallback is on), or all of ORDER."""
    cfg = cfg or {}
    pinned = (cfg.get("provider") or "auto").strip().lower()
    if pinned in ("template", "none"):
        return []
    if pinned not in BACKENDS:
        return list(ORDER)
    return [pinned, *(n for n in ORDER if n != pinned)] if cfg.get("fallback") else [pinned]


def active_provider(cfg: dict | None = None, avail: dict | None = None) -> str | None:
    """The provider the next request will really reach, given what's ready (`avail`: name -> bool)."""
    cfg = effective(cfg)
    if avail is None:
        avail = {k: bool(v.get("available")) for k, v in describe(cfg).items()}
    return next((n for n in candidates(cfg) if avail.get(n)), None)


def call(name: str, system: str, user: str, cfg: dict | None = None, **over) -> str:
    """One request to one named provider, with the saved options applied and the usage log updated.
    `over` (timeout, max_tokens) is for callers with their own needs, like the connection test."""
    cfg = effective(cfg)
    opt = {**options(cfg), **over}
    _last.tokens = (0, 0)
    t0 = time.time()
    try:
        if name in OPENAI_COMPAT:
            text = generate_openai_compat(name, system, user, cfg, timeout=opt["timeout"], max_tokens=opt["max_tokens"])
        elif name == "ollama":
            text = generate_ollama(system, user, cfg.get("ollama_model"), timeout=max(opt["timeout"], 240),
                                   think=bool(cfg.get("ollama_think")), temperature=opt["temperature"])
        elif name == "anthropic":
            text = generate_anthropic(system, user, cfg.get("anthropic_model"), max_tokens=opt["max_tokens"],
                                      timeout=opt["timeout"])
        else:
            text = generate_claude_code(system, user, cfg.get("claude_code_model"), timeout=max(opt["timeout"], 180))
    except LLMNotSetUp:
        raise
    except LLMUnavailable as exc:
        _record(name, 0, str(exc))
        raise
    _record(name, int((time.time() - t0) * 1000))
    return text


def generate(system: str, user: str, cfg: dict | None = None) -> tuple[str, str]:
    """
    Produce text with the first backend that works.

    Returns (text, backend_name). Raises LLMUnavailable only if every
    candidate failed, so the caller can fall back to the template.
    """
    cfg = effective(cfg)   # callers pass what they have; the saved endpoints and the account's own choices fill the rest
    names = candidates(cfg)
    if not names:
        raise LLMUnavailable("provider pinned to template")

    errors = []
    pinned = (cfg.get("provider") or "auto").strip().lower()
    for name in names:
        if name != pinned and name in OPENAI_COMPAT and not _describe_compat(name, cfg)["available"]:
            continue   # an API nobody set up is not an error worth reporting
        try:
            text = call(name, system, user, cfg)
            log.info("cover letter generated via %s", name)
            return text, name
        except LLMUnavailable as exc:
            errors.append(f"{name}: {exc}")
            log.info("  %s unavailable (%s)", name, exc)

    raise LLMUnavailable("; ".join(errors) or "no backend configured")
