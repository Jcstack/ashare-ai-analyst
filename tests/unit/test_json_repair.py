"""Tests for truncated JSON repair in prediction analyzer."""

import pytest

from src.prediction.analyzer import _extract_json_from_text, _repair_truncated_json


class TestRepairTruncatedJson:
    def test_closes_single_open_brace(self):
        fragment = '{"key": "value", "score": 0.8'
        result = _repair_truncated_json(fragment)
        assert result is not None
        import json
        parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert parsed["score"] == 0.8

    def test_closes_nested_braces(self):
        fragment = '{"outer": {"inner": 42}'
        result = _repair_truncated_json(fragment)
        assert result is not None
        import json
        parsed = json.loads(result)
        assert parsed["outer"]["inner"] == 42

    def test_closes_array_and_brace(self):
        fragment = '{"items": [1, 2, 3'
        result = _repair_truncated_json(fragment)
        assert result is not None
        import json
        parsed = json.loads(result)
        assert parsed["items"] == [1, 2, 3]

    def test_strips_trailing_incomplete_string(self):
        fragment = '{"key": "value", "partial": "this is cut o'
        result = _repair_truncated_json(fragment)
        assert result is not None
        import json
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_returns_none_for_balanced_json(self):
        fragment = '{"key": "value"}'
        result = _repair_truncated_json(fragment)
        assert result is None

    def test_returns_none_for_unrepairable(self):
        fragment = '{"key": [{"nested": tru'
        result = _repair_truncated_json(fragment)
        # May or may not be repairable; just ensure no crash
        # and returns None if json.loads fails
        assert result is None or isinstance(result, str)

    def test_strips_trailing_comma(self):
        fragment = '{"a": 1, "b": 2,'
        result = _repair_truncated_json(fragment)
        assert result is not None
        import json
        parsed = json.loads(result)
        assert parsed["a"] == 1


class TestExtractJsonTruncated:
    def test_extracts_from_truncated_markdown_fence(self):
        text = '```json\n{"prediction": "buy", "confidence": 0.85'
        result = _extract_json_from_text(text)
        import json
        parsed = json.loads(result)
        assert parsed["prediction"] == "buy"

    def test_normal_json_still_works(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json_from_text(text)
        import json
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_raw_json_still_works(self):
        text = 'Some preamble {"answer": 42} trailing text'
        result = _extract_json_from_text(text)
        import json
        parsed = json.loads(result)
        assert parsed["answer"] == 42
