from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import KVCandidate, MergedBlock
from .utils import (
    bbox_center_y,
    ensure_bbox,
    is_amount_like,
    is_date_like,
    is_identifier_like,
    is_percent_like,
    normalize_text,
    union_bbox,
    y_overlap_ratio,
)


INLINE_PATTERN = re.compile(
    r"^\s*(?P<label>[A-Za-z\u4e00-\u9fff][^:\n]{1,50}?)(?:\s*[:：]\s*|\s{1,3})(?P<value>[^\n]{1,120})\s*$"
)


@dataclass(slots=True)
class KVBuilderConfig:
    max_horizontal_distance: float = 320.0
    max_vertical_distance: float = 110.0
    same_row_y_tolerance: float = 16.0
    top_n_per_label: int = 3


def build_kv_candidates(blocks: list[MergedBlock], config: KVBuilderConfig | None = None) -> list[KVCandidate]:
    cfg = config or KVBuilderConfig()
    if not blocks:
        return []
    candidates: list[KVCandidate] = []
    counter = 0

    for block in blocks:
        inline = _extract_inline_pair(block)
        if inline is not None:
            counter += 1
            candidates.append(
                KVCandidate(
                    candidate_id=f"kv_{counter}",
                    label_text=inline[0],
                    value_text=inline[1],
                    page=block.page,
                    bbox=list(block.bbox),
                    score=_value_format_bonus(inline[1], base=0.82),
                    relation_type="inline",
                    label_block_id=block.block_id,
                    value_block_id=block.block_id,
                    source_block_ids=[*block.source_block_ids],
                )
            )

    for label in blocks:
        label_text = normalize_text(label.text)
        if not _looks_like_label(label_text):
            continue
        neighbors = _find_spatial_candidates(label, blocks, cfg)
        for score, relation_type, value_block in neighbors[: cfg.top_n_per_label]:
            value_text = normalize_text(value_block.text)
            if not value_text or value_text == label_text:
                continue
            counter += 1
            candidates.append(
                KVCandidate(
                    candidate_id=f"kv_{counter}",
                    label_text=label_text.rstrip(":："),
                    value_text=value_text,
                    page=label.page,
                    bbox=union_bbox(ensure_bbox(label.bbox), ensure_bbox(value_block.bbox)),
                    score=_value_format_bonus(value_text, base=score),
                    relation_type=relation_type,
                    label_block_id=label.block_id,
                    value_block_id=value_block.block_id,
                    source_block_ids=[*label.source_block_ids, *value_block.source_block_ids],
                )
            )
    return _dedupe_kv(candidates)


def _extract_inline_pair(block: MergedBlock) -> tuple[str, str] | None:
    text = normalize_text(block.text)
    match = INLINE_PATTERN.match(text)
    if not match:
        return None
    label = normalize_text(match.group("label")).rstrip(":：")
    value = normalize_text(match.group("value"))
    if not label or not value:
        return None
    if len(label) > 60 or len(value) > 180:
        return None
    return label, value


def _looks_like_label(text: str) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) > 36:
        return False
    if ":" in stripped or "：" in stripped:
        return True
    tokens = stripped.split()
    return len(tokens) <= 5 and any(ch.isalpha() or ("\u4e00" <= ch <= "\u9fff") for ch in stripped)


def _find_spatial_candidates(label: MergedBlock, blocks: list[MergedBlock], cfg: KVBuilderConfig) -> list[tuple[float, str, MergedBlock]]:
    results: list[tuple[float, str, MergedBlock]] = []
    for other in blocks:
        if other.block_id == label.block_id or other.page != label.page:
            continue
        relation, score = _relation_score(label, other, cfg)
        if relation:
            results.append((score, relation, other))
    results.sort(key=lambda item: item[0], reverse=True)
    return results


def _relation_score(label: MergedBlock, value: MergedBlock, cfg: KVBuilderConfig) -> tuple[str, float]:
    lbox = label.bbox
    vbox = value.bbox
    x_distance = vbox[0] - lbox[2]
    y_distance = abs(bbox_center_y(vbox) - bbox_center_y(lbox))
    same_row = y_overlap_ratio(lbox, vbox) >= 0.45 or y_distance <= cfg.same_row_y_tolerance

    if same_row and 0 <= x_distance <= cfg.max_horizontal_distance:
        score = 0.65 + max(0.0, 0.2 * (1 - min(1.0, x_distance / cfg.max_horizontal_distance)))
        score += 0.06
        return "left_right", score

    downward_distance = vbox[1] - lbox[3]
    left_align = abs(vbox[0] - lbox[0]) <= 80.0
    if left_align and 0 <= downward_distance <= cfg.max_vertical_distance:
        score = 0.62 + max(0.0, 0.22 * (1 - min(1.0, downward_distance / cfg.max_vertical_distance)))
        return "top_down", score

    return "", 0.0


def _value_format_bonus(value_text: str, base: float) -> float:
    score = base
    if is_date_like(value_text):
        score += 0.08
    if is_amount_like(value_text):
        score += 0.08
    if is_percent_like(value_text):
        score += 0.05
    if is_identifier_like(value_text):
        score += 0.06
    return round(min(0.99, max(0.1, score)), 4)


def _dedupe_kv(candidates: list[KVCandidate]) -> list[KVCandidate]:
    result: list[KVCandidate] = []
    seen: set[tuple[str, str, int, str]] = set()
    for item in sorted(candidates, key=lambda x: x.score, reverse=True):
        marker = (
            normalize_text(item.label_text).lower(),
            normalize_text(item.value_text).lower(),
            item.page,
            item.relation_type,
        )
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result

