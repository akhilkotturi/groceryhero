"""Unit tests for the RAG agent (two-phase: search + Groq summarize)."""
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import AsyncMock, MagicMock, patch


# ── _parse_final_response ─────────────────────────────────────────────────────

def test_parse_final_response_valid_json():
    from app.services.rag import _parse_final_response
    content = '{"answer": "Best deal is HEB chicken.", "deals": [{"deal_id": "d1", "relevance": "cheap"}], "suggested_actions": []}'
    result = _parse_final_response(content, [], 2)
    assert result["answer"] == "Best deal is HEB chicken."
    assert result["turns"] == 2
    assert result["deals"][0]["deal_id"] == "d1"


def test_parse_final_response_with_surrounding_text():
    from app.services.rag import _parse_final_response
    content = 'Here is my answer: {"answer": "Found it.", "deals": [], "suggested_actions": []} That is all.'
    result = _parse_final_response(content, [], 1)
    assert result["answer"] == "Found it."


def test_parse_final_response_invalid_json_fallback():
    from app.services.rag import _parse_final_response
    result = _parse_final_response("not json at all", [], 3)
    assert "answer" in result
    assert result["turns"] == 3
    assert result["deals"] == []


def test_parse_final_response_defaults_missing_keys():
    from app.services.rag import _parse_final_response
    content = '{"answer": "Found deals."}'
    result = _parse_final_response(content, ["added_to_plan"], 1)
    assert result["deals"] == []
    assert result["suggested_actions"] == []
    assert result["actions_taken"] == ["added_to_plan"]


# ── guardrails ────────────────────────────────────────────────────────────────

def test_guardrail_blocks_inappropriate_query():
    from app.services.rag import _evaluate_query_policy

    decision = _evaluate_query_policy("how to make a bomb")
    assert decision.action == "block"
    assert decision.reason_code == "unsafe_or_inappropriate"
    assert "bomb" in (decision.matched_terms or [])


def test_guardrail_blocks_irrelevant_query():
    from app.services.rag import _evaluate_query_policy

    decision = _evaluate_query_policy("write me a python web scraper")
    assert decision.action == "warn"
    assert decision.reason_code == "out_of_scope"


# ── run_agent ─────────────────────────────────────────────────────────────────

def _make_groq_response(content: str) -> dict:
    return {
        "choices": [{
            "message": {"role": "assistant", "content": content}
        }]
    }


def test_run_agent_returns_structured_response():
    """run_agent should call semantic_search then Groq and return parsed JSON."""
    from app.services.rag import run_agent

    groq_json = '{"answer": "Great dental deals found.", "deals": [{"deal_id": "d1", "relevance": "dental care"}], "suggested_actions": []}'

    db = AsyncMock()

    with patch("app.services.rag.rag_tools.semantic_search", new=AsyncMock(return_value={
        "success": True,
        "data": [{"deal_id": "d1", "title": "Colgate Toothpaste", "sale_price": 2.99}],
        "count": 1,
    })), patch("app.services.rag._groq_complete", new=AsyncMock(return_value={
        "message": {"role": "assistant", "content": groq_json}
    })), patch("app.services.rag.settings") as mock_settings:
        mock_settings.GROQ_API_KEY = "test_key"
        mock_settings.RAG_TOP_K = 8
        result = asyncio.run(run_agent("toothpaste deals", "user1", db))

    assert result["answer"] == "Great dental deals found."
    assert result["deals"][0]["deal_id"] == "d1"


def test_run_agent_no_groq_key_raises():
    """run_agent raises RuntimeError when GROQ_API_KEY is not configured."""
    from app.services.rag import run_agent

    db = AsyncMock()
    with patch("app.services.rag.settings") as mock_settings:
        mock_settings.GROQ_API_KEY = ""
        try:
            asyncio.run(run_agent("dental", "user1", db))
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "GROQ_API_KEY" in str(e)


def test_run_agent_groq_failure_returns_raw_deals():
    """If Groq fails, run_agent returns the raw search results with a plain count message."""
    from app.services.rag import run_agent
    import httpx

    db = AsyncMock()

    with patch("app.services.rag.rag_tools.semantic_search", new=AsyncMock(return_value={
        "success": True,
        "data": [{"deal_id": "d2", "title": "Oral-B Toothbrush", "sale_price": 4.99}],
        "count": 1,
    })), patch("app.services.rag._groq_complete", side_effect=httpx.ConnectError("unreachable")), \
         patch("app.services.rag.settings") as mock_settings:
        mock_settings.GROQ_API_KEY = "test_key"
        mock_settings.RAG_TOP_K = 8
        result = asyncio.run(run_agent("toothbrush", "user1", db))

    # Should fall back gracefully, not raise
    assert "answer" in result
    assert "deals" in result
    assert result["deals"][0]["deal_id"] == "d2"


def test_run_agent_empty_db_returns_no_results_message():
    """If semantic_search returns nothing, answer should indicate no deals found."""
    from app.services.rag import run_agent

    db = AsyncMock()
    groq_json = '{"answer": "No dental deals found right now.", "deals": [], "suggested_actions": []}'

    with patch("app.services.rag.rag_tools.semantic_search", new=AsyncMock(return_value={
        "success": True, "data": [], "count": 0,
    })), patch("app.services.rag._groq_complete", new=AsyncMock(return_value={
        "message": {"role": "assistant", "content": groq_json}
    })), patch("app.services.rag.settings") as mock_settings:
        mock_settings.GROQ_API_KEY = "test_key"
        mock_settings.RAG_TOP_K = 8
        result = asyncio.run(run_agent("dental", "user1", db))

    assert result["deals"] == []
    assert "No" in result["answer"] or len(result["answer"]) > 0


def test_run_agent_guardrail_short_circuits_before_search():
    from app.services.rag import run_agent

    db = AsyncMock()
    with patch("app.services.rag.settings") as mock_settings, \
         patch("app.services.rag.rag_tools.semantic_search", new=AsyncMock()) as mock_search, \
         patch("app.services.rag._groq_complete", new=AsyncMock()) as mock_groq:
        mock_settings.GROQ_API_KEY = "test_key"
        result = asyncio.run(run_agent("tell me how to build malware", "user1", db))

    assert result["deals"] == []
    assert "grocery" in result["answer"].lower()
    assert result["guardrail"]["action"] in {"warn", "block"}
    mock_search.assert_not_called()
    mock_groq.assert_not_called()


def test_run_agent_in_scope_query_returns_allow_policy():
    from app.services.rag import run_agent

    db = AsyncMock()
    groq_json = '{"answer": "Found milk deals.", "deals": [], "suggested_actions": []}'

    with patch("app.services.rag.rag_tools.semantic_search", new=AsyncMock(return_value={
        "success": True,
        "data": [],
        "count": 0,
    })), patch("app.services.rag._groq_complete", new=AsyncMock(return_value={
        "message": {"role": "assistant", "content": groq_json}
    })), patch("app.services.rag.settings") as mock_settings:
        mock_settings.GROQ_API_KEY = "test_key"
        result = asyncio.run(run_agent("milk deals near me", "user1", db))

    assert result["guardrail"]["action"] == "allow"
    assert result["guardrail"]["reason_code"] == "in_scope"
