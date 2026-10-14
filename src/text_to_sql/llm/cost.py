"""Token pricing and a hard spending cap."""

from __future__ import annotations

from dataclasses import dataclass, field

# $ per million tokens (Claude API, prompts <= 100K tokens). Cache writes (5-minute TTL) bill at 1.25x
# input, cache reads at 0.1x input.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_api(cls, u) -> Usage:
        return cls(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
        )


def cost_usd(model: str, usage: Usage) -> float:
    if model not in PRICES:
        raise KeyError(f"no price for {model!r}; add it to PRICES before spending money on it")
    p_in, p_out = PRICES[model]
    return (
        usage.input_tokens * p_in
        + usage.cache_creation_input_tokens * p_in * CACHE_WRITE_MULT
        + usage.cache_read_input_tokens * p_in * CACHE_READ_MULT
        + usage.output_tokens * p_out
    ) / 1_000_000


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class BudgetGuard:
    """Refuses a call when spent + projected cost of that call would pass the cap.

    The projection errs high: input tokens are estimated at chars/3 or the highest tokens-per-char
    ratio seen for that model, whichever is larger, priced as uncached input; output tokens are the
    largest output seen so far (or `min_output_tokens`). Both are then multiplied by `margin`.
    """

    cap_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    min_output_tokens: int = 600
    margin: float = 1.25
    _max_out: dict[str, int] = field(default_factory=dict)
    _tok_per_char: dict[str, float] = field(default_factory=dict)

    def projected(self, model: str, prompt_chars: int) -> float:
        ratio = max(1 / 3, self._tok_per_char.get(model, 0.0))
        out = max(self._max_out.get(model, 0), self.min_output_tokens)
        est = Usage(input_tokens=int(prompt_chars * ratio), output_tokens=out)
        return cost_usd(model, est) * self.margin

    def check(self, model: str, prompt_chars: int) -> None:
        nxt = self.projected(model, prompt_chars)
        if self.spent_usd + nxt > self.cap_usd:
            raise BudgetExceeded(
                f"budget cap ${self.cap_usd:.2f} reached: spent ${self.spent_usd:.4f}, next call ~${nxt:.4f}"
            )

    def record(self, model: str, usage: Usage, prompt_chars: int | None = None) -> float:
        c = cost_usd(model, usage)
        self.spent_usd += c
        self.calls += 1
        self._max_out[model] = max(self._max_out.get(model, 0), usage.output_tokens)
        if prompt_chars:
            total_in = usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
            self._tok_per_char[model] = max(self._tok_per_char.get(model, 0.0), total_in / prompt_chars)
        return c
