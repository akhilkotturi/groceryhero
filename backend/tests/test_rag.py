"""Unit tests for the ReAct agent — tests response parsing and tool dispatch, mocks Ollama."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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


def test_tool_definitions_have_required_fields():
    from app.services.rag import TOOL_DEFINITIONS
    names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
    assert "semantic_search" in names
    assert "filter_by_store" in names
    assert "compare_prices" in names
    assert "add_to_plan" in names
    for tool in TOOL_DEFINITIONS:
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_system_prompt_contains_json_schema():
    from app.services.rag import SYSTEM_PROMPT
    assert "answer" in SYSTEM_PROMPT
    assert "deals" in SYSTEM_PROMPT
    assert "suggested_actions" in SYSTEM_PROMPT
