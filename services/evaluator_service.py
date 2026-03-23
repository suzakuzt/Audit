from __future__ import annotations

from schemas.evaluation_schema import EvaluationDetail, EvaluationResult
from utils.json_utils import normalize_text


def evaluate_extraction(ai_result: dict, gold_answer: dict[str, str]) -> EvaluationResult:
    mapped_fields = {
        item.get('standard_field', ''): item.get('source_value', '')
        for item in ai_result.get('mapped_fields', [])
        if item.get('standard_field')
    }

    details: list[EvaluationDetail] = []
    correct_fields = 0
    missing_fields = 0
    wrong_fields = 0

    for field_name, expected_value in gold_answer.items():
        ai_value = mapped_fields.get(field_name, '')
        expected_norm = normalize_text(expected_value)
        ai_norm = normalize_text(ai_value)

        if not expected_norm and not ai_norm:
            status = 'empty'
        elif expected_norm and ai_norm == expected_norm:
            status = 'correct'
            correct_fields += 1
        elif expected_norm and not ai_norm:
            status = 'missing'
            missing_fields += 1
        else:
            status = 'wrong'
            wrong_fields += 1

        details.append(
            EvaluationDetail(
                standard_field=field_name,
                expected_value=expected_value,
                ai_value=ai_value,
                status=status,
            )
        )

    total_fields = len(gold_answer)
    accuracy = round(correct_fields / total_fields, 4) if total_fields else 0.0
    return EvaluationResult(
        total_fields=total_fields,
        correct_fields=correct_fields,
        missing_fields=missing_fields,
        wrong_fields=wrong_fields,
        accuracy=accuracy,
        details=details,
    )
