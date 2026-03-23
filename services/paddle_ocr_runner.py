from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
CACHE_ROOT = Path(__file__).resolve().parents[1] / ".runtime_tmp" / "paddle_cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PADDLE_HOME", str(CACHE_ROOT))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))
TEMP_ROOT = CACHE_ROOT / "temp"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TEMP", str(TEMP_ROOT))
os.environ.setdefault("TMP", str(TEMP_ROOT))


def _extract_text(item: object) -> list[str]:
    lines: list[str] = []
    if item is None:
        return lines
    if isinstance(item, str):
        value = item.strip()
        if value:
            lines.append(value)
        return lines
    if isinstance(item, dict):
        for key in ("rec_text", "text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(value.strip())
        nested = item.get("res")
        if nested is not None:
            lines.extend(_extract_text(nested))
        nested_texts = item.get("texts")
        if isinstance(nested_texts, list):
            for part in nested_texts:
                lines.extend(_extract_text(part))
        return lines
    if isinstance(item, (list, tuple)):
        for sub in item:
            lines.extend(_extract_text(sub))
        return lines
    return lines


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    image_paths = [str(Path(path)) for path in payload.get("image_paths", [])]
    if not image_paths:
        sys.stdout.write(json.dumps({"text": "", "page_count": 0, "engine": "paddleocr"}, ensure_ascii=False))
        return 0

    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        lang=payload.get("lang") or "en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    page_texts: list[str] = []
    for image_path in image_paths:
        result = ocr.predict(image_path)
        lines = _extract_text(result)
        page_texts.append("\n".join(line for line in lines if line))

    sys.stdout.write(
        json.dumps(
            {
                "text": "\n\n".join(text.strip() for text in page_texts if text.strip()).strip(),
                "page_count": len(image_paths),
                "engine": "paddleocr",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
