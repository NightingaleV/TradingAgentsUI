"""Framework-neutral durable analysis runtime.

The heavy graph adapter is imported lazily so the Reflex view can compile without
initializing provider and LangGraph dependencies in its web process.
"""

from .models import RunRequest, RunResult

__all__ = ["AnalysisRunner", "RunCancelled", "RunRequest", "RunResult"]


def __getattr__(name: str):
    if name in {"AnalysisRunner", "RunCancelled"}:
        from .analysis_runner import AnalysisRunner, RunCancelled

        return {"AnalysisRunner": AnalysisRunner, "RunCancelled": RunCancelled}[name]
    raise AttributeError(name)
