"""Anthropic client: structured post generation with tool-use and prompt caching."""
from __future__ import annotations

import time
from typing import Any

import structlog

log = structlog.get_logger()

# Tool schema — forces Claude to return exactly three post strings.
GENERATE_POSTS_TOOL: dict = {
    "name": "generate_posts",
    "description": "Return the three platform-specific post drafts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "facebook":  {"type": "string", "minLength": 300, "maxLength": 1200},
            "instagram": {"type": "string", "minLength": 200, "maxLength": 2200},
            "linkedin":  {"type": "string", "minLength": 400, "maxLength": 3000},
        },
        "required": ["facebook", "instagram", "linkedin"],
    },
}


def generate_posts(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    lf_span: Any = None,
) -> tuple[dict[str, str], dict]:
    """Call Claude with tool_choice=generate_posts and prompt caching on the system.

    Returns:
        drafts:  {"facebook": ..., "instagram": ..., "linkedin": ...}
        usage:   token counts + model ID for storage in run_events
    """
    import anthropic

    # Open a Langfuse generation nested under the content span (if provided).
    # Input uses the messages format so Langfuse renders a proper conversation view.
    lf_generation = None
    if lf_span is not None:
        lf_generation = lf_span.start_observation(
            name="claude_generate_posts",
            as_type="generation",
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            metadata={"tool": "generate_posts", "cache_control": "ephemeral_on_system"},
        )

    client = anthropic.Anthropic(api_key=api_key)
    t0 = time.monotonic()

    response = client.messages.create(
        model=model,
        max_tokens=3500,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[GENERATE_POSTS_TOOL],
        tool_choice={"type": "tool", "name": "generate_posts"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    tool_block = next(
        (b for b in response.content if b.type == "tool_use"),
        None,
    )
    if not tool_block:
        if lf_generation:
            lf_generation.update(level="ERROR", status_message=f"No tool_use block; stop_reason={response.stop_reason}")
            lf_generation.end()
        raise ValueError(
            f"Claude returned no tool_use block; stop_reason={response.stop_reason}"
        )

    drafts: dict[str, str] = tool_block.input
    required_platforms = {"facebook", "instagram", "linkedin"}
    missing = required_platforms - set(drafts.keys())
    if missing:
        if lf_generation:
            lf_generation.update(level="ERROR", status_message=f"Tool response missing platforms: {missing}")
            lf_generation.end()
        raise ValueError(f"Claude tool response missing required platforms: {missing}")

    cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
    cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0)
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "model": response.model,
    }

    if lf_generation:
        lf_generation.update(
            output=drafts,
            usage_details={
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            },
            metadata={
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
                "latency_ms": latency_ms,
                "stop_reason": response.stop_reason,
            },
        )
        lf_generation.end()

    log.info(
        "llm_generate_posts",
        model=response.model,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cache_read=cache_read,
        cache_creation=cache_creation,
        latency_ms=latency_ms,
    )
    return drafts, usage
