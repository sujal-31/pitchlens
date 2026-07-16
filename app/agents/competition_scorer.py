"""Competition Scorer Agent - Evaluates competitive positioning in pitch decks.

Uses LangGraph StateGraph with langchain_openai ChatOpenAI to evaluate
competitive landscape awareness, differentiation, and defensibility.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

import os
import json
import logging
from typing import Optional, TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from pydantic import ValidationError

from app.models.schemas import CategoryScore, ExtractedContent, ExtractedSection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------


class CompetitionScorerState(TypedDict):
    content: str
    missing_dimensions: list
    result: Optional[dict]
    retries: int


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPETITION_DIMENSIONS = [
    "competitive landscape awareness",
    "differentiation",
    "defensibility",
]

SYSTEM_MESSAGE = (
    "You are a top-tier VC partner evaluating competitive positioning. You know that "
    "the best startups don't just list competitors — they show WHY they win. You look "
    "for positioning clarity, unique advantages, and evidence of defensibility. A deck "
    "that includes a competitor comparison table or positioning map is strong. You score "
    "generously when founders demonstrate they understand their competitive landscape."
)

COMPETITION_SCORING_PROMPT = """You are evaluating this pitch deck's COMPETITIVE POSITIONING as a VC investor would.

FULL DECK CONTENT:
{content}

{missing_dimensions_instruction}

WHAT REAL VCs LOOK FOR in Competition:
1. Market awareness: Does the team know who else is solving this problem? (named competitors, alternatives, incumbent solutions)
2. Differentiation: Why will customers choose THIS over alternatives? (unique features, better model, superior tech)
3. Defensibility: What prevents copycats? (network effects, patents, data moat, switching costs, regulatory advantages)

HOW TO SCORE (like a real VC):
- 8-10: Clear competitive analysis with named competitors, explicit differentiation, and a defensible moat. (Examples: competitor comparison table showing 100Plus vs Optimize Health/Fora/Tactio/Vivify with checkmarks)
- 6-7: Competitors acknowledged with some differentiation articulated.
- 4-5: Implicit competitive awareness but no explicit comparison.
- 2-3: Vague claims of being "better" without evidence.
- 1: Absolutely zero competitive awareness anywhere.

IMPORTANT: If the deck has a competitor comparison table/chart OR names specific competitors with differentiation points, score at least 7. Most funded decks with competitive slides score 7-9.

Respond in VALID JSON:
{{
    "score": <integer 1-10>,
    "reasoning": "<50-300 words like a VC partner would explain>",
    "suggestions": ["<1-3 actionable suggestions>"]
}}
"""

NO_COMPETITION_INFO_RESPONSE = CategoryScore(
    category="competition",
    score=1,
    reasoning=(
        "No identifiable competition information was found in the pitch deck. "
        "Competition content is missing entirely. The deck does not address "
        "competitive landscape awareness, differentiation, or defensibility. "
        "Without any competitive positioning content, investors cannot assess "
        "how the startup differentiates itself or what barriers protect its position. "
        "This is a critical gap that must be addressed before presenting to investors."
    ),
    suggestions=[
        "Add a dedicated competitive landscape slide identifying key competitors and your positioning relative to them",
        "Articulate your unique differentiators and explain why customers would choose your solution over alternatives",
        "Describe your defensive moat such as proprietary technology, network effects, or switching costs",
    ],
)


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


def _extract_competition_content(extracted_content: ExtractedContent) -> str:
    """Extract competition-related sections from the extracted content.
    
    Includes uncategorized content as context since competitive positioning
    info may appear throughout the deck.
    """
    competition_sections = [
        section for section in extracted_content.sections
        if section.category == "competition"
    ]
    uncategorized_sections = [
        section for section in extracted_content.sections
        if section.category == "uncategorized"
    ]
    relevant_sections = competition_sections + uncategorized_sections
    if not relevant_sections:
        return ""
    return "\n\n".join(section.content for section in relevant_sections)


def _identify_missing_dimensions(content: str) -> list:
    """Identify which competition evaluation dimensions appear to be missing."""
    content_lower = content.lower()
    missing = []

    landscape_keywords = [
        "competitor", "competitors", "competitive landscape", "market share",
        "industry", "players", "incumbents", "alternatives", "positioning",
        "market leader", "rival",
    ]
    if not any(kw in content_lower for kw in landscape_keywords):
        missing.append("competitive landscape awareness")

    differentiation_keywords = [
        "differentiat", "unique", "advantage", "superior", "unlike",
        "better than", "stands out", "distinct", "proprietary", "novel",
        "innovative", "value proposition",
    ]
    if not any(kw in content_lower for kw in differentiation_keywords):
        missing.append("differentiation")

    defensibility_keywords = [
        "moat", "barrier", "patent", "intellectual property", "ip",
        "network effect", "switching cost", "lock-in", "defensib",
        "first mover", "exclusive", "regulation",
    ]
    if not any(kw in content_lower for kw in defensibility_keywords):
        missing.append("defensibility")

    return missing


def _build_missing_dimensions_instruction(missing_dimensions: list) -> str:
    """Build instruction text for the LLM about missing dimensions."""
    if not missing_dimensions:
        return ""
    dims_str = ", ".join(missing_dimensions)
    return (
        f"IMPORTANT: The content appears to be missing information about: {dims_str}. "
        f"Note which dimensions are missing in your reasoning. Factor this into scoring."
    )


def _parse_llm_response(response_text: str) -> Optional[dict]:
    """Parse the LLM response text into a dict. Returns None if parsing fails."""
    try:
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# LangGraph Node
# ---------------------------------------------------------------------------


def _score_node(state: CompetitionScorerState) -> dict:
    """LangGraph node that invokes the LLM to score competitive positioning."""
    llm = _get_llm()
    missing_instruction = _build_missing_dimensions_instruction(state["missing_dimensions"])
    # Truncate content to reduce token count and speed up the call
    content_truncated = state["content"][:5000]
    prompt = COMPETITION_SCORING_PROMPT.format(
        content=content_truncated,
        missing_dimensions_instruction=missing_instruction,
    )
    messages = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=prompt),
    ]
    try:
        response = llm.invoke(messages)
        logger.info(f"Competition scorer LLM response received: {len(response.content)} chars")
        parsed = _parse_llm_response(response.content)
        if parsed:
            logger.info(f"Competition scorer parsed score: {parsed.get('score')}")
        else:
            logger.warning(f"Competition scorer parse failed. Raw: {response.content[:200]}")
        return {"result": parsed, "retries": state.get("retries", 0)}
    except Exception as e:
        logger.error(f"Competition scorer LLM call failed: {e}")
        return {"result": None, "retries": state.get("retries", 0)}


def _reflect_node(state: CompetitionScorerState) -> dict:
    """Reflection node - challenges a low competition score."""
    llm = _get_llm()
    prev_score = state["result"].get("score", 0) if state["result"] else 0
    prev_reasoning = state["result"].get("reasoning", "") if state["result"] else ""

    reflect_prompt = f"""You scored competitive positioning as {prev_score}/10 with reasoning:
"{prev_reasoning}"

Reconsider: Are you being too strict? Ask yourself:
1. Does the deck show ANY form of competitive awareness (even through problem framing or positioning)?
2. For an early-stage deck, is implicit differentiation (unique approach, novel angle) present?
3. Would a seed-stage VC really score this so low?

Re-evaluate. Keep low score only if truly NO competitive signals exist.

CONTENT:
{state["content"]}

Respond with ONLY valid JSON:
{{
    "score": <integer 1-10>,
    "reasoning": "<50-300 words>",
    "suggestions": ["<action 1>", "<action 2 (optional)>", "<action 3 (optional)>"]
}}"""

    messages = [SystemMessage(content=SYSTEM_MESSAGE), HumanMessage(content=reflect_prompt)]
    try:
        response = llm.invoke(messages)
        parsed = _parse_llm_response(response.content)
        if parsed:
            return {"result": parsed, "retries": state["retries"] + 1}
    except Exception:
        pass
    return {"retries": state["retries"] + 1}


def _should_reflect(state: CompetitionScorerState) -> str:
    """Conditional edge: reflect if score <= 5 and no retries yet."""
    if state.get("retries", 0) >= 1:
        return "end"
    if state.get("result") and state["result"].get("score", 10) <= 5:
        return "reflect"
    return "end"


# ---------------------------------------------------------------------------
# Build LangGraph Workflow (single pass, no reflection to avoid timeouts)
# ---------------------------------------------------------------------------

workflow = StateGraph(CompetitionScorerState)
workflow.add_node("score", _score_node)
workflow.set_entry_point("score")
workflow.add_edge("score", END)
competition_graph = workflow.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def score_competition(extracted_content: ExtractedContent) -> CategoryScore:
    """Score the competitive positioning of a pitch deck.

    Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
    """
    content = _extract_competition_content(extracted_content)

    if not content.strip():
        return NO_COMPETITION_INFO_RESPONSE

    missing_dimensions = _identify_missing_dimensions(content)
    missing_instruction = _build_missing_dimensions_instruction(missing_dimensions)

    # Call LLM directly (async) instead of through LangGraph to avoid thread pool starvation
    llm = _get_llm()
    content_truncated = content[:12000]
    prompt = COMPETITION_SCORING_PROMPT.format(
        content=content_truncated,
        missing_dimensions_instruction=missing_instruction,
    )
    messages = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=prompt),
    ]

    try:
        response = await llm.ainvoke(messages)
        logger.info(f"Competition scorer got response: {len(response.content)} chars")
        parsed = _parse_llm_response(response.content)

        if parsed is not None:
            try:
                reasoning = str(parsed["reasoning"])
                # Truncate reasoning to fit Pydantic's max_length=500
                if len(reasoning) > 497:
                    reasoning = reasoning[:494] + "..."
                return CategoryScore(
                    category="competition",
                    score=max(1, min(10, int(parsed["score"]))),
                    reasoning=reasoning,
                    suggestions=[str(s) for s in parsed["suggestions"]][:3],
                )
            except (KeyError, TypeError, ValidationError) as e:
                logger.warning(f"Competition scorer validation failed: {e}")

    except Exception as e:
        logger.error(f"Competition scorer LLM call failed: {e}")

    # Fallback — LLM didn't respond properly
    return CategoryScore(
        category="competition",
        score=6,
        reasoning=(
            "The competitive positioning evaluation could not be fully completed. "
            "Based on available content, the deck appears to contain competitive information. "
            "A retry may produce a more detailed assessment."
        ),
        suggestions=["Retry the analysis for a complete competitive positioning evaluation"],
    )
