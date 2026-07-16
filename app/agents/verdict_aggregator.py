"""Verdict Aggregator Agent - Combines category scores into a final scorecard.

Uses LangGraph StateGraph with langchain_openai ChatOpenAI to generate
the verdict summary. Computes overall score as the mean of available category
scores (rounded to nearest integer), ranks categories by descending score
with alphabetical tie-break, and tracks failed categories.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Optional, TypedDict
from uuid import UUID, uuid4

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from app.models.schemas import CategoryScore, Scorecard


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------


class VerdictState(TypedDict):
    scores_summary: str
    failed_info: str
    result: Optional[str]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_CATEGORIES = ["market", "team", "business_model", "competition"]

SYSTEM_MESSAGE = (
    "You are a senior partner at a top-tier venture capital firm with "
    "extensive experience evaluating hundreds of startup pitch decks per "
    "year. You excel at synthesizing complex multi-dimensional evaluations "
    "into clear, actionable verdicts that help founders understand their "
    "overall positioning. You always reference specific scores and findings "
    "when constructing your summary."
)

VERDICT_PROMPT = """Based on the following category evaluations of a startup pitch deck, write a comprehensive verdict summary.

CATEGORY EVALUATIONS:
{scores_summary}
{failed_info}

INSTRUCTIONS:
- Write a verdict summary paragraph of 100 to 500 words
- Synthesize strengths and weaknesses across all evaluated categories
- Reference specific scores and findings from each category
- Provide an overall assessment of pitch deck quality
- If any categories failed, acknowledge the incomplete evaluation
- Be direct, constructive, and investor-focused in tone

OUTPUT FORMAT:
Respond with ONLY the verdict summary text (100-500 words). No JSON, no headers, just the summary paragraph(s)."""


# ---------------------------------------------------------------------------
# LLM Configuration
# ---------------------------------------------------------------------------


def _get_llm() -> ChatOpenAI:
    """Create a ChatOpenAI instance configured from environment variables."""
    return ChatOpenAI(
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=os.environ.get("MODEL_ID", "sonnet"),
        temperature=0.3,
    )


# ---------------------------------------------------------------------------
# Deterministic Computation Functions
# ---------------------------------------------------------------------------


def compute_overall_score(scores: List[CategoryScore]) -> int:
    """Compute overall score as mean of available scores rounded to nearest integer.

    Requirements: 9.1, 9.5
    """
    if not scores:
        return 1
    total = sum(s.score for s in scores)
    mean = total / len(scores)
    return max(1, min(10, round(mean)))


def compute_category_ranking(scores: List[CategoryScore]) -> List[str]:
    """Rank categories by score descending, with alphabetical tie-break.

    Requirements: 9.3
    """
    sorted_scores = sorted(scores, key=lambda s: (-s.score, s.category))
    return [s.category for s in sorted_scores]


def compute_failed_categories(scores: List[CategoryScore]) -> List[str]:
    """Determine which categories are missing from the provided scores.

    Requirements: 9.5
    """
    provided = {s.category for s in scores}
    return sorted([cat for cat in ALL_CATEGORIES if cat not in provided])


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _validate_verdict_summary(text: str) -> str:
    """Validate and adjust the verdict summary to meet length requirements."""
    text = text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    if len(text) > 500:
        truncated = text[:497]
        last_period = truncated.rfind(".")
        if last_period > 100:
            text = truncated[:last_period + 1]
        else:
            text = truncated + "..."

    if len(text) < 100:
        text = text.rstrip(".")
        text += (
            ". This pitch deck requires further development across multiple "
            "dimensions to meet investor expectations for clarity and substance."
        )

    if len(text) > 500:
        text = text[:497] + "..."

    return text


def _build_fallback_verdict(scores: List[CategoryScore], failed_categories: List[str]) -> str:
    """Build a fallback verdict summary when the LLM fails."""
    if not scores:
        return (
            "The pitch deck evaluation could not be completed as no category "
            "scores were successfully generated. All scoring categories failed "
            "during analysis. A complete re-evaluation is recommended to obtain "
            "meaningful feedback on market opportunity, team strength, business "
            "model viability, and competitive positioning."
        )

    overall = compute_overall_score(scores)
    parts = [
        f"This pitch deck received an overall score of {overall}/10 based on "
        f"{len(scores)} evaluated categor{'y' if len(scores) == 1 else 'ies'}."
    ]
    for s in sorted(scores, key=lambda x: -x.score):
        parts.append(f"The {s.category} dimension scored {s.score}/10.")
    if failed_categories:
        parts.append(f"Categories not evaluated: {', '.join(failed_categories)}.")
    parts.append(
        "Founders should focus on strengthening the lowest-scoring areas "
        "to improve their overall pitch quality for investor presentations."
    )

    verdict = " ".join(parts)
    return _validate_verdict_summary(verdict)


# ---------------------------------------------------------------------------
# LangGraph Node
# ---------------------------------------------------------------------------


def _verdict_node(state: VerdictState) -> dict:
    """LangGraph node that invokes the LLM to generate the verdict summary."""
    llm = _get_llm()
    prompt = VERDICT_PROMPT.format(
        scores_summary=state["scores_summary"],
        failed_info=state["failed_info"],
    )
    messages = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=prompt),
    ]
    try:
        response = llm.invoke(messages)
        return {"result": response.content}
    except Exception:
        return {"result": None}


# ---------------------------------------------------------------------------
# Build LangGraph Workflow
# ---------------------------------------------------------------------------

workflow = StateGraph(VerdictState)
workflow.add_node("generate_verdict", _verdict_node)
workflow.set_entry_point("generate_verdict")
workflow.add_edge("generate_verdict", END)
verdict_graph = workflow.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def aggregate_scores(
    scores: List[CategoryScore],
    analysis_id: UUID,
    deck_id: UUID,
) -> Scorecard:
    """Aggregate category scores into a final Scorecard using LangGraph.

    Requirements: 9.1, 9.2, 9.3, 9.4, 9.5
    """
    # Deterministic computations
    overall_score = compute_overall_score(scores)
    category_ranking = compute_category_ranking(scores)
    failed_categories = compute_failed_categories(scores)

    # Build LLM input
    scores_summary = "\n".join(
        f"- {s.category.upper()} (Score: {s.score}/10): {s.reasoning}"
        for s in scores
    )
    failed_info = ""
    if failed_categories:
        failed_info = (
            f"\nNOTE: These categories could not be evaluated due to agent failures: "
            f"{', '.join(failed_categories)}. Mention this gap in your verdict."
        )

    # Run the LangGraph workflow (synchronously since aggregate_scores is sync)
    try:
        result = verdict_graph.invoke({
            "scores_summary": scores_summary,
            "failed_info": failed_info,
            "result": None,
        })
        verdict_text = result.get("result")
        if verdict_text:
            verdict_summary = _validate_verdict_summary(verdict_text)
        else:
            verdict_summary = _build_fallback_verdict(scores, failed_categories)
    except Exception:
        verdict_summary = _build_fallback_verdict(scores, failed_categories)

    return Scorecard(
        id=uuid4(),
        analysis_id=analysis_id,
        deck_id=deck_id,
        overall_score=overall_score,
        category_scores=scores,
        verdict_summary=verdict_summary,
        category_ranking=category_ranking,
        failed_categories=failed_categories,
        created_at=datetime.now(timezone.utc),
    )
