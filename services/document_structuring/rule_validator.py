from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any


DATE_FULL_PATTERN = re.compile(r"^(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})$")
AMOUNT_FULL_PATTERN = re.compile(r"^(?:USD|CNY|EUR|RMB|US\$|\$|¥)?\s?\d{1,3}(?:,\d{3})*(?:\.\d{1,4})?$", re.I)
CODE_FULL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._/\-]{2,}$", re.I)


@dataclass(slots=True)
class RuleValidationIssue:
    code: str
    level: str
    message: str
    field: str | None = None
    evidence: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class RuleValidationResult:
    passed: bool
    issues: list[RuleValidationIssue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [
                {
                    "code": issue.code,
                    "level": issue.level,
                    "message": issue.message,
                    "field": issue.field,
                    "evidence": issue.evidence,
                }
                for issue in self.issues
            ],
        }


def validate_business_output(payload: dict[str, Any]) -> RuleValidationResult:
    data = payload if isinstance(payload, dict) else {}
    issues: list[RuleValidationIssue] = []

    for key, value in data.items():
        key_lower = str(key).lower()
        value_str = str(value or "").strip()
        if not value_str:
            continue
        if "date" in key_lower and not DATE_FULL_PATTERN.match(value_str):
            issues.append(RuleValidationIssue("DATE_FORMAT_INVALID", "warning", "日期格式不合法", key, {"value": value_str}))
        if any(token in key_lower for token in ("amount", "price", "total")) and not AMOUNT_FULL_PATTERN.match(value_str):
            issues.append(RuleValidationIssue("AMOUNT_FORMAT_INVALID", "warning", "金额格式不合法", key, {"value": value_str}))
        if any(token in key_lower for token in ("no", "number", "code", "id")) and len(value_str) >= 3 and not CODE_FULL_PATTERN.match(value_str):
            issues.append(RuleValidationIssue("CODE_FORMAT_SUSPECT", "warning", "编号格式疑似异常", key, {"value": value_str}))

    line_items = data.get("line_items")
    if isinstance(line_items, list):
        for idx, row in enumerate(line_items, start=1):
            if not isinstance(row, dict):
                continue
            qty = _to_float(row.get("qty") or row.get("quantity"))
            unit_price = _to_float(row.get("unit_price"))
            amount = _to_float(row.get("amount"))
            if qty is None or unit_price is None or amount is None:
                continue
            expected = qty * unit_price
            if abs(expected - amount) > max(0.01, abs(amount) * 0.03):
                issues.append(
                    RuleValidationIssue(
                        "LINE_TOTAL_MISMATCH",
                        "warning",
                        "数量 × 单价 与 行金额不一致",
                        "line_items",
                        {"row_index": idx, "qty": qty, "unit_price": unit_price, "amount": amount, "expected": round(expected, 4)},
                    )
                )
        total_amount = _to_float(data.get("total_amount"))
        if total_amount is not None:
            subtotal = sum(_to_float((row or {}).get("amount")) or 0.0 for row in line_items if isinstance(row, dict))
            if subtotal > 0 and abs(subtotal - total_amount) > max(0.01, abs(total_amount) * 0.03):
                issues.append(
                    RuleValidationIssue(
                        "TOTAL_AMOUNT_MISMATCH",
                        "warning",
                        "明细合计与总金额不一致",
                        "total_amount",
                        {"line_sum": round(subtotal, 4), "total_amount": total_amount},
                    )
                )

    for required in ("contract_no", "invoice_no", "total_amount"):
        if required in data and (data.get(required) is None or str(data.get(required)).strip() == ""):
            issues.append(
                RuleValidationIssue(
                    "EMPTY_REQUIRED_FIELD",
                    "warning",
                    "关键字段为空",
                    required,
                    {},
                )
            )

    return RuleValidationResult(passed=not issues, issues=issues)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"[^\d.\-]", "", text)
    if text in {"", "-", ".", "-."}:
        return None
    try:
        return float(text)
    except Exception:
        return None
