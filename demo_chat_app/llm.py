"""Real Anthropic API calls for the demo chat app.

This experiment compares two *variants* of the same base model rather than
two different models: Claude Sonnet 5 with adaptive thinking on (control)
vs. the same model with thinking off (weak, the cheaper candidate). The eval
system's call_site_configs.control_model/weak_model fields are opaque
identifier strings from its perspective (see design doc, "call site" and
"model" are just labels the config service stores and the SDK reports back)
-- interpreting them is this application's job, so MODEL_VARIANTS below maps
each configured identifier to the real API model id + thinking setting to
use, rather than assuming the string is itself a literal Anthropic model id.
"""
import anthropic

SYSTEM_PROMPT = (
    "You are a helpful, friendly chat assistant in a product demo. "
    "Keep responses concise -- a few sentences, unless the user asks for more detail."
)
MAX_TOKENS = 4096  # headroom for the thinking variant's invisible reasoning tokens
THINKING_EFFORT = "low"  # bounds thinking depth -- casual chat doesn't need "high"'s default spend

# call_site_configs.control_model / weak_model value -> (real API model id, thinking config)
MODEL_VARIANTS = {
    "claude-sonnet-5-thinking": ("claude-sonnet-5", {"type": "adaptive"}),
    "claude-sonnet-5-no-thinking": ("claude-sonnet-5", {"type": "disabled"}),
}

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    return _client


def generate_reply(model: str, messages: list[dict]) -> str:
    """`model` is the call site's configured identifier (a MODEL_VARIANTS key,
    not necessarily a literal Anthropic model id). `messages`: full
    conversation so far, ending in the newest user turn."""
    if model not in MODEL_VARIANTS:
        raise RuntimeError(f"unknown model variant {model!r} -- add it to MODEL_VARIANTS in llm.py")
    api_model, thinking = MODEL_VARIANTS[model]

    client = _get_client()
    try:
        response = client.messages.create(
            model=api_model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
            thinking=thinking,
            output_config={"effort": THINKING_EFFORT},
        )
    except anthropic.AuthenticationError as e:
        raise RuntimeError(
            "Anthropic API key missing or invalid -- set ANTHROPIC_API_KEY in .env and restart the server."
        ) from e
    except anthropic.RateLimitError as e:
        raise RuntimeError("Rate limited by the Anthropic API -- try again in a moment.") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("Could not reach the Anthropic API -- check your network connection.") from e

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise RuntimeError(f"Model declined to respond (refusal category: {category}).")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        if response.stop_reason == "max_tokens":
            # Rare even with low effort + generous max_tokens, on a genuinely
            # hard prompt. Degrade to an in-character reply instead of
            # breaking the chat -- this is itself a legitimate (bad) outcome
            # for a demo rating to capture, not just an error to hide.
            return "Hmm, that one took more thinking than I had room for -- could you try rephrasing or simplifying it?"
        raise RuntimeError(f"Model returned no text (stop_reason={response.stop_reason}).")
    return text
