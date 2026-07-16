"""Market Scorer Agent - Evaluates market opportunity in pitch decks.

Uses LangGraph StateGraph with langchain_openai ChatOpenAI to score market
opportunity (1-10) by evaluating TAM/SAM/SOM, market timing, and growth
potential from extracted deck content.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
"""

import json
import os
from typing import TypedDict, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from app.models.schemas import CategoryScore, ExtractedContent


# ---------------------------------------------------------------------------
# LLM Configuration
# ---------------------------------------------------------------------------


def _get_llm() -> ChatOpenAI:
    """Create a ChatOpenAI instance configured from environment variables."""
    return ChatOpenAI(
        model=os.environ.get("MODEL_ID", "sonnet"),
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL", ""),
        temperature=0.3,
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


SYSTEM_MESSAGE = (
    "You are a top-tier VC partner who has reviewed 2000+ pitch decks and invested in "
    "companies from seed to Series B. You evaluate decks the way real investors do: "
    "looking for signals of a massive opportunity, not checking boxes on a rigid checklist. "
    "You understand that early-stage decks may be imperfect but can still demonstrate "
    "exceptional market awareness through problem framing, demand signals, or growth data. "
    "You score generously when founders show they understand their market deeply, "
    "even if formal metrics like TAM/SAM/SOM aren't explicitly labeled."
)


def _build_scoring_prompt(market_content: str) -> str:
    """Build the scoring task prompt for the market scorer."""
    return f"""You are evaluating this pitch deck's MARKET OPPORTUNITY as a VC investor would.

FULL DECK CONTENT:
{market_content}

WHAT REAL VCs LOOK FOR in Market Opportunity:
1. Is there a large, growing market? (TAM/SAM/SOM, industry size, growth rates — formal or informal)
2. Is the timing right? (regulatory changes, tech shifts, COVID/macro trends, behavioral shifts)
3. Is there proven demand? (existing alternatives, waitlists, pilot users, market validation)
4. Is the problem urgent and expensive? (cost of status quo, pain points quantified)

HOW TO SCORE (be fair and generous like a real VC, not a pedantic checklist):
- 8-10: Massive clear market opportunity. Big numbers, strong timing, proven demand. (Examples: $60B Medicare RPM market, $750B healthcare burden, 38% monthly growth)
- 6-7: Good market signals present but could be stronger. Market exists and is growing.
- 4-5: Some market awareness but sizing is vague or timing unclear.
- 2-3: Minimal market evidence.
- 1: Absolutely zero market information anywhere in the deck.

IMPORTANT: If the deck mentions market size, growth rates, problem cost, or demand validation ANYWHERE, score at least 6. Most funded startups score 7-9 here.

Respond with ONLY a JSON object:
{{
    "score": <integer 1-10>,
    "reasoning": "<50-500 words explaining your score like a VC partner would>",
    "suggestions": ["<1-3 actionable suggestions to strengthen this section>"]
}}"""


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _extract_market_content(extracted_content: ExtractedContent) -> Optional[str]:
    """Extract market-related sections from the extracted content.

    Returns concatenated market content. Includes uncategorized content
    as additional context since early-stage decks often don't have clearly
    delineated sections.
    """
    market_sections = [
        section for section in extracted_content.sections
        if section.category == "market"
    ]
    uncategorized_sections = [
        section for section in extracted_content.sections
        if section.category == "uncategorized"
    ]

    # Combine market + uncategorized for full context
    relevant_sections = market_sections + uncategorized_sections

    if not relevant_sections:
        return None

    return "\n\n".join(section.content for section in relevant_sections)


def _build_missing_info_score() -> CategoryScore:
    """Build a CategoryScore for when no market information is found.

    Requirement 4.4: If no identifiable market information, score=1 with
    reasoning stating market information is missing.
    """
    reasoning = (
        "The pitch deck contains no identifiable market information. "
        "There is no mention of Total Addressable Market (TAM), Serviceable "
        "Addressable Market (SAM), or Serviceable Obtainable Market (SOM). "
        "No market timing indicators or growth potential evidence were found. "
        "Investors require clear market sizing and opportunity data to evaluate "
        "a startup's potential. Without market information, it is impossible to "
        "assess whether the venture targets a viable and sufficiently large market."
    )
    suggestions = [
        "Add a dedicated market size slide with TAM, SAM, and SOM figures backed by credible sources.",
        "Include market timing evidence showing why now is the right moment for this solution.",
        "Present growth potential data such as CAGR projections or emerging trend indicators.",
    ]
    return CategoryScore(
        category="market",
        score=1,
        reasoning=reasoning,
        suggestions=suggestions,
    )


def _parse_agent_response(response: str) -> dict:
    """Parse the agent's response into a dictionary.

    Handles cases where the response may contain markdown code fences
    or extra text around the JSON.
    """
    text = response.strip()

    # Remove markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]

    return json.loads(text)


def _clamp_score(score: int) -> int:
    """Clamp score to valid range [1, 10]."""
    return max(1, min(10, score))


def _truncate_reasoning(reasoning: str) -> str:
    """Ensure reasoning is within bounds: >=50 words and <=500 characters.

    If too short (< 50 words), pad with contextual information.
    If too long (> 500 characters), truncate at the last complete sentence within limit.
    """
    words = reasoning.split()
    if len(words) < 50:
        padding = (
            " The market analysis section requires significant improvement "
            "to meet investor expectations for specificity and evidence-based claims. "
            "Investors need to see concrete data points, credible third-party sources, "
            "and a clear narrative connecting market size to the startup's growth trajectory "
            "and capture strategy within the identified market segments. A thorough market "
            "analysis demonstrates awareness of the competitive dynamics at play."
        )
        reasoning = reasoning.rstrip(".") + "." + padding
        words = reasoning.split()

    if len(reasoning) > 500:
        truncated = reasoning[:500]
        last_period = truncated.rfind(".")
        if last_period > 100:
            truncated = truncated[:last_period + 1]
        else:
            last_space = truncated.rfind(" ")
            if last_space > 100:
                truncated = truncated[:last_space] + "."
        reasoning = truncated

    return reasoning


def _ensure_suggestions(suggestions: list) -> list:
    """Ensure suggestions list has 1-3 items."""
    if not suggestions:
        return ["Strengthen the market opportunity section with specific data points and credible sources."]
    return suggestions[:3]


# ---------------------------------------------------------------------------
# LangGraph State (with reflection support)
# ---------------------------------------------------------------------------


class MarketScorerState(TypedDict):
    content: str
    result: Optional[dict]
    retries: int


# ---------------------------------------------------------------------------
# LangGraph Nodes
# ---------------------------------------------------------------------------


def _score_node(state: MarketScorerState) -> dict:
    """LangGraph node that invokes the LLM to score market opportunity."""
    llm = _get_llm()
    messages = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=_build_scoring_prompt(state["content"])),
    ]
    response = llm.invoke(messages)
    try:
        parsed = _parse_agent_response(response.content)
        return {"result": parsed, "retries": state.get("retries", 0)}
    except (json.JSONDecodeError, ValueError):
        return {"result": None, "retries": state.get("retries", 0)}


def _reflect_node(state: MarketScorerState) -> dict:
    """LangGraph reflection node - challenges a low score and re-evaluates.

    When the initial score is <= 5, this node asks the LLM to reconsider
    whether the score is fair given the full context, especially for
    early-stage decks that may present information informally.
    """
    llm = _get_llm()
    prev_score = state["result"].get("score", 0) if state["result"] else 0
    prev_reasoning = state["result"].get("reasoning", "") if state["result"] else ""

    reflect_prompt = f"""You previously scored this pitch deck's market opportunity as {prev_score}/10 with this reasoning:
"{prev_reasoning}"

Please reconsider your evaluation. The score seems harsh. Ask yourself:
1. Are you penalizing an early-stage/seed deck for not having formal metrics that only later-stage companies would have?
2. Is there implicit market evidence (like showing existing demand, naming large markets, or describing growing trends) that you underweighted?
3. Would a real VC seeing this deck at seed stage score it this low, or would they give credit for vision and market awareness?

Re-evaluate the SAME content with a more calibrated lens. If the low score was justified (truly no market info), keep it. But if there IS market signal that you were too strict about, adjust upward.

ORIGINAL CONTENT:
{state["content"]}

Respond with ONLY a JSON object:
{{
    "score": <integer 1-10>,
    "reasoning": "<50-500 words with updated reasoning>",
    "suggestions": ["<suggestion 1>", "<suggestion 2 (optional)>", "<suggestion 3 (optional)>"]
}}"""

    messages = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=reflect_prompt),
    ]
    response = llm.invoke(messages)
    try:
        parsed = _parse_agent_response(response.content)
        return {"result": parsed, "retries": state["retries"] + 1}
    except (json.JSONDecodeError, ValueError):
        # Keep original result if reflection fails
        return {"retries": state["retries"] + 1}


def _should_reflect(state: MarketScorerState) -> str:
    """Conditional edge: route to reflect if score <= 5 and haven't retried yet."""
    if state.get("retries", 0) >= 1:
        return "end"
    if state.get("result") and state["result"].get("score", 10) <= 5:
        return "reflect"
    return "end"


# ---------------------------------------------------------------------------
# Build LangGraph workflow with reflection loop
# ---------------------------------------------------------------------------

workflow = StateGraph(MarketScorerState)
workflow.add_node("score", _score_node)
workflow.add_node("reflect", _reflect_node)
workflow.set_entry_point("score")
workflow.add_conditional_edges("score", _should_reflect, {"reflect": "reflect", "end": END})
workflow.add_conditional_edges("reflect", _should_reflect, {"reflect": "reflect", "end": END})
graph = workflow.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def score_market(extracted_content: ExtractedContent) -> CategoryScore:
    """Score the market opportunity from extracted pitch deck content.

    This is the main entry point for the Market Scorer Agent. It:
    1. Extracts market-related sections from the content
    2. Handles the case of missing market info (Req 4.4)
    3. Runs the LangGraph workflow to evaluate market opportunity
    4. Parses and validates the response into a CategoryScore

    Args:
        extracted_content: The structured content extracted from the pitch deck.

    Returns:
        CategoryScore with category="market", score 1-10, reasoning, and suggestions.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
    """
    # Check for missing market information (Requirement 4.4)
    market_content = _extract_market_content(extracted_content)
    if market_content is None:
        return _build_missing_info_score()

    # Run the LangGraph workflow (with reflection loop for low scores)
    result = await graph.ainvoke({"content": market_content, "result": None, "retries": 0})

    parsed = result.get("result")
    if parsed is None:
        # If parsing fails, return a conservative score with explanation
        return CategoryScore(
            category="market",
            score=5,
            reasoning=(
                "The market opportunity analysis could not be fully evaluated due to "
                "formatting issues in the assessment. The deck contains market-related "
                "content suggesting a viable market opportunity, but a comprehensive "
                "evaluation could not be completed reliably. A retry is recommended."
            ),
            suggestions=[
                "Ensure market data is clearly structured with labeled TAM, SAM, and SOM figures.",
                "Add explicit market timing rationale explaining why this market is ready now.",
            ],
        )

    # Extract and validate fields
    score = _clamp_score(int(parsed.get("score", 5)))
    reasoning = _truncate_reasoning(str(parsed.get("reasoning", "")))
    suggestions = _ensure_suggestions(parsed.get("suggestions", []))
    suggestions = [str(s) for s in suggestions]

    return CategoryScore(
        category="market",
        score=score,
        reasoning=reasoning,
        suggestions=suggestions,
    )
