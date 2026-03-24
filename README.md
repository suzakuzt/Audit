# Audit System

一个聚焦审单场景的批量核心字段提取验证器，当前主链路为 `FastAPI + React`，已包含批量上传、核心字段提取、人工确认、准确率评估、批量汇总统计，以及 Prompt/Alias/Rule 配置能力。

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
- `http://127.0.0.1:8000/docs`

## 环境变量

- 复制 `.env.example` 为 `.env`
- 如需调用大模型，设置 `AUDIT_LLM_API_KEY`
- 如需 PDF 文本抽取，确认 `AUDIT_PDFINFO_PATH` 和 `AUDIT_PDFTOTEXT_PATH` 指向本机 Poppler 可执行文件

## 项目结构

```text
audit_system/
├─ src/audit_system/          # FastAPI 应用、数据库模型、API 路由
├─ frontend/                  # React 源码
├─ alembic/                   # 数据库迁移
├─ services/                  # 提取、OCR、评估、知识库等核心服务
├─ schemas/                   # 文档提取与评估结构
├─ llm/                       # Prompt 与 LLM 客户端
├─ knowledge/                 # alias / rule 数据
├─ tests/                     # 后端测试
└─ pyproject.toml
```

## 当前代码主链路

- 页面入口：`src/audit_system/main.py`
- API 路由：`src/audit_system/api/routes/document_compare.py`
- 前端页面：`frontend/src/App.jsx`
- 提取主流程：`services/pdf_text_service.py` -> `services/extractor_service.py` -> `services/evaluator_service.py`

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
