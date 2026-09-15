"""Storage roundtrip keeps non-ASCII text readable."""

import json

from line_ext_msg.output.storage import save_json


def test_save_json_utf8(tmp_path):
    path = tmp_path / "out.json"
    save_json(str(path), {"rooms": [{"name": "café"}]})
    raw = path.read_bytes().decode("utf-8")
    assert "café" in raw
    assert json.loads(raw)["rooms"][0]["name"] == "café"
