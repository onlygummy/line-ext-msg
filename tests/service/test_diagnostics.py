"""Probe summaries keep only key names, never secret values."""

from line_ext_msg.service.diagnostics import summarize_dict


def test_summarize_redacts_values():
    data = {"token": "secret123", "count": 5, "tags": ["a", "b"], "gone": None}
    out = summarize_dict(data)
    assert out["token"] == {"type": "str", "len": 9}
    assert out["count"]["type"] == "int"
    assert out["tags"] == {"type": "list", "len": 2}
    assert out["gone"] == {"type": "none", "len": 0}
    # No raw secret leaks into the summary.
    assert "secret123" not in str(out)


def test_summarize_bad_input():
    assert summarize_dict(None) == {}
    assert summarize_dict("nope") == {}
