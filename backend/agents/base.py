"""BaseAgent — shared scaffold for all pipeline agents."""

from __future__ import annotations

from typing import Any, Callable, Coroutine


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
    ) -> None:
        self.run_id = run_id
        self.emit = emit
        self.log = logger

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError
