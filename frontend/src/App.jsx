import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import PromptLearningCenter from './PromptLearningCenter';
import { Component } from 'react';

const CORE_FIELDS = ['factory_no', 'contract_no', 'consignee_name_address', 'product_name', 'weight', 'unit_price', 'amount', 'beneficiary_bank', 'prepayment_amount', 'trade_term', 'total_weight', 'total_amount', 'hs_code', 'payment_term', 'port_of_origin', 'port_of_destination', 'shelf_life', 'shipment_date'];

const CONTRACT_TEMPLATE_FIELDS = [...CORE_FIELDS, 'unit'];
const INVOICE_TEMPLATE_FIELDS = ['invoice_no', 'consignee_name_address', 'port_of_origin', 'port_of_destination', 'payment_term', 'trade_term', 'container_no', 'product_name', 'box_count', 'net_weight', 'gross_weight', 'unit_price', 'total_amount', 'prepayment_amount', 'balance_amount', 'contract_no', 'country_of_dispatch', 'vessel_name', 'product_category', 'hs_code', 'total_box_count', 'total_net_weight', 'total_gross_weight', 'seal_no', 'slaughter_date', 'production_date', 'shelf_life'];
const PACKING_TEMPLATE_FIELDS = ['invoice_no', 'consignee_name_address', 'port_of_origin', 'port_of_destination', 'container_no', 'product_name', 'box_count', 'net_weight', 'gross_weight', 'contract_no', 'vessel_name', 'production_date', 'shelf_life', 'factory_no', 'product_category', 'total_box_count', 'total_net_weight', 'total_gross_weight', 'seal_no', 'slaughter_date'];
const NO_WOOD_TEMPLATE_FIELDS = ['invoice_no', 'consignee_name_address', 'container_no', 'product_name', 'box_count', 'net_weight', 'gross_weight', 'contract_no', 'product_category', 'vessel_name', 'port_of_origin', 'port_of_destination', 'seal_no', 'slaughter_date', 'production_date', 'shelf_life'];
const BATCH_TEMPLATE_FIELDS = ['invoice_no', 'consignee_name_address', 'port_of_origin', 'port_of_destination', 'container_no', 'seal_no', 'slaughter_date', 'production_date', 'shelf_life', 'product_name', 'batch_no', 'box_count', 'net_weight', 'gross_weight'];
const ORIGIN_TEMPLATE_FIELDS = ['invoice_no', 'consignee_name_address', 'invoice_date', 'port_of_destination', 'box_count', 'product_name', 'container_no', 'net_weight', 'gross_weight', 'hs_code', 'product_category', 'total_box_count', 'total_net_weight', 'total_gross_weight', 'vessel_name'];
const HEALTH_TEMPLATE_FIELDS = ['consignee_name_address', 'export_country', 'port_of_destination', 'port_of_origin', 'container_no', 'seal_no', 'hs_code', 'product_name', 'origin_country', 'brand', 'batch_no', 'production_date', 'slaughter_date', 'cut_date', 'shelf_life', 'slaughterhouse_info', 'processing_plant_info', 'cold_storage_info', 'total_package_count', 'total_net_weight', 'total_gross_weight'];
const BL_TEMPLATE_FIELDS = ['bl_no', 'consignee_name_address', 'notify_party_name_address', 'vessel_voyage', 'port_of_origin', 'port_of_destination', 'discharge_port', 'total_box_count', 'product_name', 'total_gross_weight', 'container_no', 'container_seal_no', 'issue_date', 'shipment_date', 'hs_code', 'health_cert_seal_no', 'net_weight', 'total_net_weight'];
const HALAL_TEMPLATE_FIELDS = ['invoice_no', 'consignee_name_address', 'port_of_origin', 'port_of_destination', 'slaughter_date', 'production_date', 'product_name', 'brand', 'box_count', 'shelf_life', 'net_weight', 'gross_weight', 'container_no'];
const BUILTIN_TEMPLATE_IDS = new Set(['core_fields', 'contract_template', 'invoice_template', 'packing_template', 'no_wood_template', 'batch_template', 'origin_template', 'health_template', 'bl_template', 'halal_template', 'all_fields']);

const FIELD_PRESETS = [
  { id: 'core_fields', label: '\u6838\u5fc3\u5b57\u6bb5', fields: CORE_FIELDS },
  { id: 'all_fields', label: '\u5168\u90e8\u5b57\u6bb5', fields: 'ALL' },
];

const DEFAULT_TEMPLATES = [
  { id: 'core_fields', name: '核心字段', fields: CORE_FIELDS },
  {
    id: 'contract_template',
    name: '合同模板',
    fields: CONTRACT_TEMPLATE_FIELDS,
  },
  {
    id: 'invoice_template',
    name: '发票模板',
    fields: INVOICE_TEMPLATE_FIELDS,
  },
  {
    id: 'packing_template',
    name: '装箱单模板',
    fields: PACKING_TEMPLATE_FIELDS,
  },
  {
    id: 'no_wood_template',
    name: '无木制装箱单模板',
    fields: NO_WOOD_TEMPLATE_FIELDS,
  },
  {
    id: 'batch_template',
    name: '批次清单模板',
    fields: BATCH_TEMPLATE_FIELDS,
  },
  {
    id: 'origin_template',
    name: '原产地证书模板',
    fields: ORIGIN_TEMPLATE_FIELDS,
  },
  {
    id: 'health_template',
    name: '卫生证模板',
    fields: HEALTH_TEMPLATE_FIELDS,
  },
  {
    id: 'bl_template',
    name: '提单模板',
    fields: BL_TEMPLATE_FIELDS,
  },
  {
    id: 'halal_template',
    name: '清真证书模板',
    fields: HALAL_TEMPLATE_FIELDS,
  },
  { id: 'all_fields', name: '自定义', fields: 'ALL' },
];

const EXTRACTION_MODES = [
  { id: 'bundle', label: '\u6574\u5957\u5355\u636e\u63d0\u53d6', description: '\u5c06\u4e00\u6574\u5957\u4e1a\u52a1\u5355\u636e\u653e\u5728\u4e00\u8d77\uff0c\u4ece\u6574\u5957\u6587\u4ef6\u4e2d\u6c47\u603b\u63d0\u53d6\u5173\u952e\u6807\u51c6\u5b57\u6bb5' },
  { id: 'single', label: '\u6309\u540c\u54c1\u7c7b\u5bf9\u6bd4', description: '\u5c06\u540c\u4e00\u54c1\u7c7b\u7684\u5355\u636e\u653e\u5728\u4e00\u8d77\uff0c\u6309\u540c\u4e00\u6807\u51c6\u5b57\u6bb5\u5bf9\u6bd4\u663e\u793a\uff0c\u4e5f\u652f\u6301\u53ea\u4e0a\u4f20\u5355\u5f20\u7968\u636e\u8fdb\u884c\u8bc6\u522b' },
];

const SINGLE_DOC_TYPES = [
  '\u81ea\u52a8\u5224\u65ad',
  '\u5408\u540c',
  '\u53d1\u7968',
  '\u88c5\u7bb1\u5355',
  '\u63d0\u5355',
  '\u539f\u4ea7\u5730\u8bc1\u4e66',
  '\u536b\u751f\u8bc1',
  '\u6e05\u771f\u8bc1\u4e66',
  '\u6279\u6b21\u6e05\u5355',
  '\u65e0\u6728\u5236\u88c5\u7bb1\u58f0\u660e',
];

const FIELD_COLORS = {
  contract_no: '#f59e0b',
  factory_no: '#0f766e',
  product_name: '#2563eb',
  amount: '#dc2626',
  unit_price: '#7c3aed',
  weight: '#ea580c',
  shipment_date: '#0891b2',
};

const TEXT = {
  loading: '\u6b63\u5728\u52a0\u8f7d\u914d\u7f6e...',
  start: '\u5f00\u59cb\u6279\u91cf\u63d0\u53d6\u9a8c\u8bc1',
  save: '\u4fdd\u5b58\u786e\u8ba4\u7ed3\u679c',
  openPromptConfig: '\u63d0\u793a\u8bcd\u4f18\u5316\u4e2d\u5fc3',
  openPromptConfigAction: '\u67e5\u770b\u89c4\u5219\u9875',
  pageIntro: '\u8fd9\u4e2a\u9875\u9762\u53ea\u505a\u5173\u952e\u6807\u51c6\u5b57\u6bb5\u63d0\u53d6\u786e\u8ba4\u3002\u63d0\u793a\u8bcd\u3001\u5b66\u4e60\u8bb0\u5f55\u548c\u5386\u53f2\u5efa\u8bae\u90fd\u653e\u5728\u201c\u63d0\u793a\u8bcd\u914d\u7f6e\u201d\u5f39\u7a97\u91cc\u5904\u7406\u3002',
  resultTitle: '\u5173\u952e\u6807\u51c6\u5b57\u6bb5\u63d0\u53d6\u7ed3\u679c',
  resultIntro: '\u7cfb\u7edf\u5df2\u81ea\u52a8\u63d0\u53d6\u5173\u952e\u5b57\u6bb5\uff1b\u5982\u7cfb\u7edf\u5224\u65ad\u4e0d\u591f\u786e\u5b9a\uff0c\u4f1a\u6807\u8bb0\u201c\u5efa\u8bae\u786e\u8ba4\u201d\uff0c\u8bf7\u5feb\u901f\u6838\u5bf9\u3002',
  noResultRows: '\u8fd8\u6ca1\u6709\u53ef\u786e\u8ba4\u7684\u63d0\u53d6\u7ed3\u679c\u3002\u5148\u4e0a\u4f20\u6587\u4ef6\u5e76\u5f00\u59cb\u63d0\u53d6\u3002',
  saving: '\u6b63\u5728\u5199\u5165\u4eba\u5de5\u786e\u8ba4\u7ed3\u679c\u548c alias \u5e93\uff0c\u8bf7\u7a0d\u7b49...',
  saveDone: '\u4eba\u5de5\u786e\u8ba4\u7ed3\u679c\u5df2\u7ecf\u4fdd\u5b58\uff0c\u4f60\u73b0\u5728\u53ef\u4ee5\u7ee7\u7eed\u5207\u6362\u6587\u4ef6\u7b5b\u9009\u4e0b\u4e00\u6279\u5019\u9009\u5b57\u6bb5\u3002',
  requestFail: '\u8bf7\u6c42\u5931\u8d25',
  processFail: '\u5904\u7406\u5931\u8d25\uff1a',
  saveFail: '\u4fdd\u5b58\u5931\u8d25\uff1a',
  noFile: '\u8bf7\u5148\u9009\u62e9\u81f3\u5c11\u4e00\u4e2a PDF \u6587\u4ef6\u3002',
  noFilesSelected: '\u5f53\u524d\u8fd8\u6ca1\u6709\u9009\u62e9\u6587\u4ef6\u3002',
  queued: '\u5f85\u63d0\u4ea4',
  processing: '\u5904\u7406\u4e2d',
  done: '\u5df2\u5b8c\u6210',
  failed: '\u5904\u7406\u5931\u8d25',
  extracting: '\u7cfb\u7edf\u4f1a\u5148\u63d0\u53d6\u6587\u672c\uff0c\u5e76\u4f18\u5148\u53c2\u8003\u5df2\u786e\u8ba4\u8fc7\u7684\u5e38\u7528\u5b57\u6bb5\u5199\u6cd5\uff1b\u53ea\u6709\u4e0d\u591f\u786e\u5b9a\u7684\u5185\u5bb9\u624d\u4f1a\u7ee7\u7eed OCR / AI \u8bc6\u522b\uff0c\u8bf7\u7a0d\u7b49...',
  duplicateHint: '\u4ee5\u4e0b alias \u5df2\u7ecf\u5b58\u5728\uff0c\u672a\u91cd\u590d\u5199\u5165\uff1a',
  noDocs: '\u672c\u6b21\u6ca1\u6709\u8fd4\u56de\u53ef\u5c55\u793a\u7684\u5b57\u6bb5\u63d0\u53d6\u7ed3\u679c\u3002',
  noCandidates: '\u65e0\u53c2\u8003',
  noImage: '\u5f53\u524d\u6ca1\u6709\u53ef\u9884\u89c8\u7684\u56fe\u7247\u3002',
  noEvidence: '\u5f53\u524d\u6ca1\u6709\u5728\u62bd\u53d6\u6587\u672c\u4e2d\u5b9a\u4f4d\u5230\u660e\u663e\u7247\u6bb5\uff0c\u4f60\u53ef\u4ee5\u5148\u4eba\u5de5\u786e\u8ba4\u540e\u518d\u6c89\u6dc0 alias\u3002',
  zoomImage: '\u653e\u5927\u67e5\u770b',
  close: '\u5173\u95ed',
  view: '\u67e5\u770b',
  title: '\u6279\u91cf\u6838\u5fc3\u5b57\u6bb5\u63d0\u53d6\u9a8c\u8bc1\u5668',
  learningTitle: '\u63d0\u793a\u8bcd\u4f18\u5316\u4e2d\u5fc3',
};

const EMPTY_CONFIG = {
  prompt_text: '',
  prompt_file_name: 'extract_prompt_v1.txt',
  llm_base_url: 'https://api.deepseek.com',
  llm_model: 'deepseek-chat',
  ocr_model: 'deepseek-chat',
  llm_timeout: 180,
  use_alias_active: false,
  use_rule_active: true,
  enable_ocr: true,
  force_ocr: true,
  focus_fields: CORE_FIELDS,
  focus_labels: {},
  model_options: [
    { value: 'deepseek-chat', label: 'DeepSeek Chat' },
    { value: 'deepseek-reasoner', label: 'DeepSeek Reasoner' },
  ],
};

const EMPTY_LEARNING_CONFIG = {
  prompt_texts: {
    base: '',
    classify: '',
    field_understanding: '',
    suggestion: '',
  },
  prompt_flags: {
    classify: true,
    field_understanding: true,
    suggestion: true,
  },
  history: { records: [], suggestions: [] },
};

function normalizeText(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function normalizeSearchText(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9一-鿿]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function formatPercent(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return '0%';
  return `${Math.round(num)}%`;
}

function bytesToSize(size) {
  const num = Number(size || 0);
  if (!num) return '0 B';
  if (num < 1024) return `${num} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
  return `${(num / (1024 * 1024)).toFixed(2)} MB`;
}

function formatRate(value, total) {
  if (!total) return '0.0%';
  return `${((value / total) * 100).toFixed(1)}%`;
}

function tsvCell(value) {
  return String(value ?? '').replace(/[\t\r\n]+/g, ' ').trim();
}

function encodeUtf16Le(text) {
  const buffer = new Uint8Array(2 + text.length * 2);
  buffer[0] = 0xff;
  buffer[1] = 0xfe;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    buffer[2 + index * 2] = code & 0xff;
    buffer[3 + index * 2] = code >> 8;
  }
  return buffer;
}

function downloadTsv(fileName, rows) {
  const tsv = rows.map((row) => row.map(tsvCell).join('\t')).join('\r\n');
  const bytes = encodeUtf16Le(tsv);
  const blob = new Blob([bytes], { type: 'text/tab-separated-values;charset=utf-16le;' });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}

function resolveReviewState(row) {
  const value = String(row.sourceValue || '').trim();
  const fieldName = String(row.sourceFieldName || '').trim();
  const sourceKind = String(row.doc?.raw_text_result?.metadata?.source_kind || '');

  if (!value || !fieldName) {
    return { key: 'manual_review_required', label: '需人工确认', className: 'manual-review-required' };
  }
  if (sourceKind === 'scan_ocr') {
    return { key: 'review_suggested', label: '建议确认', className: 'review-suggested' };
  }
  return { key: 'confirmed', label: '已确认', className: 'confirmed' };
}

function extractionMarker(doc) {
  const raw = doc?.raw_text_result || {};
  const meta = raw.metadata || {};
  const extractionMeta = doc?.extraction_metadata || {};
  const sourceKind = String(meta.source_kind || '');
  const ocrStatus = String(meta.ocr_status || '');
  const ocrEngine = String(meta.ocr_engine || '');
  const decisionMode = String(extractionMeta.decision_mode || '');

  if (sourceKind === 'scan_ocr' && ocrStatus === 'applied') {
    if (ocrEngine === 'paddleocr') {
      return decisionMode === 'alias_fast_path'
        ? '\u767e\u5ea6 PaddleOCR -> DeepSeek \u5904\u7406 \u00b7 alias \u5feb\u901f\u5b9a\u4f4d'
        : '\u767e\u5ea6 PaddleOCR -> DeepSeek \u5904\u7406';
    }
    return decisionMode === 'alias_fast_path'
      ? 'OCR \u8bc6\u522b -> DeepSeek \u5904\u7406 \u00b7 alias \u5feb\u901f\u5b9a\u4f4d'
      : 'OCR \u8bc6\u522b -> DeepSeek \u5904\u7406';
  }
  if (sourceKind === 'scan_like' && ocrStatus === 'failed') {
    return 'OCR \u5931\u8d25\uff0c\u672a\u5b8c\u6210 DeepSeek \u5904\u7406';
  }
  if (decisionMode === 'alias_fast_path') {
    return '\u6807\u51c6\u6587\u672c\u63d0\u53d6 -> DeepSeek \u5904\u7406 \u00b7 alias \u5feb\u901f\u5b9a\u4f4d';
  }
  if (sourceKind === 'digital_text') {
    return '\u6807\u51c6\u6587\u672c\u63d0\u53d6 -> DeepSeek \u5904\u7406';
  }
  if (sourceKind === 'scan_like') {
    return '\u626b\u63cf\u4ef6\uff0c\u7b49\u5f85\u767e\u5ea6 PaddleOCR';
  }
  return '\u6807\u51c6\u6587\u672c\u63d0\u53d6 -> DeepSeek \u5904\u7406';
}

function selectedPresetId(selectedFields, allFields) {
  const normalized = [...selectedFields].sort().join('|');
  for (const preset of FIELD_PRESETS) {
    const presetFields = preset.fields === 'ALL' ? allFields : preset.fields;
    if ([...presetFields].sort().join('|') === normalized) return preset.id;
  }
  return 'custom';
}

function normalizeTemplateFields(fields, allFields) {
  if (fields === 'ALL') return 'ALL';
  const allowed = new Set(allFields || []);
  return (fields || []).filter((field) => allowed.has(field));
}

function mergeTemplatesWithDefaults(storedTemplates, allFields) {
  const normalizedDefaults = DEFAULT_TEMPLATES.map((template) => ({
    ...template,
    fields: normalizeTemplateFields(template.fields, allFields),
  })).filter((template) => template.fields === 'ALL' || template.fields.length);

  const stored = Array.isArray(storedTemplates) ? storedTemplates : [];
  const customTemplates = stored
    .map((template) => ({
      id: String(template.id || ''),
      name: String(template.name || '').trim() || '未命名模板',
      fields: normalizeTemplateFields(template.fields, allFields),
    }))
    .filter((template) => template.id && !BUILTIN_TEMPLATE_IDS.has(template.id))
    .filter((template) => template.fields === 'ALL' || template.fields.length);

  const mergedBuiltins = normalizedDefaults.map((template) => {
    const matched = stored.find((item) => String(item?.id || '') === template.id);
    if (!matched || template.fields === 'ALL') return template;
    const mergedFields = [...new Set([...(Array.isArray(matched.fields) ? matched.fields : []), ...template.fields])];
    return {
      ...template,
      name: String(matched.name || '').trim() || template.name,
      fields: normalizeTemplateFields(mergedFields, allFields),
    };
  });

  return [...mergedBuiltins, ...customTemplates];
}

function countTemplateLevels(fields, allFields, fieldLevels) {
  const resolved = fields === 'ALL' ? allFields : fields;
  return (resolved || []).reduce((acc, field) => {
    const level = Number(fieldLevels?.[field] || 2);
    if (level === 1) acc.level1 += 1;
    else acc.level2 += 1;
    return acc;
  }, { level1: 0, level2: 0 });
}

function collectEvidence(doc, field, extraTerms = []) {
  const mapping = (doc.standard_mappings || []).find((item) => item.standard_field === field) || {};
  const text = String(doc.raw_text_result?.text || '');
  const terms = [mapping.source_field_name, mapping.source_value, ...extraTerms].map((item) => String(item || '').trim()).filter(Boolean);
  const uniqueTerms = [...new Set(terms)];
  const snippets = [];
  uniqueTerms.forEach((term) => {
    let cursor = 0;
    let hits = 0;
    const termLower = term.toLowerCase();
    while (hits < 3) {
      const index = text.toLowerCase().indexOf(termLower, cursor);
      if (index === -1) break;
      snippets.push({ term, excerpt: text.slice(Math.max(0, index - 60), Math.min(text.length, index + term.length + 90)) });
      cursor = index + term.length;
      hits += 1;
    }
  });
  return snippets;
}

function bestVisualPage(doc, field, extraTerms = []) {
  const pages = Array.isArray(doc.visual_pages) ? doc.visual_pages.filter((page) => page?.image_data_url) : [];
  if (!pages.length) return null;
  const mapping = (doc.standard_mappings || []).find((item) => item.standard_field === field) || {};
  const terms = [mapping.source_field_name, mapping.source_value, ...extraTerms].map((item) => normalizeSearchText(item)).filter(Boolean);
  if (!terms.length) return pages[0];
  const scored = pages.map((page) => {
    const wordText = (page.words || []).map((word) => word.text || '').join(' ');
    const blockText = (page.blocks || []).map((block) => block.text || '').join(' ');
    const pageText = normalizeSearchText(wordText || blockText);
    const score = terms.reduce((sum, term) => sum + (pageText.includes(term) ? 1 : 0), 0);
    return { page, score };
  });
  scored.sort((a, b) => b.score - a.score || (a.page.page_number || 0) - (b.page.page_number || 0));
  return scored[0]?.page || pages[0];
}


function fieldColor(field) {
  return FIELD_COLORS[field] || '#0f766e';
}

function splitTokens(value) {
  return normalizeSearchText(value).split(' ').filter(Boolean);
}

function compactText(value) {
  return normalizeSearchText(value).replace(/\s+/g, '');
}

function collectHighlights(page, terms, field) {
  const words = Array.isArray(page?.words) ? page.words : [];
  const normalizedWords = words.map((word) => normalizeSearchText(word.text));
  const compactWords = words.map((word) => compactText(word.text));
  const seen = new Set();
  const boxes = [];

  const pushWordBox = (term, start, end) => {
    const matchedWords = words.slice(start, end);
    if (!matchedWords.length) return false;
    const key = `${term}:${start}:${end}`;
    if (seen.has(key)) return false;
    seen.add(key);
    boxes.push({
      term,
      color: fieldColor(field),
      x0: Math.min(...matchedWords.map((item) => Number(item.x0 || 0))),
      x1: Math.max(...matchedWords.map((item) => Number(item.x1 || 0))),
      top: Math.min(...matchedWords.map((item) => Number(item.top || 0))),
      bottom: Math.max(...matchedWords.map((item) => Number(item.bottom || 0))),
    });
    return true;
  };

  terms.forEach((term) => {
    const tokens = splitTokens(term);
    if (!tokens.length) return;
    for (let index = 0; index <= normalizedWords.length - tokens.length; index += 1) {
      let matched = true;
      for (let offset = 0; offset < tokens.length; offset += 1) {
        if (normalizedWords[index + offset] !== tokens[offset]) {
          matched = false;
          break;
        }
      }
      if (matched) {
        pushWordBox(term, index, index + tokens.length);
      }
    }
  });

  if (!boxes.length && words.length) {
    terms.forEach((term) => {
      const compactTerm = compactText(term);
      if (!compactTerm) return;
      for (let start = 0; start < compactWords.length; start += 1) {
        let merged = '';
        for (let end = start; end < Math.min(compactWords.length, start + 4); end += 1) {
          merged += compactWords[end];
          if (merged && (merged.includes(compactTerm) || compactTerm.includes(merged))) {
            if (pushWordBox(term, start, end + 1)) {
              return;
            }
          }
        }
      }
    });
  }

  if (boxes.length) {
    return boxes.slice(0, 12);
  }
  const blocks = Array.isArray(page?.blocks) ? page.blocks : [];
  const normalizedTerms = terms.map((term) => normalizeSearchText(term)).filter(Boolean);
  const compactTerms = terms.map((term) => ({ raw: term, compact: compactText(term) })).filter((item) => item.compact);
  blocks.forEach((block) => {
    const blockText = normalizeSearchText(block.text || '');
    const compactBlockText = compactText(block.text || '');
    if (!blockText && !compactBlockText) return;
    const matchedTerm = normalizedTerms.find((term) => blockText.includes(term))
      || compactTerms.find((item) => compactBlockText.includes(item.compact))?.raw;
    if (!matchedTerm) return;
    boxes.push({
      term: matchedTerm,
      color: fieldColor(field),
      x0: Number(block.x0 || 0),
      x1: Number(block.x1 || 0),
      top: Number(block.top || 0),
      bottom: Number(block.bottom || 0),
    });
  });
  return boxes.slice(0, 12);
}

function cloneDocuments(documents) {
  return (documents || []).map((doc) => ({
    ...doc,
    standard_mappings: (doc.standard_mappings || []).map((item) => ({ ...item })),
    manual_confirmation_rows: (doc.manual_confirmation_rows || []).map((item) => ({ ...item })),
  }));
}

function firstNonEmpty(...values) {
  return values.map((item) => String(item || '').trim()).find(Boolean) || '';
}

function clusterText(value) {
  return normalizeSearchText(value).replace(/\b(name|address|addr|no|number|and)\b/g, ' ').replace(/\s+/g, ' ').trim();
}

function semanticBlockLabel(block) {
  const labels = {
    numbering_info_block: '编号信息块',
    party_address_block: '主体地址块',
    party_address_candidate: '主体地址候选类',
    goods_info_block: '货物信息块',
    payment_term_block: '付款条款块',
    bank_info_block: '银行信息块',
    logistics_block: '物流信息块',
    remark_block: '备注补充块',
  };
  return labels[block] || block || '未分类';
}

function uniqueList(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function summarizeSemanticGroup(row, focusLabels) {
  const candidates = uniqueList(row.candidateStandardFields);
  const suggestedField = candidates[0] || row.field;
  const suggestedLabel = focusLabels?.[suggestedField] || suggestedField;
  if (row.semanticCandidateClass === 'party_address_candidate') {
    const candidateLabels = candidates.map((field) => focusLabels?.[field] || field);
    return {
      groupType: 'semantic_candidate',
      groupKey: `semantic:${row.semanticCandidateClass}:${candidates.join('|') || row.field}`,
      groupName: candidates.length > 1 ? '主体地址候选组' : `${suggestedLabel}候选组`,
      suggestedField,
      suggestedLabel,
      semanticHint: `${semanticBlockLabel(row.semanticCandidateClass)}${candidateLabels.length ? ` · 候选标准字段：${candidateLabels.join(' / ')}` : ''}`,
    };
  }
  if (row.semanticBlock && row.semanticBlock !== 'remark_block') {
    return {
      groupType: 'semantic_block',
      groupKey: `block:${row.semanticBlock}:${suggestedField}`,
      groupName: `${semanticBlockLabel(row.semanticBlock)} · ${suggestedLabel}`,
      suggestedField,
      suggestedLabel,
      semanticHint: semanticBlockLabel(row.semanticBlock),
    };
  }
  return {
    groupType: 'field_alias',
    groupKey: `field:${row.field}:${clusterText(row.sourceFieldName || row.candidates[0]?.alias || row.label || row.field) || 'missing'}`,
    groupName: firstNonEmpty(row.sourceFieldName, row.label),
    suggestedField: row.field,
    suggestedLabel: row.label,
    semanticHint: '',
  };
}

function computeReviewScore(row, historyCount) {
  let score = 0;
  if (row.sourceFieldName) score += 28;
  if (row.sourceValue) score += 22;
  if (row.aliasHit) score += 18;
  if (historyCount >= 2) score += 15;
  if (row.semanticCandidateClass === 'party_address_candidate') score += 6;
  if (row.candidateStandardFields.length === 1) score += 8;
  if (row.semanticBlock && row.semanticBlock !== 'remark_block') score += 5;
  if (Number(row.confidence || 0) >= 0.9) score += 10;
  else if (Number(row.confidence || 0) >= 0.8) score += 7;
  else if (Number(row.confidence || 0) >= 0.65) score += 4;
  if (row.sourceKind === 'scan_ocr') score -= 10;
  if (!row.sourceFieldName) score -= 18;
  if (!row.sourceValue) score -= 15;
  return Math.max(0, Math.min(100, score));
}

function buildReviewWorkbench(documents, focusFields, focusLabels) {
  const docs = documents || [];
  const rows = [];

  docs.forEach((doc) => {
    const mapped = new Map((doc.standard_mappings || []).map((item) => [item.standard_field, item]));
    const manualRows = new Map((doc.manual_confirmation_rows || []).map((item) => [item.standard_field, item]));
    const candidateMap = new Map();
    (doc.alias_candidates || []).forEach((item) => {
      const field = String(item.standard_field || '');
      if (!field) return;
      if (!candidateMap.has(field)) candidateMap.set(field, []);
      candidateMap.get(field).push(item);
    });

    (focusFields || []).forEach((field) => {
      const mapping = mapped.get(field) || {};
      const manual = manualRows.get(field) || {};
      const candidates = candidateMap.get(field) || [];
      const sourceFieldName = firstNonEmpty(mapping.source_field_name, candidates[0]?.alias);
      const sourceValue = firstNonEmpty(manual.confirmed_value, mapping.source_value);
      const aliasHit = (doc.alias_hits || []).some((item) => item.standard_field === field && normalizeText(item.source_field_name) === normalizeText(sourceFieldName));
      const row = {
        key: `${field}:${doc.filename}`,
        doc,
        field,
        label: focusLabels?.[field] || field,
        sourceFieldName,
        sourceValue,
        candidates,
        promoteAlias: manual.promote_alias === true,
        confidence: Number(mapping.confidence || 0),
        uncertain: Boolean(mapping.uncertain || (doc.uncertain_fields || []).includes(field)),
        sourceKind: String(doc.raw_text_result?.metadata?.source_kind || ''),
        aliasHit,
        isMismatch: manual.match_status === 'mismatched',
        reviewNote: String(manual.review_note || ''),
        semanticBlock: String(mapping.semantic_block || ''),
        semanticCandidateClass: String(mapping.semantic_candidate_class || ''),
        candidateStandardFields: Array.isArray(mapping.candidate_standard_fields) ? mapping.candidate_standard_fields.filter(Boolean) : [],
      };
      rows.push(row);
    });
  });

  const historyCounter = rows.reduce((acc, row) => {
    const aliasKey = `${row.field}:${normalizeText(row.sourceFieldName)}`;
    if (normalizeText(row.sourceFieldName)) acc.set(aliasKey, (acc.get(aliasKey) || 0) + 1);
    return acc;
  }, new Map());

  const enrichedRows = rows.map((row) => {
    const historyCount = historyCounter.get(`${row.field}:${normalizeText(row.sourceFieldName)}`) || 0;
    const score = computeReviewScore(row, historyCount);
    const needsManual = score < 45 || !row.sourceFieldName || !row.sourceValue || row.uncertain;
    const semanticGroup = summarizeSemanticGroup(row, focusLabels);
    return {
      ...row,
      historyCount,
      score,
      needsManual,
      clusterKey: semanticGroup.groupKey,
      groupType: semanticGroup.groupType,
      semanticHint: semanticGroup.semanticHint,
      suggestedField: semanticGroup.suggestedField,
      suggestedLabel: semanticGroup.suggestedLabel,
      groupName: semanticGroup.groupName,
    };
  });

  const groupsByKey = new Map();
  enrichedRows.forEach((row) => {
    if (!groupsByKey.has(row.clusterKey)) groupsByKey.set(row.clusterKey, []);
    groupsByKey.get(row.clusterKey).push(row);
  });

  const groups = [...groupsByKey.entries()].map(([groupId, groupRows]) => {
    const names = [...new Set(groupRows.map((row) => row.sourceFieldName).filter(Boolean))];
    const examples = [...new Set(groupRows.map((row) => row.sourceValue).filter(Boolean))].slice(0, 3);
    const docsCount = new Set(groupRows.map((row) => row.doc.filename)).size;
    const approvableRows = groupRows.filter((row) => !row.needsManual);
    const exceptionRows = groupRows.filter((row) => row.needsManual);
    const confidence = Math.round(groupRows.reduce((sum, row) => sum + row.score, 0) / Math.max(1, groupRows.length));
    const conflict = names.length >= 3 || (approvableRows.length > 0 && exceptionRows.length > 0);
    let tier = 'manual';
    if (approvableRows.length === groupRows.length && confidence >= 72 && !conflict) tier = 'auto';
    else if (approvableRows.length > 0 && confidence >= 48) tier = 'batch';
    const firstRow = groupRows[0];
    const suggestedFieldCounts = groupRows.reduce((acc, row) => {
      const key = row.suggestedField || row.field;
      acc.set(key, (acc.get(key) || 0) + 1);
      return acc;
    }, new Map());
    const suggestedField = [...suggestedFieldCounts.entries()]
      .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))[0]?.[0] || firstRow.field;
    return {
      id: groupId,
      groupName: firstNonEmpty(firstRow.groupName, names[0], firstRow.label),
      field: firstRow.field,
      label: firstRow.label,
      suggestedField,
      suggestedLabel: focusLabels?.[suggestedField] || suggestedField,
      rows: groupRows,
      approvableRows,
      exceptionRows,
      totalCount: groupRows.length,
      docsCount,
      confidence,
      conflict,
      aliases: names,
      examples,
      tier,
      semanticHint: firstRow.semanticHint,
      candidateLabels: uniqueList(groupRows.flatMap((row) => (row.candidateStandardFields || []).map((field) => focusLabels?.[field] || field))),
    };
  }).sort((a, b) => {
    const order = { auto: 0, batch: 1, manual: 2 };
    return order[a.tier] - order[b.tier] || b.confidence - a.confidence || a.label.localeCompare(b.label);
  });

  return {
    rows: enrichedRows,
    groups,
    autoGroups: groups.filter((group) => group.tier === 'auto'),
    batchGroups: groups.filter((group) => group.tier === 'batch'),
    manualGroups: groups.filter((group) => group.tier === 'manual'),
  };
}

function summarizeReviewDecisions(rows) {
  const total = rows.length;
  const mismatched = rows.filter((row) => row.isMismatch).length;
  const matched = total - mismatched;
  const withNotes = rows.filter((row) => String(row.reviewNote || '').trim()).length;
  return {
    total,
    matched,
    mismatched,
    withNotes,
    accuracy: total ? formatRate(matched, total) : '-',
  };
}

function mergeByStandardField(items) {
  const merged = new Map();
  (items || []).forEach((item) => {
    const field = String(item?.standard_field || '').trim();
    if (!field) return;
    const current = merged.get(field) || {};
    merged.set(field, {
      ...current,
      ...item,
      standard_field: field,
      standard_label_cn: item?.standard_label_cn || current.standard_label_cn || field,
    });
  });
  return [...merged.values()];
}

function buildFeedbackDrafts(analysis) {
  const next = {};
  (analysis?.documents || []).forEach((doc) => {
    next[doc.filename] = {
      filename: doc.filename,
      doc_type_correct: true,
      corrected_doc_type: '',
      note: '',
      fields: Object.fromEntries((doc.field_understanding || []).map((field) => [field.standard_field, {
        correct: true,
        corrected_field: '',
        corrected_value: '',
      }])),
    };
  });
  return next;
}

class AppErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: String(error?.message || error || '页面渲染失败'),
    };
  }

  componentDidCatch(error, info) {
    console.error('App render failed', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="page-shell">
          <section className="hero-card">
            <h1>{TEXT.title}</h1>
            <div className="warn-box">页面恢复时出现异常：{this.state.message}</div>
            <div className="action-row top-gap-small">
              <button type="button" onClick={() => window.location.reload()}>重新加载页面</button>
            </div>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}

function AppContent() {
  const [config, setConfig] = useState(EMPTY_CONFIG);
  const [learningConfig, setLearningConfig] = useState(EMPTY_LEARNING_CONFIG);
  const [loading, setLoading] = useState(true);
  const [files, setFiles] = useState([]);
  const [statusMap, setStatusMap] = useState({});
  const [promptText, setPromptText] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('deepseek-chat');
  const [focusFields, setFocusFields] = useState(CORE_FIELDS);
  const [priorityFields, setPriorityFields] = useState([]);
  const [extractionMode, setExtractionMode] = useState('bundle');
  const [singleDocType, setSingleDocType] = useState('\u81ea\u52a8\u5224\u65ad');
  const [templates, setTemplates] = useState(DEFAULT_TEMPLATES);
  const [selectedTemplateId, setSelectedTemplateId] = useState('core_fields');
  const [templateEditorOpen, setTemplateEditorOpen] = useState(false);
  const [templateDraft, setTemplateDraft] = useState(null);
  const [resultData, setResultData] = useState(null);
  const [saveFeedback, setSaveFeedback] = useState(null);
  const [error, setError] = useState('');
  const [modalState, setModalState] = useState(null);
  const [promptModalOpen, setPromptModalOpen] = useState(false);
  const openPromptCenter = () => setPromptModalOpen(true);
  const [learningPrompts, setLearningPrompts] = useState(EMPTY_LEARNING_CONFIG.prompt_texts);
  const [learningPromptFlags, setLearningPromptFlags] = useState(EMPTY_LEARNING_CONFIG.prompt_flags);
  const [learningAnalysis, setLearningAnalysis] = useState(null);
  const [learningDrafts, setLearningDrafts] = useState({});
  const [learningStatus, setLearningStatus] = useState({ loading: false, message: '' });
  const [expandedReviewGroups, setExpandedReviewGroups] = useState({});
  const pollTimer = useRef(null);
  const allFieldKeys = useMemo(
    () => Object.keys(config.focus_labels || {}).sort((left, right) => {
      const leftLevel = Number(config.field_levels?.[left] || 2);
      const rightLevel = Number(config.field_levels?.[right] || 2);
      if (leftLevel !== rightLevel) return leftLevel - rightLevel;
      return String(config.focus_labels?.[left] || left).localeCompare(String(config.focus_labels?.[right] || right), 'zh-CN');
    }),
    [config.focus_labels, config.field_levels],
  );
  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedTemplateId) || templates[0] || null,
    [templates, selectedTemplateId],
  );
  const currentPreset = useMemo(() => selectedPresetId(focusFields, allFieldKeys), [focusFields, allFieldKeys]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const normalizedDefaults = mergeTemplatesWithDefaults([], allFieldKeys);

    const restorePageState = () => {
      setTemplates((prev) => (Array.isArray(prev) && prev.length ? prev : normalizedDefaults));
      setSelectedTemplateId((prev) => {
        if (prev && templates.some((template) => template.id === prev)) return prev;
        return normalizedDefaults[0]?.id || 'core_fields';
      });
    };

    window.addEventListener('pageshow', restorePageState);
    return () => {
      window.removeEventListener('pageshow', restorePageState);
    };
  }, [allFieldKeys, templates]);

  useEffect(() => {
    let active = true;
    fetch('/api/v1/document-foundation/ui-config')
      .then((resp) => resp.json().then((data) => ({ ok: resp.ok, data })))
      .then(({ ok, data }) => {
        if (!active) return;
        if (!ok) throw new Error(data.detail || TEXT.requestFail);
        const nextConfig = { ...EMPTY_CONFIG, ...data, focus_fields: data.focus_fields?.length ? data.focus_fields : EMPTY_CONFIG.focus_fields };
        const localRuleConfig = typeof window !== 'undefined' ? window.localStorage.getItem('audit-rule-config') : null;
        let localActiveFields = [];
        let localPriorityFields = [];
        if (localRuleConfig) {
          try {
            const parsed = JSON.parse(localRuleConfig);
            localActiveFields = parsed.field_preferences?.active_fields || [];
            localPriorityFields = parsed.field_preferences?.priority_fields || [];
          } catch (storageError) {
            console.warn('Failed to parse local rule config', storageError);
          }
        }
        const availableFieldKeys = Object.keys(nextConfig.focus_labels || {});
        setConfig(nextConfig);
        setPromptText(nextConfig.prompt_text || '');
        setModel(nextConfig.llm_model || 'deepseek-chat');
        setFocusFields((localActiveFields.length ? localActiveFields : nextConfig.focus_fields).filter((item) => availableFieldKeys.includes(item)));
        setPriorityFields(localPriorityFields.filter((item) => availableFieldKeys.includes(item)));
      })
      .catch((err) => {
        if (active) setError(String(err.message || err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!allFieldKeys.length || typeof window === 'undefined') return;
    try {
      const raw = window.localStorage.getItem('audit-field-templates');
      if (!raw) {
        setTemplates(mergeTemplatesWithDefaults([], allFieldKeys));
        return;
      }
      const parsed = JSON.parse(raw);
      const nextTemplates = mergeTemplatesWithDefaults(parsed, allFieldKeys);
      setTemplates(nextTemplates.length ? nextTemplates : mergeTemplatesWithDefaults([], allFieldKeys));
    } catch (error) {
      console.warn('Failed to load field templates', error);
      setTemplates(mergeTemplatesWithDefaults([], allFieldKeys));
    }
  }, [allFieldKeys]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('audit-field-templates', JSON.stringify(templates));
  }, [templates]);

  useEffect(() => {
    if (!templates.length) return;
    if (!templates.some((template) => template.id === selectedTemplateId)) {
      setSelectedTemplateId(templates[0].id);
    }
  }, [templates, selectedTemplateId]);

  useEffect(() => {
    let active = true;
    fetch('/api/v1/prompt-learning/ui-config')
      .then((resp) => resp.json().then((data) => ({ ok: resp.ok, data })))
      .then(({ ok, data }) => {
        if (!active) return;
        if (!ok) throw new Error(data.detail || TEXT.requestFail);
        const localRuleConfig = typeof window !== 'undefined' ? window.localStorage.getItem('audit-rule-config') : null;
        let localPromptTexts = {};
        let localPromptFlags = {};
        if (localRuleConfig) {
          try {
            const parsed = JSON.parse(localRuleConfig);
            localPromptTexts = parsed.prompt_texts || {};
            localPromptFlags = parsed.prompt_flags || {};
          } catch (storageError) {
            console.warn('Failed to parse local rule config', storageError);
          }
        }
        setLearningConfig(data);
        setLearningPrompts({ ...EMPTY_LEARNING_CONFIG.prompt_texts, ...(data.prompt_texts || {}), ...localPromptTexts });
        setLearningPromptFlags({ ...EMPTY_LEARNING_CONFIG.prompt_flags, ...(data.prompt_flags || {}), ...localPromptFlags });
      })
      .catch((err) => {
        if (active) setError(String(err.message || err));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!resultData?.documents?.length) {
      setLearningAnalysis(null);
      setLearningDrafts({});
      setLearningStatus({ loading: false, message: '' });
      return;
    }
    if (!promptModalOpen) {
      setLearningStatus({ loading: false, message: '' });
      return;
    }
    let cancelled = false;
    setLearningStatus({ loading: true, message: '\u6b63\u5728\u751f\u6210\u63d0\u793a\u8bcd\u5b66\u4e60\u8865\u5145\u5efa\u8bae...' });
    fetch('/api/v1/prompt-learning/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ documents: resultData.documents, prompt_context: learningPrompts, prompt_flags: learningPromptFlags }),
    })
      .then((resp) => resp.json().then((data) => ({ ok: resp.ok, data })))
      .then(({ ok, data }) => {
        if (cancelled) return;
        if (!ok) throw new Error(data.detail || TEXT.requestFail);
        setLearningAnalysis(data);
        setLearningDrafts(buildFeedbackDrafts(data));
        setLearningStatus({ loading: false, message: '' });
      })
      .catch((err) => {
        if (!cancelled) setLearningStatus({ loading: false, message: `\u5b66\u4e60\u5206\u6790\u5931\u8d25\uff1a${String(err.message || err)}` });
      });
    return () => {
      cancelled = true;
    };
  }, [resultData, learningPrompts, learningPromptFlags, promptModalOpen]);

  useEffect(() => {
    if (!selectedTemplate || !allFieldKeys.length) return;
    const nextFields = selectedTemplate.fields === 'ALL' ? allFieldKeys : selectedTemplate.fields;
    setFocusFields(nextFields);
  }, [selectedTemplate, allFieldKeys]);

  function updateFileStatuses(nextStatuses) {
    setStatusMap((prev) => ({ ...prev, ...nextStatuses }));
  }

  function handleFileChange(event) {
    const nextFiles = Array.from(event.target.files || []);
    setFiles(nextFiles);
    setSaveFeedback(null);
    if (!nextFiles.length) {
      setStatusMap({});
      return;
    }
    setStatusMap(Object.fromEntries(nextFiles.map((file) => [file.name, { label: TEXT.queued, className: 'queued', detail: '' }])));
  }

  function toggleField(field) {
    setFocusFields((prev) => (prev.includes(field) ? prev.filter((item) => item !== field) : [...prev, field]));
  }

  function applyPreset(preset) {
    setFocusFields(preset.fields === 'ALL' ? allFieldKeys : preset.fields);
  }

  function openTemplateEditor(mode = 'edit') {
    if (mode === 'create') {
      setTemplateDraft({
        id: `custom_${Date.now()}`,
        name: '新模板',
        fields: [...focusFields],
      });
    } else if (selectedTemplate) {
      setTemplateDraft({
        id: selectedTemplate.id,
        name: selectedTemplate.name,
        fields: selectedTemplate.fields === 'ALL' ? 'ALL' : [...selectedTemplate.fields],
      });
    }
    setTemplateEditorOpen(true);
  }

  function toggleTemplateDraftField(field) {
    setTemplateDraft((prev) => {
      if (!prev || prev.fields === 'ALL') return prev;
      const exists = prev.fields.includes(field);
      return {
        ...prev,
        fields: exists ? prev.fields.filter((item) => item !== field) : [...prev.fields, field],
      };
    });
  }

  function updateTemplateDraft(key, value) {
    setTemplateDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  function saveTemplateDraft() {
    if (!templateDraft) return;
    const nextTemplate = {
      id: templateDraft.id,
      name: templateDraft.name.trim() || '未命名模板',
      fields: templateDraft.fields === 'ALL' ? 'ALL' : normalizeTemplateFields(templateDraft.fields, allFieldKeys),
    };
    setTemplates((prev) => {
      const exists = prev.some((item) => item.id === nextTemplate.id);
      return exists
        ? prev.map((item) => (item.id === nextTemplate.id ? nextTemplate : item))
        : [...prev, nextTemplate];
    });
    setSelectedTemplateId(nextTemplate.id);
    setTemplateEditorOpen(false);
  }

  function deleteSelectedTemplate() {
    if (!selectedTemplate) return;
    setTemplates((prev) => {
      const next = prev.filter((item) => item.id !== selectedTemplate.id);
      return next.length ? next : prev;
    });
    setTemplateEditorOpen(false);
  }

  function buildStatusMap(fileStatuses = []) {
    return Object.fromEntries((fileStatuses || []).map((item) => [item.filename, {
      label: item.status === 'completed' ? TEXT.done : item.status === 'done' ? TEXT.done : item.status === 'failed' ? TEXT.failed : item.status === 'processing' ? TEXT.processing : TEXT.queued,
      className: item.status === 'completed' ? 'done' : item.status === 'done' ? 'done' : item.status === 'failed' ? 'failed' : item.status === 'processing' ? 'processing' : 'queued',
      detail: item.detail || '',
    }]));
  }

  function pollValidation(jobId) {
    fetch(`/api/v1/document-foundation/validate-status/${jobId}`)
      .then((resp) => resp.json().then((data) => ({ ok: resp.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) throw new Error(data.detail || TEXT.requestFail);
        if (data.file_statuses) updateFileStatuses(buildStatusMap(data.file_statuses));
        const nextView = data.result || data.partial_response;
        if (nextView) setResultData(nextView);
        if (data.status === 'completed') return;
        if (data.status === 'failed') throw new Error(data.error || TEXT.requestFail);
        pollTimer.current = window.setTimeout(() => pollValidation(jobId), 1200);
      })
      .catch((err) => setError(`${TEXT.processFail}${String(err.message || err)}`));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError('');
    setSaveFeedback(null);
    if (!files.length) {
      setError(TEXT.noFile);
      return;
    }
    const fd = new FormData();
    files.forEach((file) => fd.append('files', file));
    fd.append('prompt_text', promptText);
    fd.append('prompt_file_name', config.prompt_file_name);
    fd.append('llm_api_key', apiKey);
    fd.append('llm_base_url', config.llm_base_url);
    fd.append('llm_model', model);
    fd.append('ocr_model', config.ocr_model);
    fd.append('llm_timeout', String(config.llm_timeout));
    fd.append('use_alias_active', config.use_alias_active ? 'true' : 'false');
    fd.append('use_rule_active', config.use_rule_active ? 'true' : 'false');
    fd.append('enable_ocr', config.enable_ocr ? 'true' : 'false');
    fd.append('force_ocr', config.force_ocr ? 'true' : 'false');
    fd.append('focus_fields', focusFields.join(','));
    fd.append('priority_fields', priorityFields.join(','));
    fd.append('extraction_mode', extractionMode);
    fd.append('single_doc_type', singleDocType);
    fd.append('include_visual_assets', 'true');
    setResultData({ documents: [], loading_message: TEXT.extracting });
    updateFileStatuses(Object.fromEntries(files.map((file) => [file.name, { label: TEXT.queued, className: 'queued', detail: '' }] )));
    try {
      const resp = await fetch('/api/v1/document-foundation/validate-async', { method: 'POST', body: fd });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || TEXT.requestFail);
      pollValidation(data.job_id);
    } catch (err) {
      setError(`${TEXT.processFail}${String(err.message || err)}`);
    }
  }

  function updateAliasName(docFilename, field, nextAlias) {
    setResultData((prev) => {
      if (!prev) return prev;
      const docs = cloneDocuments(prev.documents || []);
      const doc = docs.find((item) => item.filename === docFilename);
      if (!doc) return prev;
      if (!Array.isArray(doc.standard_mappings)) doc.standard_mappings = [];
      let mapping = doc.standard_mappings.find((item) => item.standard_field === field);
      if (!mapping) {
        mapping = {
          standard_field: field,
          standard_label_cn: config.focus_labels?.[field] || field,
          source_field_name: '',
          source_value: '',
          confidence: 0,
          uncertain: true,
          reason: 'manual alias input',
        };
        doc.standard_mappings.push(mapping);
      }
      mapping.source_field_name = nextAlias;
      if (!Array.isArray(doc.manual_confirmation_rows)) doc.manual_confirmation_rows = [];
      let manual = doc.manual_confirmation_rows.find((item) => item.standard_field === field);
      if (!manual) {
        manual = {
          standard_field: field,
          standard_label_cn: config.focus_labels?.[field] || field,
          ai_value: mapping.source_value || '',
          confirmed_value: '',
          promote_alias: false,
        };
        doc.manual_confirmation_rows.push(manual);
      }
      return { ...prev, documents: docs };
    });
  }


  function updatePromoteAlias(docFilename, field, checked) {
    setResultData((prev) => {
      if (!prev) return prev;
      const docs = cloneDocuments(prev.documents || []);
      const doc = docs.find((item) => item.filename === docFilename);
      if (!doc) return prev;
      if (!Array.isArray(doc.manual_confirmation_rows)) doc.manual_confirmation_rows = [];
      let manual = doc.manual_confirmation_rows.find((item) => item.standard_field === field);
      if (!manual) {
        manual = {
          standard_field: field,
          standard_label_cn: config.focus_labels?.[field] || field,
          ai_value: '',
          confirmed_value: '',
          promote_alias: checked,
        };
        doc.manual_confirmation_rows.push(manual);
      }
      manual.promote_alias = checked;
      return { ...prev, documents: docs };
    });
  }

  function applyGroupDecision(group, checked = true) {
    setResultData((prev) => {
      if (!prev) return prev;
      const docs = cloneDocuments(prev.documents || []);
      group.approvableRows.forEach((row) => {
        const doc = docs.find((item) => item.filename === row.doc.filename);
        if (!doc) return;
        const targetField = group.suggestedField || row.suggestedField || row.field;
        const targetLabel = config.focus_labels?.[targetField] || targetField;
        if (!Array.isArray(doc.standard_mappings)) doc.standard_mappings = [];
        let mapping = doc.standard_mappings.find((item) => item.standard_field === targetField);
        if (!mapping && targetField !== row.field) {
          mapping = doc.standard_mappings.find((item) => item.standard_field === row.field);
        }
        if (!mapping) {
          mapping = {
            standard_field: targetField,
            standard_label_cn: targetLabel,
            source_field_name: '',
            source_value: row.sourceValue || '',
            confidence: row.confidence || 0,
            uncertain: false,
            reason: 'group confirmation',
          };
          doc.standard_mappings.push(mapping);
        }
        mapping.standard_field = targetField;
        mapping.standard_label_cn = targetLabel;
        mapping.source_field_name = firstNonEmpty(mapping.source_field_name, row.sourceFieldName, row.candidates[0]?.alias);
        mapping.source_value = row.sourceValue || mapping.source_value || '';
        mapping.uncertain = false;
        if (!Array.isArray(doc.manual_confirmation_rows)) doc.manual_confirmation_rows = [];
        let manual = doc.manual_confirmation_rows.find((item) => item.standard_field === targetField);
        if (!manual && targetField !== row.field) {
          manual = doc.manual_confirmation_rows.find((item) => item.standard_field === row.field);
        }
        if (!manual) {
          manual = {
            standard_field: targetField,
            standard_label_cn: targetLabel,
            ai_value: row.sourceValue || '',
            confirmed_value: row.sourceValue || '',
            promote_alias: checked,
          };
          doc.manual_confirmation_rows.push(manual);
        }
        manual.standard_field = targetField;
        manual.standard_label_cn = targetLabel;
        manual.promote_alias = checked;
        manual.ai_value = row.sourceValue || manual.ai_value || '';
        manual.confirmed_value = row.sourceValue || manual.confirmed_value || '';
        doc.standard_mappings = mergeByStandardField(doc.standard_mappings);
        doc.manual_confirmation_rows = mergeByStandardField(doc.manual_confirmation_rows);
      });
      return { ...prev, documents: docs };
    });
  }

  function toggleReviewGroup(groupId) {
    setExpandedReviewGroups((prev) => ({ ...prev, [groupId]: !prev[groupId] }));
  }

  function updateLearningPrompt(key, value) {
    setLearningPrompts((prev) => ({ ...prev, [key]: value }));
  }

  function updateLearningPromptFlag(key, value) {
    setLearningPromptFlags((prev) => ({ ...prev, [key]: value }));
  }

  function updateLearningDraft(filename, key, value) {
    setLearningDrafts((prev) => ({
      ...prev,
      [filename]: {
        ...(prev[filename] || {}),
        [key]: value,
      },
    }));
  }

  function updateFieldDraft(filename, field, key, value) {
    setLearningDrafts((prev) => ({
      ...prev,
      [filename]: {
        ...(prev[filename] || {}),
        fields: {
          ...((prev[filename] || {}).fields || {}),
          [field]: {
            ...(((prev[filename] || {}).fields || {})[field] || {}),
            [key]: value,
          },
        },
      },
    }));
  }

  async function handleLearningSave() {
    if (!learningAnalysis?.documents?.length) return;
    setLearningStatus({ loading: true, message: '\u6b63\u5728\u4fdd\u5b58\u672c\u6b21\u5b66\u4e60\u8bb0\u5f55...' });
    try {
      const resp = await fetch('/api/v1/prompt-learning/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          run_key: resultData?.experiment_record?.run_dir || '',
          prompt_name: config.prompt_file_name,
          analysis_result: learningAnalysis,
          feedback_items: Object.values(learningDrafts),
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || TEXT.requestFail);
      setLearningConfig((prev) => ({ ...prev, history: data.history }));
      setLearningStatus({ loading: false, message: `\u5df2\u4fdd\u5b58 ${data.saved.total_documents} \u4efd\u5b66\u4e60\u8bb0\u5f55\uff0c\u5e76\u65b0\u589e ${data.saved.created_suggestions} \u6761\u8865\u5145\u5efa\u8bae\u3002` });
    } catch (err) {
      setLearningStatus({ loading: false, message: `\u4fdd\u5b58\u5b66\u4e60\u8bb0\u5f55\u5931\u8d25\uff1a${String(err.message || err)}` });
    }
  }

  function updateReviewMismatch(docFilename, field, checked) {
    setResultData((prev) => {
      if (!prev) return prev;
      const docs = cloneDocuments(prev.documents || []);
      const doc = docs.find((item) => item.filename === docFilename);
      if (!doc) return prev;
      if (!Array.isArray(doc.manual_confirmation_rows)) doc.manual_confirmation_rows = [];
      let manual = doc.manual_confirmation_rows.find((item) => item.standard_field === field);
      if (!manual) {
        manual = {
          standard_field: field,
          standard_label_cn: config.focus_labels?.[field] || field,
          ai_value: '',
          confirmed_value: '',
          promote_alias: false,
        };
        doc.manual_confirmation_rows.push(manual);
      }
      manual.match_status = checked ? 'mismatched' : 'matched';
      return { ...prev, documents: docs };
    });
  }

  function updateReviewNote(docFilename, field, reviewNote) {
    setResultData((prev) => {
      if (!prev) return prev;
      const docs = cloneDocuments(prev.documents || []);
      const doc = docs.find((item) => item.filename === docFilename);
      if (!doc) return prev;
      if (!Array.isArray(doc.manual_confirmation_rows)) doc.manual_confirmation_rows = [];
      let manual = doc.manual_confirmation_rows.find((item) => item.standard_field === field);
      if (!manual) {
        manual = {
          standard_field: field,
          standard_label_cn: config.focus_labels?.[field] || field,
          ai_value: '',
          confirmed_value: '',
          promote_alias: false,
          match_status: 'matched',
        };
        doc.manual_confirmation_rows.push(manual);
      }
      manual.review_note = reviewNote;
      return { ...prev, documents: docs };
    });
  }

  async function handleSave() {
    if (!resultData?.documents?.length) return;
    const docs = cloneDocuments(resultData.documents).map((doc) => {
      const mergedManualRows = [...(doc.manual_confirmation_rows || [])];
      const aliasRows = mergedManualRows.filter((manual) => manual.promote_alias === true);
      const aliasFields = new Set(aliasRows.map((manual) => manual.standard_field));
      return {
        ...doc,
        manual_confirmation_rows: mergeByStandardField(aliasRows).map((manual) => ({
          ...manual,
          ai_value: manual.ai_value || '',
          confirmed_value: manual.confirmed_value || '',
          promote_alias: true,
        })),
        standard_mappings: mergeByStandardField((doc.standard_mappings || []).map((mapping) => {
          if (!aliasFields.has(mapping.standard_field)) {
            return { ...mapping };
          }
          const nextMapping = { ...mapping };
          delete nextMapping.source_value;
          return nextMapping;
        })),
      };
    });
    const missingAliasRows = [];
    docs.forEach((doc) => {
      (doc.manual_confirmation_rows || []).forEach((manual) => {
        const mapping = (doc.standard_mappings || []).find((item) => item.standard_field === manual.standard_field) || {};
        const aliasName = String(mapping.source_field_name || '').trim();
        if (!aliasName) {
          missingAliasRows.push(`${doc.filename} / ${config.focus_labels?.[manual.standard_field] || manual.standard_field}`);
        }
      });
    });
    if (missingAliasRows.length) {
      setSaveFeedback({
        type: 'error',
        message: `\u4ee5\u4e0b\u5b57\u6bb5\u5df2\u52fe\u9009\u5199\u5165 alias \u5e93\uff0c\u4f46\u8fd8\u6ca1\u6709\u586b\u5199\u5408\u540c\u5b57\u6bb5\u540d\uff1a${missingAliasRows.join('\uff1b')}`, 
      });
      return;
    }
    setSaveFeedback({ type: 'info', message: '\u6b63\u5728\u628a\u4f60\u786e\u8ba4\u7684\u5b57\u6bb5\u540d\u5199\u5165 alias \u5e93\uff0c\u4e0d\u4fdd\u5b58\u672c\u6b21\u8bc6\u522b\u51fa\u7684\u5b57\u6bb5\u503c\uff0c\u8bf7\u7a0d\u7b49...' });
    try {
      const resp = await fetch('/api/v1/document-foundation/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ documents: docs, experiment_record: resultData.experiment_record || {} }),
      });
      const payload = await resp.json();
      if (!resp.ok) throw new Error(payload.detail || TEXT.requestFail);
      const record = payload.evaluation_record || {};
      setSaveFeedback({
        type: record.failed_alias_count ? 'error' : 'success',
        message: record.failed_alias_count ? `\u6709 ${record.failed_alias_count} \u6761 alias \u5199\u5165\u5931\u8d25` : '\u5b57\u6bb5 alias \u5df2\u5199\u5165\u6210\u529f\uff0c\u4e0d\u4f1a\u4fdd\u5b58\u672c\u6b21\u8bc6\u522b\u51fa\u7684\u5b57\u6bb5\u503c\u3002', 
        stats: [
          `\u65b0\u589e alias ${record.promoted_aliases || 0}`,
          `\u91cd\u590d alias ${record.duplicate_alias_count || 0}`,
          `\u5931\u8d25\u5199\u5165 ${record.failed_alias_count || 0}`,
        ],
        duplicates: record.duplicate_aliases || [],
      });
    } catch (err) {
      setSaveFeedback({ type: 'error', message: `${TEXT.saveFail}${String(err.message || err)}` });
    }
  }

  const reviewWorkbench = useMemo(
    () => buildReviewWorkbench(resultData?.documents || [], focusFields, config.focus_labels),
    [resultData, focusFields, config.focus_labels],
  );

  const hasReviewRows = reviewWorkbench.rows.length > 0;

  const recognitionSummary = useMemo(() => {
    const totalPairs = reviewWorkbench.rows.length;
    const fieldHits = reviewWorkbench.rows.filter((row) => normalizeText(row.sourceFieldName)).length;
    const valueHits = reviewWorkbench.rows.filter((row) => String(row.sourceValue || '').trim()).length;
    return {
      totalPairs,
      fieldHits,
      valueHits,
      fieldRate: formatRate(fieldHits, totalPairs),
      valueRate: formatRate(valueHits, totalPairs),
    };
  }, [reviewWorkbench]);
  const reviewDecisionSummary = useMemo(
    () => summarizeReviewDecisions(reviewWorkbench.rows),
    [reviewWorkbench.rows],
  );

  function handleExportResults() {
    if (!hasReviewRows) return;
    const exportRows = [
      ['结果说明', '本次识别与人工复核结果'],
      ['整体字段识别率', `${recognitionSummary.fieldRate} (${recognitionSummary.fieldHits}/${recognitionSummary.totalPairs})`],
      ['字段值识别率', `${recognitionSummary.valueRate} (${recognitionSummary.valueHits}/${recognitionSummary.totalPairs})`],
      ['人工复核准确率', reviewDecisionSummary.accuracy],
      ['不一致数量', String(reviewDecisionSummary.mismatched)],
      [],
      ['单据', '字段', '识别链路', '识别字段名', '识别值', '是否不一致', '备注'],
    ];
    reviewWorkbench.rows.forEach((row) => {
      exportRows.push([
        row.doc.filename,
        row.label,
        extractionMarker(row.doc),
        row.sourceFieldName || '',
        row.sourceValue || '',
        row.isMismatch ? '是' : '否',
        row.reviewNote || '',
      ]);
    });
    const stamp = new Date().toISOString().slice(0, 10);
    downloadTsv(`识别结果导出_${stamp}.xls`, exportRows);
  }

  if (loading) {
    return <main className="page-shell"><section className="hero-card"><h1>{TEXT.title}</h1>
            <p>{'\u4e0a\u4f20\u6587\u4ef6\u540e\uff0c\u7cfb\u7edf\u4f1a\u5148\u81ea\u52a8\u63d0\u53d6\u5173\u952e\u5b57\u6bb5\u3002\u4f60\u53ea\u9700\u8981\u5feb\u901f\u6838\u5bf9\u6807\u8bb0\u201c\u5efa\u8bae\u786e\u8ba4\u201d\u7684\u7ed3\u679c\u5373\u53ef\u3002'}</p></section></main>;
  }

  return (
    <main className="page-shell">
      <section className="hero-card">
        <header className="hero-head">
          <div>
            <h1>{TEXT.title}</h1>
            <p>{'\u4e0a\u4f20\u6587\u4ef6\u540e\uff0c\u7cfb\u7edf\u4f1a\u5148\u81ea\u52a8\u63d0\u53d6\u5173\u952e\u5b57\u6bb5\u3002\u4f60\u53ea\u9700\u8981\u5feb\u901f\u6838\u5bf9\u6807\u8bb0\u201c\u5efa\u8bae\u786e\u8ba4\u201d\u7684\u7ed3\u679c\u5373\u53ef\u3002'}</p>
          </div>
        </header>

        <form className="layout-stack" onSubmit={handleSubmit}>
          <div className="panel-grid">
            <section className="panel-card">
              <label htmlFor="files">{'\u4e0a\u4f20\u5355\u636e\uff08\u652f\u6301\u5355\u4efd/\u6279\u91cf PDF\uff09'}</label>
              <input id="files" type="file" accept=".pdf,application/pdf" multiple onChange={handleFileChange} />
              <div className="file-box">
                {!files.length ? (
                  <div className="file-empty">{TEXT.noFilesSelected}</div>
                ) : (
                  files.map((file) => {
                    const status = statusMap[file.name] || { label: TEXT.queued, className: 'queued', detail: '' };
                    return (
                      <div className="file-row" key={file.name}>
                        <div>
                          <div className="file-name">{file.name}</div>
                          <div className="file-meta">{bytesToSize(file.size)}</div>
                          {status.detail ? <div className="file-meta">{status.detail}</div> : null}
                        </div>
                        <span className={`file-state ${status.className}`}>{status.label}</span>
                      </div>
                    );
                  })
                )}
              </div>
            </section>

            <section className="panel-card">
              <h3>{'\u8fd0\u884c\u8bbe\u7f6e'}</h3>
              <div className="simple-settings">
                <div>
                  <label htmlFor="llm_api_key">DeepSeek API Key</label>
                  <input id="llm_api_key" type="text" value={apiKey} placeholder={'sk-... \u8f93\u5165\u4f60\u7684 API Key'} onChange={(event) => setApiKey(event.target.value)} />
                </div>
                <div>
                  <label htmlFor="llm_model">{'\u6a21\u578b'}</label>
                  <select id="llm_model" value={model} onChange={(event) => setModel(event.target.value)}>
                    {(config.model_options || []).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                </div>
              </div>
            </section>
          </div>

          <section className="panel-card">
            <h3>{'\u63d0\u53d6\u65b9\u5f0f\u8bbe\u7f6e'}</h3>
            <div className="simple-settings">
              <div>
                <div className="section-head">
                  <div>
                    <label>{'\u5b57\u6bb5\u6a21\u677f'}</label>
                  </div>
                  <div className="template-actions">
                    <button type="button" className="secondary-btn" onClick={() => openTemplateEditor('edit')} disabled={!selectedTemplate}>编辑模板</button>
                    <button type="button" className="secondary-btn" onClick={() => openTemplateEditor('create')}>新建模板</button>
                  </div>
                </div>
                <div className="template-list template-list-compact">
                  {templates.map((template) => {
                    const fieldCount = template.fields === 'ALL' ? allFieldKeys.length : template.fields.length;
                    const levelCounts = countTemplateLevels(template.fields, allFieldKeys, config.field_levels);
                    return (
                      <button
                        key={template.id}
                        type="button"
                        className={`template-item ${selectedTemplateId === template.id ? 'active' : ''}`}
                        onClick={() => setSelectedTemplateId(template.id)}
                      >
                        <div className="template-item-main">
                          <strong>{template.name}</strong>
                          <span>{template.fields === 'ALL' ? '可自定义选择一级/二级字段' : `一级 ${levelCounts.level1} 个 / 二级 ${levelCounts.level2} 个`}</span>
                        </div>
                        <div className="template-item-meta">
                          <span>{`${fieldCount} 个字段`}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            <div className="field-setting-note top-gap-small">
              {selectedTemplate ? `当前模板：${selectedTemplate.name}，共 ${focusFields.length} 个字段（一级 ${countTemplateLevels(selectedTemplate.fields, allFieldKeys, config.field_levels).level1} / 二级 ${countTemplateLevels(selectedTemplate.fields, allFieldKeys, config.field_levels).level2}）。` : `当前共 ${focusFields.length} 个字段。`}
            </div>
          </section>

          <div className="action-row">
            <button type="submit">{TEXT.start}</button>
          </div>
        </form>

        {error ? <div className="warn-box">{error}</div> : null}
        {resultData?.loading_message ? <div className="panel-card result-hint">{resultData.loading_message}</div> : null}

{hasReviewRows ? (
        <section className="panel-card compact-review-panel top-gap">
          <div className="section-head">
            <div>
              <h3>标准字段确认</h3>
              <p>默认按一致计入准确率，只在发现问题时勾选“不一致”并补充备注。</p>
            </div>
            <div className="section-actions">
              <button type="button" className="secondary-btn" onClick={handleExportResults}>导出结果</button>
            </div>
          </div>

          <div className="summary-chip-row top-gap-small">
            <div className="summary-chip-card">
              <span className="summary-label">验证总数</span>
              <strong>{reviewWorkbench.rows.length}</strong>
              <span className="doc-meta">{`字段名取到 ${recognitionSummary.fieldRate} / 字段值取到 ${recognitionSummary.valueRate}`}</span>
            </div>
            <div className="summary-chip-card">
              <span className="summary-label">已取到值</span>
              <strong>{recognitionSummary.valueHits}</strong>
              <span className="doc-meta">{`未取到值 ${Math.max(0, reviewWorkbench.rows.length - recognitionSummary.valueHits)}`}</span>
            </div>
            <div className="summary-chip-card">
              <span className="summary-label">当前准确度</span>
              <strong>{reviewDecisionSummary.accuracy}</strong>
              <span className="doc-meta">{`一致 ${reviewDecisionSummary.matched} / 不一致 ${reviewDecisionSummary.mismatched}`}</span>
            </div>
            <div className="summary-chip-card">
              <span className="summary-label">已写备注</span>
              <strong>{reviewDecisionSummary.withNotes}</strong>
              <span className="doc-meta">勾选不一致后可补充原因</span>
            </div>
          </div>

          <div className="history-list top-gap">
            {reviewWorkbench.rows.map((row) => {
              const hasField = Boolean(normalizeText(row.sourceFieldName));
              const hasValue = Boolean(String(row.sourceValue || '').trim());
              return (
                <article className="history-item review-manual-card" key={row.key}>
                  <div className="review-manual-head">
                    <div>
                      <div className="doc-name">{row.doc.filename}</div>
                      <div className="doc-meta">{row.label}</div>
                    </div>
                    <div className="candidate-wrap">
                      <span className="candidate-tag ocr-source-tag">{extractionMarker(row.doc)}</span>
                      <span className={`candidate-tag ${hasField ? '' : 'candidate-tag-muted'}`}>{hasField ? '已取到字段名' : '未取到字段名'}</span>
                      <span className={`candidate-tag ${hasValue ? '' : 'candidate-tag-muted'}`}>{hasValue ? '已取到值' : '未取到值'}</span>
                      <button
                        type="button"
                        className="secondary-btn"
                        onClick={() => setModalState({ doc: row.doc, field: row.field, extraTerms: [] })}
                      >
                        查看
                      </button>
                    </div>
                  </div>
                  <div className="review-manual-grid">
                    <div>
                      <span>单据字段名</span>
                      <div className="result-value">{row.sourceFieldName || '-'}</div>
                    </div>
                    <div>
                      <div className="result-value">{row.label}</div>
                    </div>
                    <div>
                      <span className="summary-label">提取值</span>
                      <ExpandableValue value={row.sourceValue} />
                    </div>
                    <div className="review-cell review-cell-note">
                      <span className="summary-label">复核</span>
                      <label className="review-checkbox-row">
                        <input type="checkbox" checked={row.isMismatch} onChange={(event) => updateReviewMismatch(row.doc.filename, row.field, event.target.checked)} />
                        <span>标记为不准确</span>
                      </label>
                      <textarea
                        className="review-note-input"
                        value={row.reviewNote}
                        placeholder="有问题时补充原因；不填也会按当前勾选状态计入准确率。"
                        onChange={(event) => updateReviewNote(row.doc.filename, row.field, event.target.value)}
                      />
                    </div>
                  </div>
                </article>
              );
            })}
          </div>

          <div className="action-row top-gap">
            <button type="button" onClick={handleExportResults}>导出验证结果</button>
          </div>
        </section>
        ) : null}
      </section>

      {templateEditorOpen && templateDraft ? (
        <TemplateEditorModal
          template={templateDraft}
          allFieldKeys={allFieldKeys}
          focusLabels={config.focus_labels}
          fieldLevels={config.field_levels}
          isEditingExisting={templates.some((item) => item.id === templateDraft.id)}
          onClose={() => setTemplateEditorOpen(false)}
          onChange={updateTemplateDraft}
          onToggleField={toggleTemplateDraftField}
          onClearFields={() => updateTemplateDraft('fields', [])}
          onDelete={deleteSelectedTemplate}
          onSave={saveTemplateDraft}
        />
      ) : null}
      {modalState ? <LocatorModal doc={modalState.doc} field={modalState.field} focusLabels={config.focus_labels} extraTerms={modalState.extraTerms} onClose={() => setModalState(null)} /> : null}
    </main>
  );
}

function TemplateEditorModal({ template, allFieldKeys, focusLabels, fieldLevels, isEditingExisting, onClose, onChange, onToggleField, onClearFields, onDelete, onSave }) {
  const usingAllFields = template.fields === 'ALL';

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card template-editor-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h3>模板维护</h3>
            <p>这里保留给你维护字段模板，主页面还是只做快速验证。</p>
          </div>
          <div className="template-actions">
            {isEditingExisting ? <button type="button" className="secondary-btn" onClick={onDelete}>删除模板</button> : null}
            <button type="button" className="secondary-btn" onClick={onClose}>取消</button>
            <button type="button" onClick={onSave}>保存模板</button>
          </div>
        </div>

        <div className="simple-settings">
          <div>
            <label htmlFor="template_name">模板名称</label>
            <input id="template_name" type="text" value={template.name} onChange={(event) => onChange('name', event.target.value)} />
          </div>
          <div>
            <label className="review-checkbox-row">
              <input type="checkbox" checked={usingAllFields} onChange={(event) => onChange('fields', event.target.checked ? 'ALL' : [])} />
              <span>使用全部字段</span>
            </label>
          </div>
        </div>

        {!usingAllFields ? (
          <div className="template-field-list top-gap">
            <div className="template-actions">
              <button type="button" className="secondary-btn" onClick={onClearFields}>取消全选</button>
            </div>
            {allFieldKeys.map((field) => (
              <label key={field} className="template-field-item">
                <input type="checkbox" checked={template.fields.includes(field)} onChange={() => onToggleField(field)} />
                <span>{`${Number(fieldLevels?.[field] || 2) === 1 ? '一级' : '二级'} · ${focusLabels?.[field] || field}`}</span>
                <em>{field}</em>
              </label>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ExpandableValue({ value }) {
  const text = String(value || '').trim();
  const [expanded, setExpanded] = useState(false);

  if (!text) return <div className="result-value">-</div>;
  if (text.length <= 160) return <div className="result-value">{text}</div>;

  return (
    <div className="result-value">
      {expanded ? text : `${text.slice(0, 160)}...`}
      {' '}
      <button type="button" className="secondary-btn" onClick={() => setExpanded((prev) => !prev)}>
        {expanded ? '收起' : '展开'}
      </button>
    </div>
  );
}

function LocatorModal({ doc, field, focusLabels, extraTerms, onClose }) {
  const mapping = (doc.standard_mappings || []).find((item) => item.standard_field === field) || {};
  const page = bestVisualPage(doc, field, extraTerms);
  const evidence = collectEvidence(doc, field, extraTerms);
  const terms = [mapping.source_field_name, mapping.source_value, ...(extraTerms || [])].map((item) => String(item || '').trim()).filter(Boolean);
  const uniqueTerms = [...new Set(terms)];
  const highlights = page ? collectHighlights(page, uniqueTerms, field) : [];
  const badgeStyle = {
    background: `${fieldColor(field)}14`,
    borderColor: `${fieldColor(field)}66`,
    color: fieldColor(field),
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h3>{`${focusLabels?.[field] || field} ${TEXT.view}`}</h3>
            <p>{doc.doc_type || '-'}</p>
            <p className="doc-meta">{extractionMarker(doc)}</p>
          </div>
          <div className="action-row compact">
            {page ? <button type="button" className="secondary-btn" onClick={() => window.open(page.image_data_url, '_blank')}>{TEXT.zoomImage}</button> : null}
            <button type="button" className="secondary-btn" onClick={onClose}>{TEXT.close}</button>
          </div>
        </div>
        <div className="modal-grid">
          <section className="panel-card image-panel">
            <h4>{'\u5408\u540c\u9884\u89c8\u56fe'}</h4>
            {page ? (
              <div className="image-stage">
                <img src={page.image_data_url} alt={doc.filename} onClick={() => window.open(page.image_data_url, '_blank')} />
                <div className="image-overlay">
                  {highlights.map((box, index) => (
                    <div
                      key={`${box.term}:${index}`}
                      className="highlight-box"
                      title={box.term}
                      style={{
                        left: `${(box.x0 / Math.max(1, Number(page.page_width || 1))) * 100}%`,
                        top: `${(box.top / Math.max(1, Number(page.page_height || 1))) * 100}%`,
                        width: `${((box.x1 - box.x0) / Math.max(1, Number(page.page_width || 1))) * 100}%`,
                        height: `${((box.bottom - box.top) / Math.max(1, Number(page.page_height || 1))) * 100}%`,
                        borderColor: box.color,
                        background: `${box.color}1f`,
                        boxShadow: `0 0 0 1px ${box.color}55 inset`,
                      }}
                    />
                  ))}
                </div>
              </div>
            ) : <p className="muted-text">{TEXT.noImage}</p>}
            {highlights.length ? (
              <div className="legend-row">
                {highlights.slice(0, 4).map((item, index) => (
                  <span key={`${item.term}:${index}`} className="legend-tag" style={{ background: `${item.color}14`, color: item.color, borderColor: `${item.color}55` }}>{item.term}</span>
                ))}
              </div>
            ) : null}
          </section>
          <section className="side-stack">
            <section className="panel-card detail-panel">
              <div className="doc-name">{doc.filename}</div>
              <div className="field-badge top-gap-small" style={badgeStyle}>{focusLabels?.[field] || field}</div>
              <div className="detail-list">
                <div><strong>{'\u5408\u540c\u5b57\u6bb5\u540d\uff1a'}</strong>{mapping.source_field_name || '-'}</div>
                <div><strong>{'\u793a\u4f8b\u503c\uff1a'}</strong>{mapping.source_value || '-'}</div>
                <div><strong>{'\u8bc6\u522b\u6765\u6e90\uff1a'}</strong>{extractionMarker(doc)}</div>
              </div>
            </section>
            <section className="panel-card evidence-panel">
              <h4>{'\u6587\u672c\u547d\u4e2d\u7247\u6bb5'}</h4>
              {evidence.length ? evidence.map((item, index) => (
                <div key={`${item.term}:${index}`} className="evidence-card" style={{ borderColor: `${fieldColor(field)}44` }}>
                  <div className="doc-meta" style={{ color: fieldColor(field) }}>{`\u547d\u4e2d\u8bcd\uff1a${item.term}`}</div>
                  <div>{item.excerpt}</div>
                </div>
              )) : <p className="muted-text">{TEXT.noEvidence}</p>}
            </section>
          </section>
        </div>
      </div>
    </div>
  );
}

function App() {
  return (
    <AppErrorBoundary>
      <AppContent />
    </AppErrorBoundary>
  );
}

export default App;


