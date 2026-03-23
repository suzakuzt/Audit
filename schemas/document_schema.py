from __future__ import annotations

from pydantic import BaseModel, Field


STANDARD_FIELD_LABELS = {
    'factory_no': '\u5382\u53f7',
    'contract_no': '\u5408\u540c\u53f7',
    'consignee_name_address': '\u6536\u8d27\u4eba\u540d\u79f0\u5730\u5740',
    'product_name': '\u54c1\u540d',
    'weight': '\u91cd\u91cf',
    'unit_price': '\u5355\u4ef7',
    'amount': '\u91d1\u989d',
    'beneficiary_bank': '\u94f6\u884c\u6536\u6b3e\u4eba',
    'prepayment_amount': '\u9884\u4ed8\u6b3e\u91d1\u989d',
    'trade_term': '\u8d38\u6613\u6761\u6b3e',
    'total_weight': '\u603b\u91cd\u91cf',
    'total_amount': '\u603b\u91d1\u989d',
    'unit': '\u5355\u4f4d',
    'hs_code': 'HS\u7f16\u7801',
    'payment_term': '\u652f\u4ed8\u6761\u6b3e',
    'port_of_origin': '\u542f\u8fd0\u6e2f',
    'port_of_destination': '\u76ee\u7684\u6e2f',
    'shelf_life': '\u4fdd\u8d28\u671f',
    'shipment_date': '\u88c5\u8239\u65e5\u671f',
}

STANDARD_FIELDS = list(STANDARD_FIELD_LABELS.keys())


class MappedField(BaseModel):
    standard_field: str
    standard_label_cn: str
    source_field_name: str | None = None
    source_value: str | None = None
    confidence: float = 0.0
    uncertain: bool = False
    reason: str = ''


class DocumentExtractResult(BaseModel):
    doc_type: str
    mapped_fields: list[MappedField] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    uncertain_fields: list[str] = Field(default_factory=list)
    raw_summary: str = ''
