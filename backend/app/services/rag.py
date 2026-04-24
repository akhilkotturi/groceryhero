"""Two-phase deal assistant: classify+expand → search → summarize with Groq."""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import rag_tools

logger = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_CLASSIFY_EXPAND_PROMPT = """\
Classify this grocery search query and expand it into specific search terms.

Query types:
- recipe   : user wants to cook something ("make tacos", "ingredients for biryani")
- cuisine  : user wants food from a specific cuisine ("indian food", "asian snacks", "mexican")
- category : user wants a product category ("dental", "cleaning supplies", "beverages", "produce")
- dietary  : user has a dietary preference ("vegan", "keto", "gluten free", "organic")
- product  : user wants a specific product or brand ("Colgate", "chicken breast", "Greek yogurt")
- store    : user wants deals from a specific store ("Walmart deals", "HEB specials")
- general  : anything else

Respond ONLY with valid JSON, no markdown:
{"type": "<type>", "detail": "<specific label e.g. 'indian' or 'dental'>", "search_terms": ["<term1>", "<term2>", ...]}

Include 6-10 specific grocery product names, ingredients, or brands in search_terms.\
"""

_SUMMARIZE_PROMPT = """You are a grocery deal assistant. You receive a user query and a list of candidate deals retrieved by a similarity search.
The similarity search is imperfect and may include irrelevant items. YOUR JOB is to filter and return ONLY deals that genuinely match the query topic.

Rules:
- If the query is about dental/oral care: ONLY include toothpaste, toothbrush, floss, mouthwash, whitening strips, etc. Exclude food, beverages, chips, soda, meat.
- If the query is about produce: ONLY include fruits and vegetables. Exclude meat, dairy, beverages.
- If the query is about cleaning/household cleaning: include detergents, sprays, disinfectants, wipes, soaps, and related cleaning supplies.
- If the user asks for a recipe, meal, or ingredients: prioritize ingredient deals (proteins, produce, sauces, staples) that help make that recipe.
- Apply the same common sense for any query — exclude anything that a shopper would not consider relevant.
- If after filtering nothing truly matches, set deals to [] and explain in the answer.

Respond ONLY with this exact JSON — no markdown, no explanation:
{
  "answer": "<1-2 sentence summary of what you found — be specific about the deals>",
  "deals": [{"deal_id": "<id>", "relevance": "<one phrase explaining the match>"}],
  "suggested_actions": [{"label": "Add best deal to plan", "action": "add_to_plan", "deal_ids": ["<top deal id>"]}]
}
Include the 3-5 best matching deals."""

_SAFETY_BLOCK_TERMS = {
    # violence / weapons
    "bomb", "explosive", "shoot", "kill", "murder", "assault weapon",
    # sexual content
    "porn", "xxx", "nude", "nudes", "explicit sex",
    # illegal hard drugs
    "meth", "cocaine", "heroin", "fentanyl",
    # self-harm
    "suicide", "self harm", "kill myself",
}



@dataclass
class PolicyDecision:
    action: str  # allow | warn | block
    reason_code: str
    message: str | None = None
    matched_terms: list[str] | None = None


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _evaluate_query_policy(query: str) -> PolicyDecision:
    lowered = query.lower().strip()
    if not lowered:
        return PolicyDecision(
            action="warn",
            reason_code="empty_query",
            message="Please ask about grocery deals, products, stores, or recipe ingredients.",
            matched_terms=[],
        )

    matched_block_terms = sorted(term for term in _SAFETY_BLOCK_TERMS if term in lowered)
    if matched_block_terms:
        return PolicyDecision(
            action="block",
            reason_code="unsafe_or_inappropriate",
            message=(
                "I can only help with grocery shopping and deal-related requests. "
                "Please ask about products, stores, discounts, or recipe ingredients."
            ),
            matched_terms=matched_block_terms,
        )

    tokens = _tokenize(lowered)
    if not tokens:
        return PolicyDecision(
            action="warn",
            reason_code="empty_query",
            message="Please ask about grocery deals, products, stores, or recipe ingredients.",
            matched_terms=[],
        )

    return PolicyDecision(
        action="allow",
        reason_code="in_scope",
        matched_terms=[],
    )


async def run_agent(query: str, user_id: str, db: AsyncSession) -> dict[str, Any]:
    """
    Phase 1: semantic_search (deterministic, no LLM).
    Phase 2: Groq summarizes results as structured JSON (no tool calling).
    """
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not configured — add it to backend/.env")

    policy = _evaluate_query_policy(query)
    if policy.action == "block":
        return {
            "answer": policy.message or "I can only help with grocery-related requests.",
            "deals": [],
            "actions_taken": [],
            "suggested_actions": [],
            "turns": 1,
            "guardrail": {
                "action": policy.action,
                "reason_code": policy.reason_code,
                "matched_terms": policy.matched_terms or [],
            },
        }
    if policy.action == "warn":
        return {
            "answer": policy.message or "Please ask about grocery deals or recipe ingredients.",
            "deals": [],
            "actions_taken": [],
            "suggested_actions": [],
            "turns": 1,
            "guardrail": {
                "action": policy.action,
                "reason_code": policy.reason_code,
                "matched_terms": policy.matched_terms or [],
            },
        }

    # Phase 1 — classify + expand, always keeping original query as anchor
    classification = await _classify_and_expand(query)
    expanded = classification.expanded_query
    search_query = f"{query} {expanded}".strip() if expanded and expanded != query else query
    search_result = await rag_tools.semantic_search(
        query=search_query,
        db=db,
        limit=8,
        query_type=classification.type,
    )
    deals = search_result.get("data", [])

    # Phase 2 — summarize: ask Groq to pick the best and explain them
    context = json.dumps(deals) if deals else "No deals found in the database."
    messages = [
        {"role": "system", "content": _SUMMARIZE_PROMPT},
        {"role": "user", "content": f"Query: {query}\n\nDeals:\n{context}"},
    ]

    try:
        resp = await _groq_complete(messages)
        result = _parse_final_response(resp["message"]["content"], [], 1)
        result["actions_taken"] = []
        result["query_type"] = classification.type
        result["guardrail"] = {
            "action": policy.action,
            "reason_code": policy.reason_code,
            "matched_terms": policy.matched_terms or [],
        }
        return result
    except Exception as e:
        logger.error("Groq summarization error: %s", e)
        return {
            "answer": f"Found {len(deals)} deal(s) matching your search.",
            "deals": [{"deal_id": d["deal_id"], "relevance": "matches your search"} for d in deals[:5]],
            "actions_taken": [],
            "suggested_actions": [],
            "turns": 1,
            "query_type": classification.type,
            "guardrail": {
                "action": policy.action,
                "reason_code": policy.reason_code,
                "matched_terms": policy.matched_terms or [],
            },
        }


_VALID_QUERY_TYPES = {"recipe", "cuisine", "category", "dietary", "product", "store", "general"}


@dataclass
class QueryClassification:
    type: str                        # recipe | cuisine | category | dietary | product | store | general
    detail: str                      # e.g. "indian", "dental", "Colgate"
    search_terms: list[str] = field(default_factory=list)

    @property
    def expanded_query(self) -> str:
        if self.search_terms:
            return f"{self.detail or ''} {' '.join(self.search_terms)}".strip()
        return self.detail or ""


async def _classify_and_expand(query: str) -> QueryClassification:
    """Single Groq call: classify query type + expand into specific grocery terms."""
    try:
        resp = await _groq_complete([
            {"role": "system", "content": _CLASSIFY_EXPAND_PROMPT},
            {"role": "user", "content": query},
        ])
        content = resp["message"]["content"].strip()
        start, end = content.find("{"), content.rfind("}") + 1
        parsed = json.loads(content[start:end]) if start >= 0 and end > start else {}
        qtype = parsed.get("type", "general")
        if qtype not in _VALID_QUERY_TYPES:
            qtype = "general"
        return QueryClassification(
            type=qtype,
            detail=parsed.get("detail", ""),
            search_terms=parsed.get("search_terms", []),
        )
    except Exception as e:
        logger.warning("Query classification failed, falling back to general: %s", e)
        return QueryClassification(type="general", detail=query, search_terms=[])


async def _groq_complete(messages: list[dict]) -> dict:
    """Plain Groq text completion — no tools, just returns the message content."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            json={"model": GROQ_MODEL, "messages": messages},
        )
        resp.raise_for_status()
        data = resp.json()
    choice_msg = data["choices"][0]["message"]
    return {"message": {"role": choice_msg["role"], "content": choice_msg.get("content") or ""}}


def _parse_final_response(content: str, actions_taken: list[str], turns: int) -> dict:
    """Extract JSON from LLM content, with fallback for malformed responses."""
    start = content.find("{")
    end = content.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            parsed = json.loads(content[start:end])
            parsed.setdefault("deals", [])
            parsed.setdefault("actions_taken", actions_taken)
            parsed.setdefault("suggested_actions", [])
            parsed["turns"] = turns
            return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {
        "answer": content or "No relevant deals found.",
        "deals": [],
        "actions_taken": actions_taken,
        "suggested_actions": [],
        "turns": turns,
    }
