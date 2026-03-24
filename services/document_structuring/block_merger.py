from __future__ import annotations

from dataclasses import dataclass

from .schemas import MergedBlock, RawBlock
from .utils import bbox_height, normalize_text, union_bbox


@dataclass(slots=True)
class BlockMergerConfig:
    x_distance_threshold: float = 80.0
    y_distance_threshold: float = 28.0
    left_edge_tolerance: float = 42.0
    line_height_ratio_tolerance: float = 0.65


TEXT_COMPATIBLE_TYPES = {
    "text",
    "paragraph",
    "title",
    "header",
    "footer",
    "list",
    "address",
}


def merge_blocks(raw_blocks: list[RawBlock], config: BlockMergerConfig | None = None) -> list[MergedBlock]:
    if not raw_blocks:
        return []
    cfg = config or BlockMergerConfig()
    ordered = sorted(raw_blocks, key=lambda item: (item.page, item.bbox[1], item.bbox[0]))
    merged: list[MergedBlock] = []

    for raw in ordered:
        if not merged:
            merged.append(_from_raw(raw, 1))
            continue
        prev = merged[-1]
        if _can_merge(prev, raw, cfg):
            prev_text = normalize_text(prev.text)
            curr_text = normalize_text(raw.text)
            joiner = "\n" if _should_join_as_newline(prev, raw) else " "
            prev.text = f"{prev_text}{joiner}{curr_text}".strip()
            prev.bbox = union_bbox(prev.bbox, raw.bbox)
            prev.source_block_ids.append(raw.block_id)
            continue
        merged.append(_from_raw(raw, len(merged) + 1))
    return merged


def _from_raw(raw: RawBlock, index: int) -> MergedBlock:
    return MergedBlock(
        block_id=f"merged_{index}",
        block_type=str(raw.block_type or "text"),
        text=normalize_text(raw.text),
        page=raw.page,
        bbox=list(raw.bbox),
        source_block_ids=[raw.block_id],
        metadata={"source_raw_count": 1},
    )


def _can_merge(prev: MergedBlock, current: RawBlock, cfg: BlockMergerConfig) -> bool:
    if prev.page != current.page:
        return False
    if not _is_type_compatible(prev.block_type, current.block_type):
        return False
    prev_bbox = prev.bbox
    cur_bbox = current.bbox
    y_gap = cur_bbox[1] - prev_bbox[3]
    x_gap = abs(cur_bbox[0] - prev_bbox[0])
    left_edge_close = x_gap <= cfg.left_edge_tolerance
    near_vertical = -8.0 <= y_gap <= cfg.y_distance_threshold
    near_horizontal = abs(cur_bbox[1] - prev_bbox[1]) <= cfg.y_distance_threshold and abs(cur_bbox[0] - prev_bbox[2]) <= cfg.x_distance_threshold
    if not (near_vertical or near_horizontal):
        return False
    prev_height = bbox_height(prev_bbox)
    cur_height = bbox_height(cur_bbox)
    if prev_height <= 0 or cur_height <= 0:
        return left_edge_close
    ratio = min(prev_height, cur_height) / max(prev_height, cur_height)
    return left_edge_close and ratio >= cfg.line_height_ratio_tolerance


def _is_type_compatible(prev_type: str, curr_type: str) -> bool:
    a = str(prev_type or "text").lower()
    b = str(curr_type or "text").lower()
    if a == b:
        return True
    return a in TEXT_COMPATIBLE_TYPES and b in TEXT_COMPATIBLE_TYPES


def _should_join_as_newline(prev: MergedBlock, current: RawBlock) -> bool:
    y_gap = current.bbox[1] - prev.bbox[3]
    return y_gap > 4.0

