"""Claude client wrapper (and a fake for tests)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .cost import BudgetGuard, Usage, cost_usd

_CACHE = {"cache_control": {"type": "ephemeral"}}


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    model: str
    usage: Usage
    cost_usd: float
    stop_reason: str | None = None


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


class LLM:
    """Interface: `complete(system, messages, cache=...) -> LLMResponse`.

    `cache=True` marks the system prompt for prompt caching. Only worth it when the same system prompt
    is sent repeatedly (full-schema mode); a cache write costs 1.25x a normal input token.
    """

    model: str

    def complete(
        self, system: str, messages: list[Message], *, cache: bool = False
    ) -> LLMResponse:  # pragma: no cover
        raise NotImplementedError


class ClaudeLLM(LLM):
    def __init__(
        self,
        model: str = "claude-sonnet-5-5",
        *,
        effort: str = "low",
        max_tokens: int = 4096,
        budget: BudgetGuard | None = None,
        client=None,
    ):
        import anthropic

        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.budget = budget

    def complete(self, system: str, messages: list[Message], *, cache: bool = False) -> LLMResponse:
        prompt_chars = len(system) + sum(len(m.content) for m in messages)
        if self.budget:
            self.budget.check(self.model, prompt_chars)
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=[
                    {"type": "text", "text": system, **_CACHE} if cache else {"type": "text", "text": system}
                ],
                messages=[{"role": m.role, "content": m.content} for m in messages],
                output_config={"effort": self.effort},
            )
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError(f"cannot reach Claude API: {e}") from e

        usage = Usage.from_api(resp.usage)
        cost = (
            self.budget.record(self.model, usage, prompt_chars)
            if self.budget
            else cost_usd(self.model, usage)
        )
        if resp.stop_reason == "refusal":
            raise LLMError("Claude declined this request (refusal)")
        if resp.stop_reason == "max_tokens":
            raise LLMError(f"response hit max_tokens={self.max_tokens} before finishing")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResponse(
            text=text, model=self.model, usage=usage, cost_usd=cost, stop_reason=resp.stop_reason
        )


@dataclass
class FakeLLM(LLM):
    """Returns canned responses. `responder(system, messages) -> str` or a list consumed in order."""

    responses: list[str] | Callable[[str, list[Message]], str] = field(default_factory=list)
    model: str = "fake"
    calls: list[tuple[str, list[Message]]] = field(default_factory=list)

    def complete(self, system: str, messages: list[Message], *, cache: bool = False) -> LLMResponse:
        self.calls.append((system, list(messages)))
        if callable(self.responses):
            text = self.responses(system, messages)
        else:
            if not self.responses:
                raise AssertionError("FakeLLM ran out of responses")
            text = self.responses.pop(0)
        usage = Usage(input_tokens=len(system) // 4, output_tokens=len(text) // 4)
        return LLMResponse(text=text, model=self.model, usage=usage, cost_usd=0.0, stop_reason="end_turn")
