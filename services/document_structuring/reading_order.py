from __future__ import annotations

from collections import defaultdict

from .schemas import MergedBlock
from .utils import bbox_center_x


def assign_reading_order(blocks: list[MergedBlock]) -> list[MergedBlock]:
    if not blocks:
        return []
    page_groups: dict[int, list[MergedBlock]] = defaultdict(list)
    for block in blocks:
        page_groups[block.page].append(block)

    next_index = 0
    ordered_result: list[MergedBlock] = []
    for page in sorted(page_groups):
        page_blocks = page_groups[page]
        if _is_two_column_layout(page_blocks):
            left, right = _split_columns(page_blocks)
            page_order = sorted(left, key=lambda item: (item.bbox[1], item.bbox[0])) + sorted(
                right, key=lambda item: (item.bbox[1], item.bbox[0])
            )
        else:
            page_order = sorted(page_blocks, key=lambda item: (item.bbox[1], item.bbox[0]))
        for block in page_order:
            next_index += 1
            block.reading_order_index = next_index
            ordered_result.append(block)
    return ordered_result


def _is_two_column_layout(blocks: list[MergedBlock]) -> bool:
    if len(blocks) < 6:
        return False
    centers = sorted(bbox_center_x(item.bbox) for item in blocks)
    if len(centers) < 6:
        return False
    gaps = [centers[idx + 1] - centers[idx] for idx in range(len(centers) - 1)]
    if not gaps:
        return False
    largest_gap = max(gaps)
    median_gap = sorted(gaps)[len(gaps) // 2]
    return largest_gap > max(80.0, median_gap * 3.0)


def _split_columns(blocks: list[MergedBlock]) -> tuple[list[MergedBlock], list[MergedBlock]]:
    centers = sorted(bbox_center_x(item.bbox) for item in blocks)
    gaps = [(centers[idx + 1] - centers[idx], idx) for idx in range(len(centers) - 1)]
    _, split_at = max(gaps, key=lambda item: item[0])
    pivot = (centers[split_at] + centers[split_at + 1]) / 2.0
    left = [item for item in blocks if bbox_center_x(item.bbox) <= pivot]
    right = [item for item in blocks if bbox_center_x(item.bbox) > pivot]
    return left, right

