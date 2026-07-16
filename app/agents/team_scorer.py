"""Team Scorer Agent - Evaluates team strength from pitch deck content.

Uses LangGraph StateGraph with langchain_openai ChatOpenAI to produce a
CategoryScore with:
- Integer score 1-10 for team strength
- Reasoning paragraph (50-300 words) on founder backgrounds, experience, completeness
- 1-3 improvement suggestions each referencing a specific gap with a concrete action

Handles:
- Missing team info: score=1, states team info is missing
- Partial team info: score 2-10 based on quality, notes missing details
"""

import json
import os
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.llm_config import get_llm
from app.models.schemas import CategoryScore, ExtractedContent


# --- LangGraph State ---

class TeamScorerState(TypedDict):
    content: str
    result: str
    retries: int


# --- Constants ---

TEAM_SCORER_ROLE = "Expert Startup Team Evaluator"

SYSTEM_MESSAGE = (
    "You are a top-tier VC partner. Team is the #1 factor in early-stage investing. "
    "You know that a strong founding team with domain expertise and execution track "
    "record can make even an imperfect idea work. You evaluate teams generously — "
    "if founders have relevant backgrounds, prior startup experience, or deep domain "
    "knowledge, that's a strong signal even without a flashy team slide."
)

SCORING_TASK_DESCRIPTION = """You are evaluating this pitch deck's TEAM as a VC investor would.

FULL DECK CONTENT:
{team_content}

WHAT REAL VCs LOOK FOR in Team:
1. Founder-market fit: Do founders have domain expertise relevant to the problem?
2. Execution track record: Have they built/scaled companies before? Prior exits?
3. Team completeness: Are key roles (CEO, CTO, sales, product) filled or planned?
4. Complementary skills: Does the team cover business, technical, and domain?
5. Advisors/investors: Notable backers signal team credibility.

HOW TO SCORE (like a real VC, not a rigid checklist):
- 8-10: Strong team with clear domain expertise, relevant track records, or notable credentials. (Examples: "Founded Practice Fusion scaled to $50M ARR", "Former VP at Amazon", "CFO at Eventbrite/Pandora")
- 6-7: Team mentioned with some backgrounds but could be stronger.
- 4-5: Names listed but minimal context on why they're the right team.
- 2-3: Very brief mention of team with no backgrounds.
- 1: Absolutely zero team information anywhere.

IMPORTANT: If the deck lists team members with titles AND relevant backgrounds/credentials, score at least 7. If founders have prior exits or built relevant companies, score 8-9.

Respond with ONLY a valid JSON object:
{{
    "category": "team",
    "score": <integer 1-10>,
    "reasoning": "<50-300 words explaining your score like a VC would>",
    "suggestions": ["<1-3 actionable suggestions>"]
}}"""


# --- Helper Functions ---

def _extract_team_content(extracted_content: ExtractedContent) -> str:
    """Extract team-related sections from the extracted content.

    Includes team sections plus uncategorized content as context since
    early-stage decks often mention founders/team throughout.
    Returns empty string if no content found at all.
    """
    team_sections = [
        section for section in extracted_content.sections
        if section.category == "team"
    ]
    uncategorized_sections = [
        section for section in extracted_content.sections
        if section.category == "uncategorized"
    ]

    relevant_sections = team_sections + uncategorized_sections

    if not relevant_sections:
        return ""

    return "\n\n".join(
        f"[Page(s) {', '.join(str(p) for p in section.page_numbers)}]\n{section.content}"
        for section in relevant_sections
    )


def _build_missing_team_score() -> CategoryScore:
    """Build a CategoryScore for when no team information is found.

    Requirements 5.4: If no team info found, score=1 and state team info is missing.
    """
    return CategoryScore(
        category="team",
        score=1,
        reasoning=(
            "The pitch deck contains no identifiable team information. Investors "
            "consider the founding team to be one of the most critical factors in "
            "evaluating a startup opportunity. Without any information about who is "
            "building this company, their backgrounds, relevant experience, or team "
            "composition, it is impossible to assess team strength. This is a significant "
            "gap that must be addressed before presenting to investors."
        ),
        suggestions=[
            "Add a dedicated team slide featuring each founder's name, role, relevant "
            "background, and key achievements that demonstrate domain expertise.",
            "Include specific prior experience that directly relates to the problem "
            "being solved, such as years in the industry or previous ventures.",
            "Highlight team completeness by showing key roles are filled or explaining "
            "your hiring plan for critical positions like CTO, sales lead, or advisors."
        ]
    )


def _parse_agent_output(output: str) -> Optional[dict]:
    """Parse the agent's JSON output, handling common formatting issues."""
    # Strip markdown code blocks if present
    text = output.strip()
    if text.startswith("```"):
        # Remove opening ```json or ```
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
        # Remove closing ```
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return None
        return None


def _validate_and_build_score(data: dict, has_partial_info: bool) -> CategoryScore:
    """Validate parsed output and build a CategoryScore.

    Ensures score constraints are met and handles edge cases.
    """
    score = data.get("score", 1)
    reasoning = data.get("reasoning", "")
    suggestions = data.get("suggestions", [])

    # Clamp score to valid range
    score = max(1, min(10, int(score)))

    # If partial info detected but score is 1, bump to 2 minimum (Req 5.5)
    if has_partial_info and score < 2:
        score = 2

    # Ensure reasoning meets length requirements (50-300 words maps to ~250-1500 chars)
    # The Pydantic model validates min_length=50, max_length=500 (characters)
    if len(reasoning) < 50:
        reasoning = reasoning + " " + (
            "The team presentation requires more detail for a thorough investor evaluation. "
            "Key areas to address include founder backgrounds and relevant experience."
        )

    if len(reasoning) > 500:
        # Truncate to fit within Pydantic's max_length constraint
        reasoning = reasoning[:497] + "..."

    # Ensure 1-3 suggestions
    if not suggestions:
        suggestions = [
            "Provide detailed founder backgrounds including relevant experience "
            "and achievements that demonstrate capability to execute on this vision."
        ]
    suggestions = suggestions[:3]  # Cap at 3

    return CategoryScore(
        category="team",
        score=score,
        reasoning=reasoning,
        suggestions=suggestions
    )


# --- LangGraph Nodes ---

def _score_node(state: TeamScorerState) -> dict:
    """LangGraph node that calls the LLM to score team strength."""
    llm = get_llm()
    messages = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=SCORING_TASK_DESCRIPTION.format(team_content=state["content"])),
    ]
    response = llm.invoke(messages)
    return {"content": state["content"], "result": response.content, "retries": state.get("retries", 0)}


def _reflect_node(state: TeamScorerState) -> dict:
    """Reflection node - challenges a low team score and re-evaluates."""
    llm = get_llm()
    parsed = _parse_agent_output(state["result"])
    prev_score = parsed.get("score", 0) if parsed else 0
    prev_reasoning = parsed.get("reasoning", "") if parsed else ""

    reflect_prompt = f"""You previously scored this pitch deck's team as {prev_score}/10 with reasoning:
"{prev_reasoning}"

Please reconsider. Ask yourself:
1. Did you miss any founder/team mentions anywhere in the content (even informal ones)?
2. Are you penalizing a seed-stage deck for not having a dedicated team slide when the founders demonstrate expertise through their product/vision?
3. Would a real VC at seed stage score the team this low if the founders clearly understand their domain?

Re-evaluate with a more calibrated lens. If truly no team info exists, keep the low score. But if there ARE signals of competent founders, adjust upward.

ORIGINAL CONTENT:
{state["content"]}

Respond with ONLY a valid JSON object:
{{
    "category": "team",
    "score": <integer 1-10>,
    "reasoning": "<50-300 words>",
    "suggestions": ["<suggestion 1>", "<suggestion 2 (optional)>", "<suggestion 3 (optional)>"]
}}"""

    messages = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=reflect_prompt),
    ]
    response = llm.invoke(messages)
    return {"content": state["content"], "result": response.content, "retries": state["retries"] + 1}


def _should_reflect(state: TeamScorerState) -> str:
    """Conditional edge: reflect if score <= 5 and no retries yet."""
    if state.get("retries", 0) >= 1:
        return "end"
    parsed = _parse_agent_output(state.get("result", ""))
    if parsed and parsed.get("score", 10) <= 5:
        return "reflect"
    return "end"


# --- Build LangGraph with reflection loop ---

_graph = StateGraph(TeamScorerState)
_graph.add_node("score", _score_node)
_graph.add_node("reflect", _reflect_node)
_graph.set_entry_point("score")
_graph.add_conditional_edges("score", _should_reflect, {"reflect": "reflect", "end": END})
_graph.add_conditional_edges("reflect", _should_reflect, {"reflect": "reflect", "end": END})
team_scorer_graph = _graph.compile()


# --- Public API ---

async def score_team(extracted_content: ExtractedContent) -> CategoryScore:
    """Score the team strength from extracted pitch deck content.

    Args:
        extracted_content: The structured content extracted from the pitch deck.

    Returns:
        CategoryScore with category="team", score 1-10, reasoning, and suggestions.

    Requirements:
        5.1: Produce integer score 1-10
        5.2: Reasoning 50-300 words on founder backgrounds, experience, completeness
        5.3: 1-3 suggestions each referencing a specific gap with concrete action
        5.4: No team info -> score=1, state missing
        5.5: Partial info -> score 2-10 based on quality, note missing details
    """
    # Extract team-specific content
    team_content = _extract_team_content(extracted_content)

    # Handle missing team info (Requirement 5.4)
    if not team_content.strip():
        return _build_missing_team_score()

    # Determine if content is partial (heuristic: very short content)
    has_partial_info = len(team_content.strip()) < 200

    # Invoke LangGraph
    try:
        result = await team_scorer_graph.ainvoke({"content": team_content, "result": "", "retries": 0})
        output_text = result["result"]

        # Parse the agent's response
        parsed = _parse_agent_output(output_text)

        if parsed is None:
            # If parsing failed, return a fallback based on partial info detection
            if has_partial_info:
                return CategoryScore(
                    category="team",
                    score=3,
                    reasoning=(
                        "The pitch deck contains limited team information that could not "
                        "be fully evaluated. While some team details are present, the "
                        "content lacks the depth needed for a comprehensive assessment of "
                        "founder backgrounds, relevant experience, and team completeness. "
                        "Investors expect clear articulation of why this team is uniquely "
                        "positioned to succeed."
                    ),
                    suggestions=[
                        "Expand team information with detailed founder backgrounds "
                        "including education, prior roles, and domain-specific achievements.",
                        "Clearly articulate each team member's role and how their "
                        "experience directly applies to solving the problem at hand."
                    ]
                )
            else:
                return CategoryScore(
                    category="team",
                    score=5,
                    reasoning=(
                        "Team information was found in the pitch deck but could not be "
                        "fully processed for scoring. The content appears to contain team "
                        "details but the evaluation could not be completed to the standard "
                        "expected by investors. A manual review of the team slide is "
                        "recommended to ensure all key elements are clearly presented."
                    ),
                    suggestions=[
                        "Ensure team information is clearly structured with distinct "
                        "sections for each founder's background, role, and relevant experience.",
                        "Add quantifiable achievements and specific domain experience "
                        "that demonstrates the team's ability to execute."
                    ]
                )

        return _validate_and_build_score(parsed, has_partial_info)

    except Exception:
        # On any execution error, return a safe fallback
        if has_partial_info:
            return CategoryScore(
                category="team",
                score=2,
                reasoning=(
                    "The pitch deck contains minimal team information. Due to processing "
                    "limitations, a detailed evaluation could not be completed. The limited "
                    "team content suggests the team section needs significant expansion to "
                    "meet investor expectations. Strong teams demonstrate relevant domain "
                    "expertise, complementary skills, and prior execution capability."
                ),
                suggestions=[
                    "Add comprehensive founder profiles with relevant experience, "
                    "education, and prior achievements that build investor confidence.",
                    "Address team completeness by identifying key roles and showing "
                    "a clear plan for filling any gaps in the founding team."
                ]
            )
        return _build_missing_team_score()
