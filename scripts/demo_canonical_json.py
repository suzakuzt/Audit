from __future__ import annotations

import json
from pathlib import Path

from services.document_structuring.canonical_json_builder import CanonicalJSONBuilder


def main() -> None:
    sample_path = Path("tests/fixtures/sample_paddle_vl_raw.json")
    raw_payload = json.loads(sample_path.read_text(encoding="utf-8"))
    builder = CanonicalJSONBuilder()
    result = builder.build_from_raw(raw_payload, doc_id="demo_doc_001")
    debug_payload = result.to_debug_payload()

    out_dir = Path("outputs") / "canonical_demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    for file_name in ("merged_blocks", "reading_order", "kv_candidates", "table_candidates", "canonical"):
        (out_dir / f"{file_name}.json").write_text(
            json.dumps(debug_payload[file_name], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    deepseek_payload = builder.build_deepseek_payload(result.canonical)
    (out_dir / "deepseek_payload.json").write_text(
        json.dumps(deepseek_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"canonical demo generated: {out_dir}")


if __name__ == "__main__":
    main()

