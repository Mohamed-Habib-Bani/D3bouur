"""D3BOUUR conversation brain: layered LLM access with automatic fallback.

Primary path: local Ollama. Secondary path: OpenRouter (cloud, free-tier
models) — tried opportunistically when the primary fails.

This was originally the other way around (OpenRouter primary, Ollama
fallback), on the assumption that a cloud model would simply be better.
Live testing (see docs/D3BOUUR_Project_Handoff.md) showed the opposite for
this use case: every free OpenRouter model tried — gpt-oss-20b, gemma,
nemotron — showed a distinct reliability problem (garbled output, fabricated
facts even with correct context provided, or leaked internal reasoning
text), while local Ollama was consistently available and accurate. So
"local first" isn't a fallback-of-last-resort here, it's the more trustworthy
path — OpenRouter is the opportunistic upgrade when it's actually behaving.
Set config.primary_provider = "openrouter" to flip this back if OpenRouter's
free-tier reliability improves enough to revisit.

Whichever provider is primary, this still preserves the original point of
having two providers at all: the robot keeps working during a live demo
even if one path is down, mirroring the project's "must not depend on venue
Wi-Fi" reliability decision — same principle, one layer up (the INTERNET
dependency becomes optional, not just the LOCAL network one).

Usage:
    from d3bouur_conversation import ConversationBrain

    brain = ConversationBrain()
    result = brain.chat("Bonjour !")
    print(result.text, result.provider)
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests

from .knowledge_base import KnowledgeBase, RetrievedChunk
from .persona import PERSONA

logger = logging.getLogger(__name__)

Message = Dict[str, str]


class ProviderError(Exception):
    """A single provider (OpenRouter or Ollama) failed to produce a usable response."""


class AllProvidersFailedError(Exception):
    """Both the primary and fallback providers failed — no response available at all."""


# Characters expected in a normal French reply: Latin letters (incl. accented),
# digits, common punctuation/currency, and the typographic marks models
# commonly produce (curly quotes, guillemets, en/en-dash variants, markdown
# bullets/emphasis). Deliberately generous on *legitimate* typography so we
# don't false-positive on normal formatting — but ANY character outside this
# set fails the check, not a percentage. A single stray CJK/Malayalam/Cyrillic
# character embedded in otherwise-fine text is still a broken TTS read; it
# doesn't need to dominate the response to matter, so this can't be a
# proportion-based threshold the way a "mostly garbled" check would be.
_ALLOWED_CHARS_RE = re.compile(
    r"[A-Za-zÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸàâäçéèêëîïôöùûüÿœÆæ0-9\s"
    r".,!?;:'\"()\-–—‑…°%€$&/*_#•@+"
    r"‘’“”«»]"
)

_SENTENCE_END_CHARS = ".!?…"


def _looks_garbled(text: str) -> bool:
    return any(not _ALLOWED_CHARS_RE.fullmatch(c) for c in text if not c.isspace())


def _trim_to_last_sentence(text: str) -> str:
    """Cut a truncated response back to its last complete sentence, so a
    hard max_tokens cutoff never reaches the visitor (or TTS) as a word
    chopped off mid-syllable. If no sentence boundary exists at all, there's
    nothing safe to cut to — return the text unchanged rather than emptying it."""
    last_end = max((text.rfind(ch) for ch in _SENTENCE_END_CHARS), default=-1)
    if last_end == -1:
        return text
    return text[: last_end + 1].strip()


def _format_rag_context(chunks: List[RetrievedChunk]) -> str:
    if not chunks:
        return (
            "Aucune information trouvée dans la base de connaissances AcaROBOTICS pour cette "
            "question. Si la question porte sur des détails spécifiques à AcaROBOTICS (histoire, "
            "projets, chiffres, événements, formations), dis clairement que tu ne disposes pas "
            "encore de cette information et propose de rediriger vers un membre de l'équipe. "
            "N'invente aucun détail."
        )
    formatted = "\n---\n".join(chunk.text for chunk in chunks)
    return (
        "Informations trouvées dans la base de connaissances AcaROBOTICS :\n"
        f"---\n{formatted}\n---\n"
        "Utilise ces informations pour répondre si elles sont pertinentes à la question. "
        "N'invente rien qui ne soit pas présent ci-dessus."
    )


def _finalize_text(raw_text: str, truncated: bool, provider: str) -> str:
    text = (raw_text or "").strip()

    if truncated and text:
        before = len(text)
        text = _trim_to_last_sentence(text)
        if len(text) != before:
            logger.warning(
                "%s response hit the token limit — trimmed to last complete sentence (%d -> %d chars)",
                provider,
                before,
                len(text),
            )

    if not text:
        raise ProviderError("empty response content")

    if _looks_garbled(text):
        raise ProviderError(f"response looks garbled/corrupted: {text[:80]!r}")

    return text


def _default_env_path() -> Path:
    # llm_router.py lives at <package_root>/d3bouur_conversation/llm_router.py,
    # so parent.parent is <package_root> — the same directory as setup.py.
    return Path(__file__).resolve().parent.parent / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class LLMConfig:
    """All tunable knobs in one place — override any of these when constructing
    ConversationBrain(config=...) without touching the routing/fallback logic."""

    openrouter_api_key: Optional[str] = None
    openrouter_model: str = "openai/gpt-oss-20b:free"
    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    # (connect_timeout, read_timeout): connect fails fast with no internet;
    # read stays generous since generation itself takes real time.
    openrouter_connect_timeout: float = 5.0
    openrouter_read_timeout: float = 30.0

    ollama_model: str = "llama3.2:3b"
    ollama_url: str = "http://localhost:11434/api/chat"
    ollama_timeout: float = 60.0

    # "ollama" or "openrouter" — see module docstring for why this defaults
    # to ollama despite being the "local, smaller model" option.
    primary_provider: str = "ollama"

    # Messages kept in history (user+assistant combined, not counting the
    # persona message which is always resent). 6 = last 3 exchanges — enough
    # for natural follow-ups ("and what about...") without growing prompts
    # unboundedly on a 3B model's limited context.
    max_history_messages: int = 6

    temperature: float = 0.7
    # Was 200 — raised as a first line of defense against mid-sentence
    # truncation. _finalize_text() is the real fix (trims cleanly to the
    # last complete sentence whenever the limit is still hit), this just
    # makes hitting the limit less frequent to begin with.
    max_tokens: int = 300

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "LLMConfig":
        _load_env_file(env_file or _default_env_path())
        return cls(openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"))


@dataclass
class ChatResult:
    text: str
    provider: str  # "openrouter" or "ollama"
    model: str
    elapsed: float


class ConversationBrain:
    """Holds conversation history and routes each turn through whichever
    provider is configured as primary, trying the other one if it fails."""

    def __init__(self, config: Optional[LLMConfig] = None, knowledge_base: Optional[KnowledgeBase] = None):
        self.config = config or LLMConfig.from_env()
        self.history: List[Message] = []
        # Optional by design: without one, behavior is unchanged from before
        # RAG existed (pure persona + history). With one, every turn gets an
        # explicit "here's what's known" or "nothing found" fact injected —
        # see _build_messages().
        self.knowledge_base = knowledge_base

    def chat(self, user_message: str) -> ChatResult:
        messages = self._build_messages(user_message)

        providers = [("ollama", self._call_ollama), ("openrouter", self._call_openrouter)]
        if self.config.primary_provider == "openrouter":
            providers.reverse()

        errors = []
        result = None
        for i, (name, call) in enumerate(providers):
            try:
                result = call(messages)
                break
            except ProviderError as exc:
                errors.append(f"{name} failed ({exc})")
                is_last = i == len(providers) - 1
                suffix = "" if is_last else " — trying next provider"
                logger.warning("%s unavailable (%s)%s", name, exc, suffix)

        if result is None:
            raise AllProvidersFailedError(" and ".join(errors))

        self._record_turn(user_message, result.text)
        return result

    def reset(self) -> None:
        """Clear conversation history — call this when a visitor interaction ends."""
        self.history.clear()

    def _build_messages(self, user_message: str) -> List[Message]:
        messages = [{"role": "system", "content": PERSONA}]
        if self.knowledge_base is not None:
            # Retrieved fresh every turn, based on the current question only —
            # deliberately NOT added to self.history, so stale retrieved
            # context never lingers into later, unrelated turns.
            chunks = self.knowledge_base.search(user_message)
            messages.append({"role": "system", "content": _format_rag_context(chunks)})
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _record_turn(self, user_message: str, assistant_message: str) -> None:
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": assistant_message})
        overflow = len(self.history) - self.config.max_history_messages
        if overflow > 0:
            # Trim from the oldest end, in pairs, so we never leave an
            # orphaned assistant message without its matching user turn.
            self.history = self.history[overflow:]

    def _call_openrouter(self, messages: List[Message]) -> ChatResult:
        if not self.config.openrouter_api_key:
            raise ProviderError("no OPENROUTER_API_KEY configured")

        payload = {
            "model": self.config.openrouter_model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.config.openrouter_api_key}",
            "HTTP-Referer": "https://d3bouur.local",
            "X-Title": "D3BOUUR",
        }

        start = time.perf_counter()
        try:
            resp = requests.post(
                self.config.openrouter_url,
                json=payload,
                headers=headers,
                timeout=(self.config.openrouter_connect_timeout, self.config.openrouter_read_timeout),
            )
        except requests.exceptions.RequestException as exc:
            # Covers no internet, DNS failure, connection refused, timeout — all
            # the "no connection" cases the fallback requirement is about.
            raise ProviderError(f"connection error: {exc}") from exc
        elapsed = time.perf_counter() - start

        if resp.status_code == 429:
            raise ProviderError("rate limited (HTTP 429)")
        if resp.status_code != 200:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        try:
            choice = data["choices"][0]
            raw_text = choice["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected response shape: {data}") from exc

        # A free model can return HTTP 200 with empty/refused content (e.g.
        # content filtering) or a garbled tail (see _looks_garbled) — both
        # raise ProviderError here, which routes through the same fallback
        # path as a network failure. From the caller's perspective "OpenRouter
        # gave me something unusable" and "OpenRouter didn't respond" are the
        # same problem.
        text = _finalize_text(raw_text, truncated=(choice.get("finish_reason") == "length"), provider="openrouter")

        return ChatResult(text=text, provider="openrouter", model=self.config.openrouter_model, elapsed=elapsed)

    def _call_ollama(self, messages: List[Message]) -> ChatResult:
        payload = {
            "model": self.config.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.config.temperature, "num_predict": self.config.max_tokens},
        }

        start = time.perf_counter()
        try:
            resp = requests.post(self.config.ollama_url, json=payload, timeout=self.config.ollama_timeout)
        except requests.exceptions.RequestException as exc:
            raise ProviderError(f"connection error: {exc}") from exc
        elapsed = time.perf_counter() - start

        if resp.status_code != 200:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        raw_text = data.get("message", {}).get("content", "")
        text = _finalize_text(raw_text, truncated=(data.get("done_reason") == "length"), provider="ollama")

        return ChatResult(text=text, provider="ollama", model=self.config.ollama_model, elapsed=elapsed)
