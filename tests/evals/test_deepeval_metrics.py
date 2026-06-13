from __future__ import annotations

import os

import pytest


def _deepeval_live_enabled() -> bool:
    if os.getenv("DEEPEVAL_LIVE") != "1":
        return False
    return bool(os.getenv("OPENAI_API_KEY"))


@pytest.mark.skipif(
    not _deepeval_live_enabled(),
    reason="Live LLM judge metrics are disabled. Set DEEPEVAL_LIVE=1 and OPENAI_API_KEY.",
)
def test_answer_relevancy_metric_for_mock_incident():
    try:
        from deepeval.metrics import AnswerRelevancyMetric
        from deepeval.test_case import LLMTestCase
    except Exception as exc:  # pragma: no cover - dependency missing in local env
        pytest.skip(f"deepeval is not available: {exc}")

    case = LLMTestCase(
        input="What should we check when coolant flow drops below minimum?",
        actual_output=(
            "Start by checking for a clogged filter or strainer. "
            "If flow stays low after filter replacement, inspect pump impeller damage."
        ),
        retrieval_context=[
            (
                "Falling coolant flow with stable pump speed almost always means a clogged filter "
                "or strainer. If flow stays low with a clean filter, check the pump impeller."
            )
        ],
    )
    metric = AnswerRelevancyMetric(threshold=0.5)
    metric.measure(case)
    assert metric.score is not None
    assert metric.score >= 0.5
