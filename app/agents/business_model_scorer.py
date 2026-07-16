"""Business Model Scorer Agent - Evaluates revenue model, unit economics, and scalability.

Uses LangGraph StateGraph with langchain_openai ChatOpenAI to analyze extracted
pitch deck content and produce a CategoryScore for the 'business_model' category.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

import json
import os
import asyncio
from typing import Optional, TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from pydantic import ValidationError

from app.models.schemas import CategoryScore, ExtractedContent


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------


class BusinessModelScorerState(TypedDict):
    content: str
    result: Optional[dict]
    retries: int


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCORING_TIMEOUT = 90
CATEGORY = "business_model"

SYSTEM_MESSAGE = (
    "You are a top-tier VC partner evaluating business model viability. You know that "
    "the best business models are simple and clear — 'We take 10% commission' is a perfect "
    "business model slide. You look for revenue clarity, unit economics signals, and "
    "scalability potential. A company showing 38% monthly growth with 80% gross margins "
    "has an exceptional business model even without detailed CAC/LTV tables."
)

SCORING_PROMPT = """You are evaluating this pitch deck's BUSINESS MODEL as a VC investor would.

FULL DECK CONTENT:
{content}

WHAT REAL VCs LOOK FOR in Business Model:
1. Revenue clarity: How does the company make money? (commission, SaaS, per-patient fee, subscription — even one sentence counts)
2. Unit economics signals: Pricing, margins, revenue per customer, CAC/LTV hints. (Examples: "$615 per patient per year", "80% gross margins", "$7M ARR")
3. Scalability: Can this grow without linear cost increases? (platform model, recurring revenue, low marginal cost)
4. Traction: Revenue figures, growth rates, projections. (Examples: "38% CMGR", "$7M net ARR", financial projections table)

HOW TO SCORE (like a real VC):
- 8-10: Clear revenue model + strong unit economics + proven scalability/traction. (Examples: revenue tables, ARR growth charts, per-unit pricing with margins)
- 6-7: Revenue model clear, some economics shown, scalability implied.
- 4-5: Business model described but economics unclear.
- 2-3: Revenue model vaguely mentioned.
- 1: Absolutely zero business model information.

IMPORTANT: If the deck shows revenue figures, pricing, growth rates, OR a clear monetization mechanism, score at least 6. If it shows ARR growth, gross margins, AND revenue projections, score 8-9.

Respond with ONLY valid JSON:
{{
    "score": <integer 1-10>,
    "reasoning": "<50-300 words like a VC partner would explain>",
    "suggestions": ["<1-3 actionable suggestions>"]
}}
"""


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
# Helper Functions
# ---------------------------------------------------------------------------


def _extract_business_model_content(extracted: ExtractedContent) -> str:
    """Extract business model relevant sections from the extracted content."""
    business_sections = [
        section for section in extracted.sections
        if section.category == "business_model"
    ]
    if business_sections:
        return "\n\n".join(
            f"[Page {', '.join(str(p) for p in section.page_numbers)}]\n{section.content}"
            for section in business_sections
        )
    # Fallback: check uncategorized content
    uncategorized = [
        section for section in extracted.sections
        if section.category == "uncategorized"
    ]
    if uncategorized:
        return "\n\n".join(
            f"[Page {', '.join(str(p) for p in section.page_numbers)}]\n{section.content}"
            for section in uncategorized
        )
    return ""


def _build_missing_info_score() -> CategoryScore:
    """Produce a score of 1 when no business model information is found."""
    return CategoryScore(
        category=CATEGORY,
        score=1,
        reasoning=(
            "The pitch deck contains no identifiable business model information. "
            "There is no description of the revenue model, unit economics, or scalability "
            "strategy. Investors need to understand how the company plans to generate revenue, "
            "what the cost structure looks like, and how the business can scale. Without any "
            "business model content, it is impossible to evaluate the viability of the venture "
            "from a financial and operational perspective."
        ),
        suggestions=[
            "Add a dedicated business model slide explaining your primary revenue streams and pricing strategy",
            "Include unit economics metrics such as customer acquisition cost, lifetime value, and gross margins",
            "Describe your scalability approach including how growth can be achieved without linear cost increases",
        ],
    )


def _parse_agent_output(output: str) -> dict:
    """Parse the JSON output from the LLM."""
    try:
        return json.loads(output.strip())
    except json.JSONDecodeError:
        pass
    start = output.find("{")
    end = output.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(output[start:end])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse agent output as JSON: {output[:200]}")


def _validate_and_build_score(parsed: dict) -> CategoryScore:
    """Validate parsed output and build a CategoryScore."""
    score = max(1, min(10, int(parsed.get("score", 1))))
    reasoning = str(parsed.get("reasoning", ""))
    suggestions = parsed.get("suggestions", [])

    if len(reasoning) < 50:
        reasoning += " The business model evaluation requires more detail. " * 3
    if len(reasoning) > 500:
        reasoning = reasoning[:497] + "..."
    if not suggestions:
        suggestions = ["Consider providing more detail about your revenue model and business strategy"]
    suggestions = [str(s) for s in suggestions[:3]]

    return CategoryScore(
        category=CATEGORY,
        score=score,
        reasoning=reasoning,
        suggestions=suggestions,
    )


# ---------------------------------------------------------------------------
# LangGraph Node
# ---------------------------------------------------------------------------


def _score_node(state: BusinessModelScorerState) -> dict:
    """LangGraph node that invokes the LLM to score business model viability."""
    llm = _get_llm()
    messages = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=SCORING_PROMPT.format(content=state["content"])),
    ]
    try:
        response = llm.invoke(messages)
        parsed = _parse_agent_output(response.content)
        return {"result": parsed, "retries": state.get("retries", 0)}
    except Exception:
        return {"result": None, "retries": state.get("retries", 0)}


def _reflect_node(state: BusinessModelScorerState) -> dict:
    """Reflection node - challenges a low business model score."""
    llm = _get_llm()
    prev_score = state["result"].get("score", 0) if state["result"] else 0
    prev_reasoning = state["result"].get("reasoning", "") if state["result"] else ""

    reflect_prompt = f"""You scored this business model as {prev_score}/10 with reasoning:
"{prev_reasoning}"

Reconsider: Are you being too harsh? Ask yourself:
1. Is the revenue model actually clear even if simple? (e.g., "We take 10% commission" is extremely clear)
2. For a seed-stage deck, are unit economics signals present even without formal CAC/LTV tables?
3. Does the business model have inherent scalability (marketplace, platform, digital) even without explicit metrics?

A simple, clear business model can score 7-9. Only score low if genuinely no business model info exists.

CONTENT:
{state["content"]}

Respond with ONLY valid JSON:
{{
    "score": <integer 1-10>,
    "reasoning": "<50-300 words>",
    "suggestions": ["<suggestion 1>", "<optional suggestion 2>", "<optional suggestion 3>"]
}}"""

    messages = [SystemMessage(content=SYSTEM_MESSAGE), HumanMessage(content=reflect_prompt)]
    try:
        response = llm.invoke(messages)
        parsed = _parse_agent_output(response.content)
        return {"result": parsed, "retries": state["retries"] + 1}
    except Exception:
        return {"retries": state["retries"] + 1}


def _should_reflect(state: BusinessModelScorerState) -> str:
    """Conditional edge: reflect if score <= 5 and no retries yet."""
    if state.get("retries", 0) >= 1:
        return "end"
    if state.get("result") and state["result"].get("score", 10) <= 5:
        return "reflect"
    return "end"


# ---------------------------------------------------------------------------
# Build LangGraph Workflow with reflection loop
# ---------------------------------------------------------------------------

workflow = StateGraph(BusinessModelScorerState)
workflow.add_node("score", _score_node)
workflow.add_node("reflect", _reflect_node)
workflow.set_entry_point("score")
workflow.add_conditional_edges("score", _should_reflect, {"reflect": "reflect", "end": END})
workflow.add_conditional_edges("reflect", _should_reflect, {"reflect": "reflect", "end": END})
business_model_graph = workflow.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def score_business_model(extracted: ExtractedContent) -> CategoryScore:
    """Score business model using LangGraph with a 30-second timeout.

    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
    """
    content = _extract_business_model_content(extracted)

    if not content.strip():
        return _build_missing_info_score()

    try:
        result = await asyncio.wait_for(
            business_model_graph.ainvoke({"content": content, "result": None, "retries": 0}),
            timeout=SCORING_TIMEOUT,
        )

        parsed = result.get("result")
        if parsed is not None:
            return _validate_and_build_score(parsed)

        return CategoryScore(
            category=CATEGORY,
            score=3,
            reasoning=(
                "The business model scoring could not be completed reliably. "
                "The deck contains business model content but the evaluation "
                "encountered issues during processing. A manual review is recommended "
                "to ensure revenue model, unit economics, and scalability are clearly "
                "presented in the pitch deck."
            ),
            suggestions=["Retry the analysis for a complete business model evaluation"],
        )
    except asyncio.TimeoutError:
        return CategoryScore(
            category=CATEGORY,
            score=5,
            reasoning=(
                "The business model scoring operation took longer than expected. "
                "Based on the available content, there appear to be some business model "
                "elements present but a full evaluation could not be completed within "
                "the time limit. Please retry for a more detailed assessment."
            ),
            suggestions=["Retry the analysis for a complete business model evaluation"],
        )
    except Exception as e:
        return CategoryScore(
            category=CATEGORY,
            score=5,
            reasoning=(
                "The business model evaluation encountered an issue during processing. "
                "Based on available content, a preliminary assessment suggests moderate "
                "business model presence. Please retry for a complete evaluation."
            ),
            suggestions=["Retry the analysis to obtain a proper business model evaluation"],
        )
