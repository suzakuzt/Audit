from __future__ import annotations

from pydantic import BaseModel, Field


STANDARD_FIELD_LABELS = {
    'factory_no': '\u5382\u53f7',
    'contract_no': '\u5408\u540c\u53f7',
    'consignee_name_address': '\u6536\u8d27\u4eba\u540d\u79f0\u5730\u5740',
    'product_name': '\u54c1\u540d',
    'weight': '\u5408\u540c\u91cd\u91cf',
    'unit_price': '\u5355\u4ef7',
    'amount': '\u91d1\u989d',
    'beneficiary_bank': '\u94f6\u884c\u6536\u76ca\u4eba',
    'prepayment_amount': '\u9884\u4ed8\u91d1\u989d',
    'trade_term': '\u8d38\u6613\u6761\u6b3e',
    'total_weight': '\u603b\u91cd\u91cf',
    'total_amount': '\u603b\u91d1\u989d',
    'unit': '\u5355\u4f4d\uff08KG\uff09',
    'hs_code': 'HS\u7f16\u7801',
    'payment_term': '\u652f\u4ed8\u6761\u6b3e',
    'port_of_origin': '\u542f\u8fd0\u6e2f',
    'port_of_destination': '\u76ee\u7684\u6e2f',
    'shelf_life': '\u4fdd\u8d28\u671f',
    'shipment_date': '\u88c5\u8239\u65e5\u671f',
    'invoice_no': '\u53d1\u7968\u53f7',
    'container_no': '\u67dc\u53f7',
    'box_count': '\u7bb1\u6570',
    'net_weight': '\u51c0\u91cd',
    'gross_weight': '\u6bdb\u91cd',
    'balance_amount': '\u5c3e\u6b3e\u91d1\u989d',
    'country_of_dispatch': '\u53d1\u8d27\u56fd\u5bb6',
    'vessel_name': '\u8239\u540d',
    'product_category': '\u54c1\u540d\u5927\u7c7b',
    'total_box_count': '\u603b\u7bb1\u6570',
    'total_net_weight': '\u603b\u51c0\u91cd',
    'total_gross_weight': '\u603b\u6bdb\u91cd',
    'seal_no': '\u94c5\u5c01\u53f7',
    'slaughter_date': '\u5c60\u5bb0\u65e5\u671f',
    'production_date': '\u751f\u4ea7\u65e5\u671f',
    'batch_no': '\u6279\u6b21\u53f7',
    'invoice_date': '\u53d1\u7968\u65e5\u671f',
    'export_country': '\u51fa\u53e3\u56fd/\u51fa\u53e3\u56fd\u5bb6',
    'origin_country': '\u52a8\u7269\u6765\u6e90\u56fd/\u539f\u4ea7\u56fd',
    'brand': '\u54c1\u724c',
    'cut_date': '\u5206\u5272\u65e5\u671f',
    'slaughterhouse_info': '\u5c60\u5bb0\u573a\u540d\u79f0\u5730\u5740\u6ce8\u518c\u53f7',
    'processing_plant_info': '\u5206\u5272\u4f01\u4e1a\u540d\u79f0\u5730\u5740\u6ce8\u518c\u53f7',
    'cold_storage_info': '\u51b7\u5e93\u540d\u79f0\u5730\u5740\u6ce8\u518c\u53f7',
    'total_package_count': '\u603b\u5305\u88c5\u6570',
    'bl_no': '\u63d0\u5355\u53f7',
    'notify_party_name_address': '\u901a\u77e5\u65b9\u540d\u79f0\u5730\u5740',
    'vessel_voyage': '\u8239\u540d\u822a\u6b21',
    'discharge_port': '\u5378\u8d27\u6e2f',
    'container_seal_no': '\u96c6\u88c5\u7bb1\u94c5\u5c01\u53f7',
    'issue_date': '\u7b7e\u53d1\u5730\u65e5\u671f',
    'health_cert_seal_no': '\u536b\u751f\u8bc1\u94c5\u5c01\u53f7',
}

STANDARD_FIELD_LEVELS = {
    'factory_no': 1,
    'contract_no': 1,
    'consignee_name_address': 1,
    'product_name': 1,
    'weight': 1,
    'unit_price': 1,
    'amount': 1,
    'beneficiary_bank': 1,
    'prepayment_amount': 1,
    'trade_term': 1,
    'total_weight': 1,
    'total_amount': 1,
    'unit': 2,
    'hs_code': 2,
    'payment_term': 1,
    'port_of_origin': 2,
    'port_of_destination': 2,
    'shelf_life': 1,
    'shipment_date': 2,
    'invoice_no': 2,
    'container_no': 2,
    'box_count': 2,
    'net_weight': 2,
    'gross_weight': 2,
    'balance_amount': 2,
    'country_of_dispatch': 2,
    'vessel_name': 2,
    'product_category': 2,
    'total_box_count': 2,
    'total_net_weight': 2,
    'total_gross_weight': 2,
    'seal_no': 2,
    'slaughter_date': 2,
    'production_date': 2,
    'batch_no': 2,
    'invoice_date': 2,
    'export_country': 2,
    'origin_country': 2,
    'brand': 2,
    'cut_date': 2,
    'slaughterhouse_info': 2,
    'processing_plant_info': 2,
    'cold_storage_info': 2,
    'total_package_count': 2,
    'bl_no': 2,
    'notify_party_name_address': 2,
    'vessel_voyage': 2,
    'discharge_port': 2,
    'container_seal_no': 2,
    'issue_date': 2,
    'health_cert_seal_no': 2,
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
