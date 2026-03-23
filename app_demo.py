from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from schemas.document_schema import STANDARD_FIELDS, STANDARD_FIELD_LABELS
from services.evaluator_service import evaluate_extraction
from services.extractor_service import (
    extract_document_with_options,
    list_prompt_versions,
    load_knowledge_file,
    save_knowledge_file,
)
from services.pdf_text_service import extract_pdf_text
from utils.file_utils import create_run_output_dir, save_bytes, save_json, save_text
from utils.json_utils import dump_json_text, normalize_text

ENV_PATH = Path(".env")
KNOWLEDGE_DIR = Path("knowledge")
OUTPUTS_DIR = Path("outputs")
PROMPTS_DIR = Path("llm/prompts")

MODEL_PRESETS = {
    "????": "deepseek-chat",
    "??????": "deepseek-reasoner",
    "???": "__custom__",
}

st.set_page_config(page_title="?? AI ???", layout="wide")


def _load_env_file() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    env_data: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env_data[key.strip()] = value.strip()
    return env_data


def _save_env_file(updates: dict[str, str]) -> None:
    env_data = _load_env_file()
    env_data.update(updates)
    ENV_PATH.write_text("\n".join(f"{k}={v}" for k, v in env_data.items()) + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value


def _resolve_model_preset(model_name: str) -> str:
    for preset_label, preset_model in MODEL_PRESETS.items():
        if preset_model == model_name:
            return preset_label
    return "???"


def _render_llm_config() -> None:
    env_data = _load_env_file()
    current_model = env_data.get("AUDIT_LLM_MODEL", "deepseek-reasoner")
    current_preset = _resolve_model_preset(current_model)
    preset_options = list(MODEL_PRESETS.keys())

    with st.sidebar:
        st.markdown("### ????")
        st.caption("??????????????????????????")
        with st.form("llm_config_form", clear_on_submit=False):
            api_key = st.text_input("API Key", value=env_data.get("AUDIT_LLM_API_KEY", ""), type="password")
            base_url = st.text_input("Base URL", value=env_data.get("AUDIT_LLM_BASE_URL", "https://api.deepseek.com"))
            preset_label = st.selectbox(
                "????",
                options=preset_options,
                index=preset_options.index(current_preset),
                help="????????????????????????????????????",
            )
            if preset_label == "???":
                model_name = st.text_input("??????", value=current_model)
            else:
                model_name = MODEL_PRESETS[preset_label]
                st.text_input("????", value=model_name, disabled=True)
            timeout_value = st.number_input(
                "?????",
                min_value=30,
                max_value=600,
                value=int(env_data.get("AUDIT_LLM_TIMEOUT", "180") or "180"),
                step=10,
            )
            submitted = st.form_submit_button("??????", use_container_width=True)
        if submitted:
            _save_env_file(
                {
                    "AUDIT_LLM_API_KEY": api_key.strip(),
                    "AUDIT_LLM_BASE_URL": base_url.strip(),
                    "AUDIT_LLM_MODEL": model_name.strip(),
                    "AUDIT_LLM_TIMEOUT": str(timeout_value),
                }
            )
            st.success(f"????????????????{model_name.strip()}")
            st.rerun()


def _render_prompt_editor() -> tuple[str, str, bool, str]:
    prompt_files = list_prompt_versions()
    options = [prompt.name for prompt in prompt_files]
    selected_name = st.selectbox("???????", options=options, index=0)
    selected_path = next(prompt for prompt in prompt_files if prompt.name == selected_name)
    default_prompt_text = selected_path.read_text(encoding="utf-8")
    st.caption(f"?? prompt ???`{selected_path}`")
    prompt_text = st.text_area(
        "Prompt ???",
        value=default_prompt_text,
        height=380,
        key=f"prompt_editor_{selected_name}",
        help="?????????????????????????????",
    )
    save_as_new = st.checkbox("??? prompt ??????", value=False)
    new_prompt_name = st.text_input("? prompt ?????? extract_prompt_v2.txt?", value="extract_prompt_v2.txt")
    return selected_name, prompt_text, save_as_new, new_prompt_name


def _save_prompt_as_new_version(prompt_text: str, file_name: str) -> str:
    target_name = file_name.strip() or "extract_prompt_v_new.txt"
    if not target_name.endswith(".txt"):
        target_name += ".txt"
    target_path = PROMPTS_DIR / target_name
    target_path.write_text(prompt_text, encoding="utf-8")
    return target_name


def _normalize_alias_candidates(raw) -> list[dict]:
    if isinstance(raw, list):
        result = []
        for item in raw:
            if isinstance(item, dict):
                result.append(
                    {
                        "standard_field": item.get("standard_field", ""),
                        "alias": item.get("alias", ""),
                        "source": item.get("source", ""),
                        "status": item.get("status", "candidate"),
                    }
                )
        return result
    if isinstance(raw, dict):
        result = []
        for field_name, aliases in raw.items():
            for alias in aliases or []:
                result.append(
                    {
                        "standard_field": field_name,
                        "alias": alias,
                        "source": "",
                        "status": "candidate",
                    }
                )
        return result
    return []


def _normalize_rule_list(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "name": item.get("name", ""),
                "field": item.get("field", item.get("applicable_field", "")),
                "rule_type": item.get("rule_type", item.get("type", "")),
                "content": item.get("content", item.get("description", "")),
                "status": item.get("status", "active"),
            }
        )
    return result


def _save_alias_candidates(items: list[dict]) -> None:
    save_knowledge_file(KNOWLEDGE_DIR / "alias_candidates.json", items)


def _save_rule_candidates(items: list[dict]) -> None:
    save_knowledge_file(KNOWLEDGE_DIR / "rule_candidates.json", items)


def _append_alias_candidate(field_name: str, alias_text: str, source: str) -> None:
    items = _normalize_alias_candidates(load_knowledge_file(KNOWLEDGE_DIR / "alias_candidates.json"))
    aliases = [item.strip() for item in alias_text.replace("\n", ",").split(",") if item.strip()]
    for alias in aliases:
        items.append(
            {
                "standard_field": field_name,
                "alias": alias,
                "source": source.strip(),
                "status": "candidate",
            }
        )
    _save_alias_candidates(items)


def _activate_alias_candidate(index: int) -> None:
    items = _normalize_alias_candidates(load_knowledge_file(KNOWLEDGE_DIR / "alias_candidates.json"))
    alias_active = load_knowledge_file(KNOWLEDGE_DIR / "alias_active.json")
    item = items[index]
    alias_active.setdefault(item["standard_field"], [])
    if item["alias"] not in alias_active[item["standard_field"]]:
        alias_active[item["standard_field"]].append(item["alias"])
    save_knowledge_file(KNOWLEDGE_DIR / "alias_active.json", alias_active)
    del items[index]
    _save_alias_candidates(items)


def _delete_alias_candidate(index: int) -> None:
    items = _normalize_alias_candidates(load_knowledge_file(KNOWLEDGE_DIR / "alias_candidates.json"))
    del items[index]
    _save_alias_candidates(items)


def _append_rule_candidate(payload: dict) -> None:
    items = _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_candidates.json"))
    payload["status"] = "candidate"
    items.append(payload)
    _save_rule_candidates(items)


def _activate_rule_candidate(index: int) -> None:
    candidates = _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_candidates.json"))
    active_rules = _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_active.json"))
    item = candidates[index]
    item["status"] = "active"
    active_rules.append(item)
    save_knowledge_file(KNOWLEDGE_DIR / "rule_active.json", active_rules)
    del candidates[index]
    _save_rule_candidates(candidates)


def _delete_rule_candidate(index: int) -> None:
    candidates = _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_candidates.json"))
    del candidates[index]
    _save_rule_candidates(candidates)


def _deactivate_rule(index: int) -> None:
    active_rules = _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_active.json"))
    candidates = _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_candidates.json"))
    item = active_rules[index]
    item["status"] = "candidate"
    candidates.append(item)
    _save_rule_candidates(candidates)
    del active_rules[index]
    save_knowledge_file(KNOWLEDGE_DIR / "rule_active.json", active_rules)


def _save_active_alias(field_name: str, aliases: list[str]) -> None:
    alias_active = load_knowledge_file(KNOWLEDGE_DIR / "alias_active.json")
    alias_active[field_name] = aliases
    save_knowledge_file(KNOWLEDGE_DIR / "alias_active.json", alias_active)


def _render_alias_config() -> None:
    alias_active = load_knowledge_file(KNOWLEDGE_DIR / "alias_active.json")
    alias_candidates = _normalize_alias_candidates(load_knowledge_file(KNOWLEDGE_DIR / "alias_candidates.json"))

    st.markdown("#### ???????")
    alias_rows = []
    for field_name in STANDARD_FIELDS:
        alias_rows.append(
            {
                "????": field_name,
                "???": STANDARD_FIELD_LABELS.get(field_name, field_name),
                "???????": "?".join(alias_active.get(field_name, [])),
            }
        )
    st.dataframe(pd.DataFrame(alias_rows), use_container_width=True, hide_index=True)

    edit_field = st.selectbox("??????????", options=STANDARD_FIELDS, key="alias_edit_field")
    current_aliases = alias_active.get(edit_field, [])
    st.caption(f"?????{STANDARD_FIELD_LABELS.get(edit_field, edit_field)}")
    st.write("??????")
    if current_aliases:
        for alias in current_aliases:
            col_alias, col_delete = st.columns([5, 1])
            with col_alias:
                st.text(alias)
            with col_delete:
                if st.button("??", key=f"del_active_alias_{edit_field}_{alias}"):
                    _save_active_alias(edit_field, [item for item in current_aliases if item != alias])
                    st.rerun()
    else:
        st.info("???????????")

    with st.form("active_alias_edit_form", clear_on_submit=True):
        new_aliases_text = st.text_input("?????????????????")
        save_alias = st.form_submit_button("????")
    if save_alias:
        merged = list(current_aliases)
        for alias in [item.strip() for item in new_aliases_text.replace("\n", ",").split(",") if item.strip()]:
            if alias not in merged:
                merged.append(alias)
        _save_active_alias(edit_field, merged)
        st.success("??????")
        st.rerun()

    st.markdown("#### ???????")
    with st.form("alias_candidate_form", clear_on_submit=True):
        field_name = st.selectbox("??????", options=STANDARD_FIELDS, key="alias_candidate_field")
        alias_text = st.text_input("?????????????")
        source_text = st.text_input("????????")
        add_alias = st.form_submit_button("?????")
    if add_alias and alias_text.strip():
        _append_alias_candidate(field_name, alias_text, source_text)
        st.success("???????????")
        st.rerun()

    st.markdown("#### ???????")
    if not alias_candidates:
        st.info("????????")
    for idx, item in enumerate(alias_candidates):
        cols = st.columns([2, 2, 2, 1, 2])
        cols[0].write(item["standard_field"])
        cols[1].write(item["alias"])
        cols[2].write(item.get("source", ""))
        cols[3].write(item.get("status", "candidate"))
        action_cols = cols[4].columns(2)
        if action_cols[0].button("??", key=f"activate_alias_{idx}"):
            _activate_alias_candidate(idx)
            st.rerun()
        if action_cols[1].button("??", key=f"delete_alias_{idx}"):
            _delete_alias_candidate(idx)
            st.rerun()


def _build_rule_name(rule_type: str, field_name: str) -> str:
    type_map = {
        "??????": "priority",
        "??????": "distinguish",
        "??????": "missing",
    }
    return f"{type_map.get(rule_type, 'rule')}_{field_name}"


def _render_rule_candidate_form() -> None:
    st.markdown("#### ???????")
    rule_type = st.selectbox(
        "??????",
        options=["??????", "??????", "??????"],
        key="rule_template",
    )
    with st.form("rule_candidate_form", clear_on_submit=True):
        field_name = st.selectbox("????", options=STANDARD_FIELDS, key="rule_field_name")
        payload = {"field": field_name, "rule_type": rule_type}
        if rule_type == "??????":
            high_kw = st.text_input("???????")
            low_kw = st.text_input("???????")
            note = st.text_input("??")
            payload["content"] = f"????[{high_kw}]????????[{low_kw}]???[{note}]"
        elif rule_type == "??????":
            kw_a = st.text_input("???A")
            meaning_a = st.text_input("????A")
            kw_b = st.text_input("???B")
            meaning_b = st.text_input("????B")
            note = st.text_input("??")
            payload["content"] = f"A[{kw_a}->{meaning_a}]?B[{kw_b}->{meaning_b}]???[{note}]"
        else:
            missing_action = st.text_input("?????????")
            note = st.text_input("??")
            payload["content"] = f"?????[{missing_action}]???[{note}]"
        payload["name"] = _build_rule_name(rule_type, field_name)
        submitted = st.form_submit_button("?????")
    if submitted:
        _append_rule_candidate(payload)
        st.success("???????????")
        st.rerun()


def _render_rule_config() -> None:
    active_rules = _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_active.json"))
    candidate_rules = _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_candidates.json"))

    st.markdown("#### ???????")
    if not active_rules:
        st.info("????????")
    for idx, rule in enumerate(active_rules):
        with st.container(border=True):
            st.markdown(f"**{rule.get('name', '')}**")
            st.write(f"?????{rule.get('field', '')}")
            st.write(f"?????{rule.get('rule_type', '')}")
            st.write(f"?????{rule.get('content', '')}")
            st.write(f"???{rule.get('status', 'active')}")
            cols = st.columns(2)
            if cols[0].button("??", key=f"edit_rule_{idx}"):
                st.session_state.rule_edit_index = idx
            if cols[1].button("??", key=f"deactivate_rule_{idx}"):
                _deactivate_rule(idx)
                st.rerun()

    edit_index = st.session_state.get("rule_edit_index")
    if isinstance(edit_index, int) and 0 <= edit_index < len(active_rules):
        rule = active_rules[edit_index]
        with st.expander("???????", expanded=True):
            with st.form("edit_active_rule_form"):
                name = st.text_input("????", value=rule.get("name", ""))
                field_default = rule.get("field", STANDARD_FIELDS[0])
                field_name = st.selectbox(
                    "????",
                    options=STANDARD_FIELDS,
                    index=STANDARD_FIELDS.index(field_default) if field_default in STANDARD_FIELDS else 0,
                )
                rule_type = st.text_input("????", value=rule.get("rule_type", ""))
                content = st.text_area("????", value=rule.get("content", ""), height=120)
                saved = st.form_submit_button("????")
            if saved:
                active_rules[edit_index] = {
                    "name": name,
                    "field": field_name,
                    "rule_type": rule_type,
                    "content": content,
                    "status": "active",
                }
                save_knowledge_file(KNOWLEDGE_DIR / "rule_active.json", active_rules)
                st.session_state.rule_edit_index = None
                st.success("??????")
                st.rerun()

    _render_rule_candidate_form()

    st.markdown("#### ???????")
    if not candidate_rules:
        st.info("????????")
    for idx, rule in enumerate(candidate_rules):
        cols = st.columns([2, 2, 2, 1, 2])
        cols[0].write(rule.get("name", ""))
        cols[1].write(rule.get("field", ""))
        cols[2].write(rule.get("rule_type", ""))
        cols[3].write(rule.get("status", "candidate"))
        action_cols = cols[4].columns(2)
        if action_cols[0].button("??", key=f"activate_rule_{idx}"):
            _activate_rule_candidate(idx)
            st.rerun()
        if action_cols[1].button("??", key=f"delete_rule_{idx}"):
            _delete_rule_candidate(idx)
            st.rerun()


def _render_knowledge_manager() -> tuple[bool, bool, dict, list]:
    st.subheader("????????")
    st.caption("??????????????????????????")
    use_alias_active = st.checkbox("?????????????", value=True)
    use_rule_active = st.checkbox("?????????????", value=True)
    st.caption("????????????????????????")
    col_left, col_right = st.columns(2)
    with col_left:
        _render_alias_config()
    with col_right:
        _render_rule_config()
    alias_active = load_knowledge_file(KNOWLEDGE_DIR / "alias_active.json") if use_alias_active else {}
    rule_active = _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_active.json")) if use_rule_active else []
    return use_alias_active, use_rule_active, alias_active, rule_active


def _ai_value_map(structured_data: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in structured_data.get("mapped_fields", []):
        field_name = item.get("standard_field", "")
        if field_name:
            result[field_name] = item.get("source_value") or ""
    return result


def _build_confirmation_dataframe(ai_values: dict[str, str], manual_values: dict[str, str]) -> pd.DataFrame:
    rows = []
    for field_name in STANDARD_FIELDS:
        ai_value = ai_values.get(field_name, "")
        manual_value = manual_values.get(field_name, ai_value)
        is_correct = bool(manual_value) and normalize_text(manual_value) == normalize_text(ai_value)
        rows.append(
            {
                "????": field_name,
                "???": STANDARD_FIELD_LABELS.get(field_name, field_name),
                "AI???": ai_value,
                "?????": manual_value,
                "????": is_correct,
            }
        )
    return pd.DataFrame(rows)


def _render_manual_confirmation(structured_data: dict) -> tuple[dict[str, str], pd.DataFrame]:
    st.subheader("???????????????")
    st.caption("????????????????????? AI ?????????????????????????????")
    ai_values = _ai_value_map(structured_data)
    if "manual_confirm_values" not in st.session_state:
        st.session_state.manual_confirm_values = dict(ai_values)
    if st.button("AI???????????"):
        st.session_state.manual_confirm_values = dict(ai_values)
        st.rerun()
    confirmation_df = _build_confirmation_dataframe(ai_values, st.session_state.manual_confirm_values)
    edited_df = st.data_editor(
        confirmation_df,
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        column_config={
            "????": st.column_config.TextColumn(disabled=True),
            "???": st.column_config.TextColumn(disabled=True),
            "AI???": st.column_config.TextColumn(disabled=True),
            "?????": st.column_config.TextColumn(help="?? AI ??????????????"),
            "????": st.column_config.CheckboxColumn(disabled=True),
        },
        key="manual_confirmation_editor",
    )
    gold_answer = {row["????"]: row["?????"] or "" for _, row in edited_df.iterrows()}
    st.session_state.manual_confirm_values = gold_answer
    with st.expander("????????????? JSON", expanded=False):
        st.code(dump_json_text(gold_answer), language="json")
    return gold_answer, edited_df


def _save_experiment_result(
    run_dir: Path,
    uploaded_name: str,
    uploaded_bytes: bytes,
    prompt_file_name: str,
    prompt_text: str,
    pdf_result: dict,
    extraction_result: dict,
    gold_answer: dict[str, str],
    evaluation_result,
    confirmation_df: pd.DataFrame,
) -> None:
    save_bytes(run_dir / "inputs" / uploaded_name, uploaded_bytes)
    save_text(run_dir / "raw_text.txt", pdf_result.get("text", ""))
    save_text(run_dir / "prompt" / prompt_file_name, prompt_text)
    save_text(run_dir / "llm_raw_response.txt", extraction_result.get("raw_model_response", ""))
    if extraction_result.get("repair_raw_response"):
        save_text(run_dir / "llm_repair_response.txt", extraction_result.get("repair_raw_response", ""))
    save_json(run_dir / "structured_result.json", extraction_result.get("structured_data", {}))
    save_json(run_dir / "gold_answer.json", gold_answer)
    save_json(run_dir / "evaluation_result.json", evaluation_result.model_dump())
    save_json(run_dir / "pdf_text_result.json", pdf_result)
    save_json(run_dir / "metadata.json", extraction_result.get("metadata", {}))
    save_json(run_dir / "manual_confirmation_table.json", confirmation_df.to_dict(orient="records"))
    save_json(run_dir / "knowledge" / "alias_active.json", extraction_result.get("metadata", {}).get("alias_active_used", {}))
    save_json(run_dir / "knowledge" / "rule_active.json", extraction_result.get("metadata", {}).get("rule_active_used", []))
    save_json(run_dir / "knowledge" / "alias_candidates.json", _normalize_alias_candidates(load_knowledge_file(KNOWLEDGE_DIR / "alias_candidates.json")))
    save_json(run_dir / "knowledge" / "rule_candidates.json", _normalize_rule_list(load_knowledge_file(KNOWLEDGE_DIR / "rule_candidates.json")))


def _store_extraction_state(payload: dict) -> None:
    st.session_state.latest_experiment = payload
    st.session_state.manual_confirm_values = dict(payload.get("ai_values", {}))
    st.session_state.latest_evaluation = None
    st.session_state.latest_output_dir = None


def main() -> None:
    st.title("?? AI ???")
    st.caption("??????????????????????????????????")
    _render_llm_config()
    with st.sidebar:
        st.markdown("### ????")
        st.write("1. ?????? PDF ??")
        st.write("2. ??????? prompt")
        st.write("3. ?????????????")
        st.write("4. ??????? AI ??")
        st.write("5. ?????????????")
        st.divider()
        st.write(f"?????{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    st.subheader("????")
    uploaded_file = st.file_uploader("????? PDF", type=["pdf"], key="single_pdf")

    selected_prompt_name, prompt_text, save_as_new, new_prompt_name = _render_prompt_editor()
    use_alias_active, use_rule_active, alias_active_override, rule_active_override = _render_knowledge_manager()

    start = st.button("????????", type="primary", use_container_width=True)
    if start:
        if uploaded_file is None:
            st.error("?????? PDF ???")
            return
        if not os.getenv("AUDIT_LLM_API_KEY", "").strip():
            st.error("???????????? API Key?")
            return

        actual_prompt_name = _save_prompt_as_new_version(prompt_text, new_prompt_name) if save_as_new else selected_prompt_name
        uploaded_bytes = uploaded_file.getvalue()
        try:
            with st.status("???????...", expanded=True) as status:
                st.write("?? 1/2??? PDF ??")
                pdf_result = extract_pdf_text(uploaded_file.name, uploaded_bytes)
                st.write("?? 2/2????????????")
                extraction_result = extract_document_with_options(
                    pdf_result=pdf_result,
                    prompt_file_name=actual_prompt_name,
                    prompt_text=prompt_text,
                    use_alias_active=use_alias_active,
                    use_rule_active=use_rule_active,
                    alias_active_override=alias_active_override,
                    rule_active_override=rule_active_override,
                )
                status.update(label="?????????????????", state="complete", expanded=False)
        except Exception as exc:
            st.exception(exc)
            return

        _store_extraction_state(
            {
                "uploaded_name": uploaded_file.name,
                "uploaded_bytes": uploaded_bytes,
                "prompt_file_name": actual_prompt_name,
                "prompt_text": prompt_text,
                "pdf_result": pdf_result.model_dump(),
                "extraction_result": extraction_result.model_dump(),
                "ai_values": _ai_value_map(extraction_result.structured_data),
            }
        )
        st.rerun()

    latest = st.session_state.get("latest_experiment")
    if not latest:
        st.info("?? PDF ????????????????????????AI ??????????????")
        return

    pdf_result = latest["pdf_result"]
    extraction_result = latest["extraction_result"]
    gold_answer, confirmation_df = _render_manual_confirmation(extraction_result["structured_data"])

    if st.button("?????????????", type="primary", use_container_width=True):
        evaluation_result = evaluate_extraction(extraction_result["structured_data"], gold_answer)
        run_dir = create_run_output_dir(OUTPUTS_DIR)
        _save_experiment_result(
            run_dir,
            latest["uploaded_name"],
            latest["uploaded_bytes"],
            latest["prompt_file_name"],
            latest["prompt_text"],
            pdf_result,
            extraction_result,
            gold_answer,
            evaluation_result,
            confirmation_df,
        )
        st.session_state.latest_evaluation = evaluation_result.model_dump()
        st.session_state.latest_output_dir = str(run_dir)
        st.success(f"???????????{run_dir}")

    for warning in [*pdf_result.get("warnings", []), *extraction_result.get("warnings", [])]:
        st.warning(warning)

    st.subheader("??????")
    st.json(
        {
            "prompt_file": latest["prompt_file_name"],
            "use_alias_active": extraction_result.get("metadata", {}).get("use_alias_active"),
            "use_rule_active": extraction_result.get("metadata", {}).get("use_rule_active"),
            "alias_count_used": len(extraction_result.get("metadata", {}).get("alias_active_used", {})),
            "rule_count_used": len(extraction_result.get("metadata", {}).get("rule_active_used", [])),
            "model_name": extraction_result.get("metadata", {}).get("model_name", ""),
        }
    )

    st.subheader("????")
    st.text_area("PDF ????", value=pdf_result.get("text", ""), height=320, key="raw_pdf_text")

    st.subheader("Prompt ??")
    st.write(f"?? Prompt ???`{latest['prompt_file_name']}`")
    st.code(latest["prompt_text"], language="text")

    st.subheader("AI ????")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("??????", extraction_result["structured_data"].get("doc_type", ""))
        st.json(extraction_result["structured_data"].get("mapped_fields", []))
    with col2:
        st.markdown("#### missing_fields")
        st.json(extraction_result["structured_data"].get("missing_fields", []))
        st.markdown("#### uncertain_fields")
        st.json(extraction_result["structured_data"].get("uncertain_fields", []))
    st.markdown("#### raw_summary")
    st.write(extraction_result["structured_data"].get("raw_summary", ""))

    latest_evaluation = st.session_state.get("latest_evaluation")
    if latest_evaluation:
        st.subheader("????")
        st.json(latest_evaluation)
        st.caption(f"???????{st.session_state.get('latest_output_dir', '')}")

    st.subheader("??????")
    st.text_area("??????", value=extraction_result.get("raw_model_response", ""), height=260, key="raw_llm_response")
    if extraction_result.get("repair_raw_response"):
        st.text_area("JSON ??????", value=extraction_result.get("repair_raw_response", ""), height=220, key="repair_llm_response")


if __name__ == "__main__":
    main()
