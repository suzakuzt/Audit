# Audit System

一个聚焦审单场景的批量核心字段提取验证器，当前已包含批量上传、核心字段提取、人工确认、准确率评估、批量汇总统计，以及 Prompt/Alias/Rule 版本记录能力。

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env
alembic upgrade head
uvicorn audit_system.main:app --reload
```

启动后可访问：

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/api/v1/audit-logs`
- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/foundation`
- `http://127.0.0.1:8000/compare`
- `http://127.0.0.1:8000/docs`

## 环境变量

- 复制 `.env.example` 为 `.env`
- 如需调用大模型，设置 `AUDIT_LLM_API_KEY`
- 如需 PDF 文本抽取，确认 `AUDIT_PDFINFO_PATH` 和 `AUDIT_PDFTOTEXT_PATH` 指向本机 Poppler 可执行文件

## 项目结构

```text
audit_system/
├─ src/audit_system/
│  ├─ api/
│  ├─ db/
│  ├─ models/
│  ├─ schemas/
│  ├─ services/
│  ├─ config.py
│  └─ main.py
├─ alembic/
│  ├─ versions/
│  └─ env.py
├─ llm/
├─ tests/
└─ pyproject.toml
```

## 当前目标

第一阶段：
- 批量验证几百份真实单据的核心字段提取能力边界
- 识别哪些字段稳定、哪些字段容易错
- 观察不同文件类型、不同模板下的边界值
- 输出文件级和字段级准确率统计

第二阶段：
- 在同一批样本上比较 Prompt、Alias、Rule 增强前后的准确率变化
- 验证增强手段是否真实有效

## 测试

```bash
pytest
```
