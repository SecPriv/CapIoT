"""
Runner registry and dispatch logic.

Contract
--------
Runners implement:
- @classmethod can_handle(cfg: AppConfig) -> tuple[int, str]:
    Returns a non-negative integer "score" and optional reason string.
    0 means "cannot handle"; higher is better. Ties are resolved as ambiguity.
- def run(self, ctx: ExperimentContext) -> None

Registration:
- Use @register() or @register(name="...", priority=...) to add to the registry.
"""

from typing import Type, List, Callable, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass
from ..config import AppConfig
from ..context import ExperimentContext
import logging

logger = logging.getLogger("capiot.runners")


class RunnerError(RuntimeError):
    """Base error for runner selection/dispatch problems."""

class RunnerNotFoundError(RunnerError):
    """Raised when no runner matches the given config."""

class RunnerAmbiguousError(RunnerError):
    """Raised when multiple runners match with equal priority."""


@dataclass(frozen=True)
class _Entry:
    cls: Type["BaseRunner"]
    name: str
    priority: int

_REGISTRY: List[_Entry] = []

def register(*, name: Optional[str] = None, priority: int = 0) -> Callable[[Type["BaseRunner"]], Type["BaseRunner"]]:
    """
    Decorator to register a runner.

    Parameters
    ----------
    name : Optional[str]
        Friendly name for logs (defaults to class name).
    priority : int
        Higher values win when multiple runners match.
    """
    def _decorator(cls: Type["BaseRunner"]) -> Type["BaseRunner"]:
        n = name or cls.__name__
        if any(e.cls is cls for e in _REGISTRY):
            logger.debug("Runner %s already registered; skipping duplicate.", n)
            return cls
        _REGISTRY.append(_Entry(cls=cls, name=n, priority=priority))
        logger.debug("Registered runner %s (priority=%d).", n, priority)
        return cls
    return _decorator

class BaseRunner(ABC):
    @classmethod
    @abstractmethod
    def can_handle(cls, cfg: AppConfig) -> bool:
        """
        Return True if this runner can handle the given config, False otherwise.
        """
        raise NotImplementedError
    @abstractmethod
    def run(self, ctx: ExperimentContext) -> None:
        """Execute the experiment workflow for the given context."""
        raise NotImplementedError

def dispatch(ctx: ExperimentContext) -> None:
    """
    Select and run the best-matching runner for the given context.

    Rules
    -----
    - All runners with can_handle(cfg) == True are considered.
    - The runner with the highest priority wins.
    - If multiple runners share the highest priority, raise RunnerAmbiguousError.
    - If no runner matches, raise RunnerNotFoundError.
    """
    cfg = ctx.config
    logger.info("Selecting runner for configuration…")

    matches = [e for e in _REGISTRY if e.cls.can_handle(cfg)]
    if not matches:
        logger.error("No runner matches this configuration.")
        raise RunnerNotFoundError("No runner matches this configuration.")

    matches_sorted = sorted(matches, key=lambda e: e.priority, reverse=True)
    top_priority = matches_sorted[0].priority
    top_candidates = [e for e in matches_sorted if e.priority == top_priority]

    if len(top_candidates) == 1:
        entry = top_candidates[0]
        logger.info("Selected runner: %s (priority=%d)", entry.name, entry.priority)
        entry.cls().run(ctx)
        return

    tied = ", ".join(f"{e.name}(prio={e.priority})" for e in top_candidates)
    logger.error("Ambiguous config; multiple runners tie: %s", tied)
    raise RunnerAmbiguousError(f"Ambiguous config; multiple runners tie: {tied}")
