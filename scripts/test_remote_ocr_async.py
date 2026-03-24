import json
import os
import sys
import time
from pathlib import Path

import requests


JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
TOKEN = "409b5b61c174ad27a633f1162a4e152bdc758649"
MODEL = "PaddleOCR-VL-1.5"
DEFAULT_FILE_PATH = Path(r"D:\360MoveData\Users\tongzhu\Desktop\审单文件夹\审单文件30套0710\L5137 无误\L5137 合同.pdf")
SUMMARY_PATH = Path(r"D:\Project\audit_system\runtime_logs\remote_ocr_async_result.json")
OUTPUT_DIR = Path(r"D:\Project\audit_system\runtime_logs\remote_ocr_async_output")


def main() -> int:
    file_path = Path(os.environ.get("REMOTE_OCR_FILE", str(DEFAULT_FILE_PATH))).resolve()
    headers = {"Authorization": f"bearer {TOKEN}"}
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    if not file_path.exists():
        print(f"Error: File not found at {file_path}")
        return 1

    data = {
        "model": MODEL,
        "optionalPayload": json.dumps(optional_payload, ensure_ascii=False),
    }

    with file_path.open("rb") as f:
        files = {"file": f}
        job_response = requests.post(JOB_URL, headers=headers, data=data, files=files, timeout=180)

    summary: dict[str, object] = {
        "file_path": str(file_path),
        "submit_status_code": job_response.status_code,
    }
    if job_response.status_code != 200:
        summary["submit_error_body"] = job_response.text[:2000]
        SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 1

    job_data = job_response.json().get("data") or {}
    job_id = str(job_data.get("jobId", "") or "")
    summary["job_id"] = job_id

    poll_states: list[dict[str, object]] = []
    jsonl_url = ""
    for _ in range(60):
        result_response = requests.get(f"{JOB_URL}/{job_id}", headers=headers, timeout=180)
        result_response.raise_for_status()
        body = result_response.json().get("data") or {}
        state = str(body.get("state", "") or "")
        progress = body.get("extractProgress") or {}
        poll_states.append(
            {
                "state": state,
                "totalPages": progress.get("totalPages"),
                "extractedPages": progress.get("extractedPages"),
                "startTime": progress.get("startTime"),
                "endTime": progress.get("endTime"),
            }
        )
        if state == "done":
            result_url = body.get("resultUrl") or {}
            jsonl_url = str(result_url.get("jsonUrl", "") or "")
            break
        if state == "failed":
            summary["failed_error"] = body.get("errorMsg")
            break
        time.sleep(5)

    summary["poll_states"] = poll_states
    summary["jsonl_url"] = jsonl_url

    if jsonl_url:
        jsonl_response = requests.get(jsonl_url, timeout=180)
        jsonl_response.raise_for_status()
        lines = [line.strip() for line in jsonl_response.text.splitlines() if line.strip()]
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        page_num = 0
        markdown_files: list[str] = []
        for line in lines:
            payload = json.loads(line)
            result = payload.get("result") or {}
            for res in result.get("layoutParsingResults") or []:
                md_filename = OUTPUT_DIR / f"doc_{page_num}.md"
                md_filename.write_text(((res.get("markdown") or {}).get("text") or ""), encoding="utf-8")
                markdown_files.append(str(md_filename))
                page_num += 1
        summary["jsonl_line_count"] = len(lines)
        summary["markdown_files"] = markdown_files

    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
