import { useMemo, useState } from 'react';

const PROMPT_SECTIONS = [
  {
    id: 'base',
    label: '基础理解',
    hint: '先让 AI 理解这段内容在业务里表达什么，再决定是否提字段。',
    placeholder: [
      '你是一个用于外贸审单的字段理解助手。',
      '先判断文本片段表达的业务含义，再判断是否能映射到标准字段。',
      '字段名只能作为线索，不能作为唯一依据。',
      '如果证据不足，返回 missing 或 uncertain，不要强行猜测。',
    ].join('\n'),
  },
  {
    id: 'classify',
    label: '单据分类',
    hint: '先区分合同、发票、提单、装箱单，再看字段在该单据中的作用。',
    placeholder: [
      '先识别单据类型，再决定字段优先级。',
      '合同里优先看主体、付款、货物、港口、编号；',
      '发票里优先看金额、单价、品名、编号；',
      '提单里优先看收货人、通知方、港口、船期。',
    ].join('\n'),
  },
  {
    id: 'field_understanding',
    label: '字段意义理解',
    hint: '重点强化“先识别字段意义，再映射标准字段”。',
    placeholder: [
      '识别字段时遵循以下顺序：',
      '1. 先看这段内容像什么业务块，例如主体信息、地址信息、付款条款、物流信息、货物信息。',
      '2. 再看它表达的是谁、什么时间、什么金额、哪个港口、哪类编号。',
      '3. 最后再映射到标准字段。',
      '如果字段名是 client、buyer、consignee、address 这类混乱写法，先按内容结构判断其业务意义。',
      '如果内容包含公司名、地址、电话、邮箱，优先按主体信息理解，而不是机械按字段名映射。',
    ].join('\n'),
  },
];

const SEMANTIC_STEPS = [
  '先看内容属于什么语义块，不要先死盯字段名。',
  '再判断这段内容表达的是哪类业务对象，比如主体、金额、港口、日期、编号。',
  '最后才映射到标准字段，避免因为 client / buyer / address 这类混乱写法误判。',
];

const SEMANTIC_EXAMPLES = [
  'Client Address / Buyer / Consignee：先判断内容是否是公司名 + 地址 + 联系方式，再细分是买方还是收货人。',
  'Port / Destination / Loading：先判断是启运港还是目的港，不要只看 Port 这个词。',
  'PI No / Contract No / Factory No：先判断编号所在语义块，再决定是哪一种编号。',
];

function buildReferenceText(config, focusLabels) {
  const fragments = Array.isArray(config?.fragments) ? config.fragments : [];
  const byId = Object.fromEntries(fragments.map((item) => [item.id, item]));
  return [
    {
      title: '编号字段理解',
      content: byId.numbering_fields?.content || '重点区分 contract_no、factory_no、hs_code 等编号字段。',
      fields: ['contract_no', 'factory_no', 'hs_code'],
    },
    {
      title: '主体字段理解',
      content: byId.party_fields?.content || '主体类字段先结合公司名、地址、联系人、电话、邮箱判断其业务角色。',
      fields: ['consignee_name_address', 'beneficiary_bank', 'port_of_origin', 'port_of_destination'],
    },
    {
      title: 'OCR 与兜底',
      content: [byId.ocr_noise_tolerance?.content, byId.fallback_handling?.content].filter(Boolean).join('\n') || '证据弱时优先保守输出，不要为了命中率强行填值。',
      fields: [],
    },
  ].map((item) => ({
    ...item,
    labels: item.fields.map((field) => focusLabels?.[field] || field),
  }));
}

export default function PromptLearningCenter({
  promptCenterConfig,
  promptFileName = 'extract_prompt_v1.txt',
  learningPrompts = {},
  learningPromptFlags = {},
  onPromptChange,
  onPromptFlagChange,
  focusFields = [],
  focusLabels = {},
  priorityFields = [],
  defaultFocusFields = [],
  onSave,
  learningStatus,
}) {
  const [activeSection, setActiveSection] = useState('field_understanding');
  const references = useMemo(() => buildReferenceText(promptCenterConfig, focusLabels), [promptCenterConfig, focusLabels]);

  return (
    <section className="learning-stack prompt-center-simple">
      <section className="panel-card learning-hero-card">
        <div className="section-head">
          <div>
            <h3>提示词配置</h3>
            <p>这里先解决一件事：让 AI 先理解单据字段的业务意义，再去做标准字段映射。</p>
            <p className="muted-text">{`当前主提示词文件：${promptFileName}`}</p>
          </div>
          <div className="prompt-lite-actions">
            <button type="button" onClick={onSave}>保存</button>
          </div>
        </div>
        <div className="summary-chip-row top-gap-small">
          <div className="summary-chip-card">
            <span className="summary-label">当前重点</span>
            <strong>字段意义优先</strong>
            <span className="doc-meta">先理解内容表达，再映射标准字段</span>
          </div>
          <div className="summary-chip-card">
            <span className="summary-label">启用字段</span>
            <strong>{focusFields.length}</strong>
            <span className="doc-meta">{focusFields.map((field) => focusLabels?.[field] || field).join('、') || '未设置'}</span>
          </div>
          <div className="summary-chip-card">
            <span className="summary-label">优先字段</span>
            <strong>{priorityFields.length}</strong>
            <span className="doc-meta">{priorityFields.map((field) => focusLabels?.[field] || field).join('、') || '未设置'}</span>
          </div>
          <div className="summary-chip-card">
            <span className="summary-label">默认字段</span>
            <strong>{defaultFocusFields.length}</strong>
            <span className="doc-meta">{defaultFocusFields.map((field) => focusLabels?.[field] || field).join('、') || '未设置'}</span>
          </div>
        </div>
      </section>

      <section className="prompt-lite-grid">
        <section className="panel-card prompt-lite-main">
          <div className="section-head">
            <h3>核心提示词</h3>
            <span className="field-guide-count">{PROMPT_SECTIONS.length} 段</span>
          </div>
          <div className="prompt-lite-fragments">
            {PROMPT_SECTIONS.map((section) => (
              <button
                key={section.id}
                type="button"
                className={`prompt-fragment-item ${section.id === activeSection ? 'active' : ''}`}
                onClick={() => setActiveSection(section.id)}
              >
                <strong>{section.label}</strong>
                <span>{section.hint}</span>
                <span>{section.id === 'base' ? '主控制段' : (learningPromptFlags?.[section.id] === false ? '已停用' : '已启用')}</span>
              </button>
            ))}
          </div>

          {PROMPT_SECTIONS.map((section) => {
            if (section.id !== activeSection) return null;
            return (
              <div className="prompt-lite-editor" key={section.id}>
                <div className="prompt-editor-toolbar">
                  <strong>{section.label}</strong>
                  {section.id !== 'base' ? (
                    <label className="field-center-switch">
                      <input
                        type="checkbox"
                        checked={learningPromptFlags?.[section.id] !== false}
                        onChange={(event) => onPromptFlagChange?.(section.id, event.target.checked)}
                      />
                      <span>启用本段</span>
                    </label>
                  ) : (
                    <span className="field-center-tag">主控制段</span>
                  )}
                </div>
                <textarea
                  className="prompt-fragment-textarea"
                  value={learningPrompts?.[section.id] || ''}
                  placeholder={section.placeholder}
                  onChange={(event) => onPromptChange?.(section.id, event.target.value)}
                />
              </div>
            );
          })}
        </section>

        <section className="prompt-lite-side">
          <section className="panel-card">
            <div className="section-head">
              <h3>字段意义理解顺序</h3>
              <span className="field-guide-count">3 步</span>
            </div>
            <div className="history-list">
              {SEMANTIC_STEPS.map((item) => (
                <article className="history-item" key={item}>
                  <p className="compact-line">{item}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="panel-card">
            <div className="section-head">
              <h3>常见混乱字段提醒</h3>
              <span className="field-guide-count">{SEMANTIC_EXAMPLES.length} 条</span>
            </div>
            <div className="history-list">
              {SEMANTIC_EXAMPLES.map((item) => (
                <article className="history-item" key={item}>
                  <p className="compact-line">{item}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="panel-card">
            <div className="section-head">
              <h3>字段规则参考</h3>
              <span className="field-guide-count">{references.length} 类</span>
            </div>
            <div className="history-list">
              {references.map((item) => (
                <article className="history-item" key={item.title}>
                  <strong>{item.title}</strong>
                  <p className="compact-line">{item.content}</p>
                  {item.labels.length ? <p className="compact-line">{`相关字段：${item.labels.join('、')}`}</p> : null}
                </article>
              ))}
            </div>
          </section>
        </section>
      </section>

      {learningStatus?.message ? <div className="warn-box rule-save-tip">{learningStatus.message}</div> : null}
    </section>
  );
}
