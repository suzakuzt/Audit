import base64
import json
import os
from pathlib import Path

import requests


API_URL = "https://q9oet3cfa154oe73.aistudio-app.com/layout-parsing"
TOKEN = "409b5b61c174ad27a633f1162a4e152bdc758649"
DEFAULT_FILE_PATH = Path(r"D:\Project\audit_system\outputs\20260320_154924\inputs\BM 740-2025合同.PDF")
OUTPUT_DIR = Path(r"D:\Project\audit_system\runtime_logs\remote_ocr_script_output")
SUMMARY_PATH = Path(r"D:\Project\audit_system\runtime_logs\remote_ocr_script_result.json")


def infer_file_type(path: Path) -> int:
    return 0 if path.suffix.lower() == ".pdf" else 1


def main() -> int:
    file_path = Path(os.environ.get("REMOTE_OCR_FILE", str(DEFAULT_FILE_PATH))).resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with file_path.open("rb") as file:
        file_bytes = file.read()
        file_data = base64.b64encode(file_bytes).decode("ascii")

    headers = {
        "Authorization": f"token {TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "file": file_data,
        "fileType": infer_file_type(file_path),
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    response = requests.post(API_URL, json=payload, headers=headers, timeout=180)
    response.raise_for_status()
    data = response.json()
    result = data["result"]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, res in enumerate(result["layoutParsingResults"]):
        md_filename = OUTPUT_DIR / f"doc_{i}.md"
        md_filename.write_text(res["markdown"]["text"], encoding="utf-8")

        for img_path, img in res["markdown"]["images"].items():
            full_img_path = OUTPUT_DIR / img_path
            full_img_path.parent.mkdir(parents=True, exist_ok=True)
            img_bytes = requests.get(img, timeout=180).content
            full_img_path.write_bytes(img_bytes)

        for img_name, img in res["outputImages"].items():
            img_response = requests.get(img, timeout=180)
            if img_response.status_code == 200:
                filename = OUTPUT_DIR / f"{img_name}_{i}.jpg"
                filename.write_bytes(img_response.content)

    summary = {
        "file_path": str(file_path),
        "status_code": response.status_code,
        "logId": data.get("logId"),
        "errorCode": data.get("errorCode"),
        "errorMsg": data.get("errorMsg"),
        "result_count": len(result.get("layoutParsingResults", [])),
        "output_dir": str(OUTPUT_DIR),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
