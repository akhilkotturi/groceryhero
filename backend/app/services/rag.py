"""ReAct agent loop: Reason→Act→Observe using Ollama llama3.1 with tool calling."""
import json
import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import rag_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a grocery deal assistant for GroceryHero. Help users find the best deals.
You have tools: semantic_search (find deals by concept), filter_by_store (deals at one store),
compare_prices (lowest price per store for one item), add_to_plan (save a deal to user's list).

When you have enough context, respond ONLY with valid JSON matching this exact schema:
{
  "answer": "<1-2 sentence summary explaining what you found and why>",
  "deals": [{"deal_id": "<id>", "relevance": "<why this deal is relevant>"}],
  "actions_taken": [],
  "suggested_actions": [{"label": "<button text>", "action": "add_to_plan", "deal_ids": ["<id>"]}]
}
Call tools first to gather deal data, then respond with the JSON."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Search deals by semantic similarity. Use for concept queries like 'cheap chicken', 'organic produce sale'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "category": {"type": "string", "description": "Category filter: produce, meat, dairy, frozen, bakery, etc."},
                    "store": {"type": "string", "description": "Store name filter: HEB, Kroger, Target, etc."},
                    "limit": {"type": "integer", "description": "Max results to return (default 8)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "filter_by_store",
            "description": "Get the top deals from a specific store chain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_name": {"type": "string", "description": "Store chain name, e.g. HEB, Kroger, Target, Walmart"},
                    "category": {"type": "string", "description": "Optional category filter"},
                },
                "required": ["store_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_prices",
            "description": "Compare prices for a specific item across all stores. Returns the lowest price at each store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "Grocery item to compare, e.g. 'chicken breast', 'whole milk'"},
                },
                "required": ["item_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_plan",
            "description": "Add a deal to the user's grocery plan. Only call when the user explicitly asks to add or save a deal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "The deal_id to add to the plan"},
                },
                "required": ["deal_id"],
            },
        },
    },
]


async def run_agent(query: str, user_id: str, db: AsyncSession) -> dict[str, Any]:
    """Run the ReAct agent for a user query. Returns structured JSON response."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    actions_taken: list[str] = []

    for turn in range(settings.RAG_MAX_TURNS):
        try:
            response = await _ollama_chat(messages)
        except httpx.ConnectError:
            raise RuntimeError("Ollama not reachable — is it running at " + settings.OLLAMA_HOST)
        except Exception as e:
            logger.error("Ollama call failed on turn %d: %s", turn + 1, e)
            break

        msg = response.get("message", {})
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            return _parse_final_response(msg.get("content", ""), actions_taken, turn + 1)

        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": tool_calls,
        })

        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            result = await _dispatch_tool(name, args, user_id, db)
            if name == "add_to_plan" and result.get("success"):
                actions_taken.append("added_to_plan")
            messages.append({"role": "tool", "content": json.dumps(result)})

    logger.warning("Agent hit MAX_TURNS=%d for query: %s", settings.RAG_MAX_TURNS, query)
    return {
        "answer": "I found some deals that may match your request.",
        "deals": [],
        "actions_taken": actions_taken,
        "suggested_actions": [],
        "turns": settings.RAG_MAX_TURNS,
    }


async def _ollama_chat(messages: list[dict]) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.OLLAMA_HOST}/api/chat",
            json={
                "model": "llama3.1",
                "messages": messages,
                "tools": TOOL_DEFINITIONS,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _dispatch_tool(name: str, args: dict, user_id: str, db: AsyncSession) -> dict:
    if name == "semantic_search":
        return await rag_tools.semantic_search(
            query=args["query"], db=db,
            category=args.get("category"), store=args.get("store"),
            limit=args.get("limit", settings.RAG_TOP_K),
        )
    if name == "filter_by_store":
        return await rag_tools.filter_by_store(
            store_name=args["store_name"], db=db, category=args.get("category"),
        )
    if name == "compare_prices":
        return await rag_tools.compare_prices(item_name=args["item_name"], db=db)
    if name == "add_to_plan":
        return await rag_tools.add_to_plan(deal_id=args["deal_id"], user_id=user_id, db=db)
    return {"success": False, "error": f"Unknown tool: {name}", "tool": name}


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
        "answer": content or "I found some relevant deals.",
        "deals": [],
        "actions_taken": actions_taken,
        "suggested_actions": [],
        "turns": turns,
    }
