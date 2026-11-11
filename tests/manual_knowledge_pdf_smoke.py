"""Optional-dependency smoke: PYTHONPATH=src python tests/manual_knowledge_pdf_smoke.py."""

import json
from pathlib import Path

from healthzip.knowledge.documents import parse_pdf
from healthzip.knowledge.store import digest

root = Path(__file__).resolve().parents[1]
path = root / "tests/fixtures/synthetic_knowledge.pdf"
raw = path.read_bytes()
metadata, spans = parse_pdf(raw)
assert metadata["page_count"] == 1
assert spans[0]["text"] == "Synthetic evidence only"
assert all(len(span["locator"]["bounding_box"]) == 4 for span in spans)
tables = [span for span in spans if span["kind"] == "table"]
assert len(tables) == 1
assert tables[0]["structured"]["cells"] == [
    {"row": 0, "column": 0, "text": "Load"},
    {"row": 0, "column": 1, "text": "Reps"},
    {"row": 1, "column": 0, "text": "10"},
    {"row": 1, "column": 1, "text": "8"},
]
out = root / "artifacts/knowledge/pdf_parser_smoke.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"data_kind": "synthetic", "input_sha256": digest(raw),
                           "metadata": metadata, "spans": spans,
                           "assertions": "text/page/bounding_box/table cells passed",
                           "command": "PYTHONPATH=src python tests/manual_knowledge_pdf_smoke.py"},
                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("PDF parser smoke passed: actual text coordinates and 4 table cells")
