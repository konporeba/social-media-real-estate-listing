"""BaseAgent — shared scaffold for all pipeline agents."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any


class BaseAgent:
    """Extend this for each pipeline agent.

    emit: async fn(agent_name, event_type, payload) — broadcasts to the SSE hub
          and persists the event row. Provided by the Orchestrator.
    """

    def __init__(
        self,
        run_id: str,
        emit: Callable[..., Coroutine[Any, Any, None]],
        logger: Any,
        lf_trace: Any = None,
    ) -> None:
        self.run_id = run_id
        self.emit = emit
        self.log = logger
        self.lf_trace = lf_trace  # Langfuse StatefulTraceClient; None when disabled

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError
