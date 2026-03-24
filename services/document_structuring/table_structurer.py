from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .schemas import MergedBlock, TableCandidate, TableCell
from .utils import bbox_center_x, bbox_center_y, normalize_text, union_bbox


@dataclass(slots=True)
class TableStructurerConfig:
    row_y_tolerance: float = 12.0
    min_rows: int = 1
    min_columns: int = 3


HEADER_KEYWORDS = {
    "description",
    "qty",
    "quantity",
    "unit",
    "price",
    "amount",
    "total",
    "packing",
    "tons",
    "us$",
}


def build_table_candidates(blocks: list[MergedBlock], config: TableStructurerConfig | None = None) -> list[TableCandidate]:
    cfg = config or TableStructurerConfig()
    if not blocks:
        return []
    page_groups: dict[int, list[MergedBlock]] = defaultdict(list)
    for block in blocks:
        page_groups[block.page].append(block)

    table_counter = 0
    candidates: list[TableCandidate] = []
    for page, page_blocks in sorted(page_groups.items()):
        rows = _cluster_rows(page_blocks, cfg.row_y_tolerance)
        if len(rows) < cfg.min_rows + 1:
            continue
        dense_rows = [row for row in rows if len(row) >= cfg.min_columns]
        if len(dense_rows) < cfg.min_rows + 1:
            continue
        header_row = _pick_header_row(dense_rows)
        anchors = [bbox_center_x(block.bbox) for block in sorted(header_row, key=lambda item: item.bbox[0])]
        if len(anchors) < cfg.min_columns:
            continue
        headers = [normalize_text(item.text) for item in sorted(header_row, key=lambda b: b.bbox[0])]
        table_rows: list[list[str]] = []
        cells: list[TableCell] = []
        source_ids: list[str] = []
        bbox_list: list[list[float]] = []
        table_row_index = 0
        for row in dense_rows:
            texts, row_cells = _materialize_row(page, table_row_index, row, anchors)
            if not any(texts):
                continue
            # skip header-like row in table body
            if _looks_like_header_row(texts):
                continue
            table_rows.append(texts)
            cells.extend(row_cells)
            source_ids.extend([sid for block in row for sid in block.source_block_ids])
            bbox_list.extend([block.bbox for block in row])
            table_row_index += 1
        if not table_rows:
            continue
        table_counter += 1
        candidates.append(
            TableCandidate(
                table_id=f"table_{table_counter}",
                page=page,
                headers=headers,
                rows=table_rows,
                cells=cells,
                source_block_ids=_dedupe_ids(source_ids),
                bbox=union_bbox(*bbox_list),
                confidence=round(min(0.97, 0.70 + 0.03 * len(table_rows)), 3),
            )
        )
    return candidates


def _cluster_rows(blocks: list[MergedBlock], tolerance: float) -> list[list[MergedBlock]]:
    ordered = sorted(blocks, key=lambda item: (item.bbox[1], item.bbox[0]))
    rows: list[list[MergedBlock]] = []
    for block in ordered:
        y = bbox_center_y(block.bbox)
        placed = False
        for row in rows:
            row_y = sum(bbox_center_y(item.bbox) for item in row) / max(1, len(row))
            if abs(y - row_y) <= tolerance:
                row.append(block)
                placed = True
                break
        if not placed:
            rows.append([block])
    for row in rows:
        row.sort(key=lambda item: item.bbox[0])
    return rows


def _pick_header_row(rows: list[list[MergedBlock]]) -> list[MergedBlock]:
    for row in rows[:4]:
        row_text = " ".join(normalize_text(item.text).lower() for item in row)
        if any(keyword in row_text for keyword in HEADER_KEYWORDS):
            return row
    return rows[0]


def _materialize_row(
    page: int,
    row_index: int,
    row_blocks: list[MergedBlock],
    anchors: list[float],
) -> tuple[list[str], list[TableCell]]:
    values = [""] * len(anchors)
    cells: list[TableCell] = []
    for block in row_blocks:
        text = normalize_text(block.text)
        if not text:
            continue
        col_idx = _nearest_anchor(bbox_center_x(block.bbox), anchors)
        values[col_idx] = f"{values[col_idx]} {text}".strip()
        cells.append(
            TableCell(
                text=text,
                row_index=row_index,
                col_index=col_idx,
                page=page,
                bbox=list(block.bbox),
                source_block_ids=[*block.source_block_ids],
            )
        )
    return values, cells


def _nearest_anchor(x: float, anchors: list[float]) -> int:
    distances = [(abs(x - anchor), idx) for idx, anchor in enumerate(anchors)]
    return min(distances, key=lambda item: item[0])[1]


def _looks_like_header_row(values: list[str]) -> bool:
    lower = " ".join(normalize_text(value).lower() for value in values)
    return any(keyword in lower for keyword in HEADER_KEYWORDS)


def _dedupe_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in ids:
        key = str(item or "")
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered
