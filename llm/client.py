from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from audit_system.config import settings


load_dotenv(override=True)


@dataclass(slots=True)
class LLMResponse:
    text: str
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class LLMRuntimeConfig:
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    timeout: int | None = None
    ocr_model: str | None = None


class LLMClient:
    def __init__(self, runtime_config: LLMRuntimeConfig | None = None, model: str | None = None) -> None:
        config = runtime_config or LLMRuntimeConfig()
        api_key = (config.api_key if config.api_key is not None else settings.llm_api_key).strip()
        if not api_key:
            raise RuntimeError("未配置 AUDIT_LLM_API_KEY，无法调用大模型。")
        base_url = config.base_url if config.base_url is not None else settings.llm_base_url
        timeout = config.timeout if config.timeout is not None else settings.llm_timeout
        default_model = config.model if config.model is not None else settings.llm_model
        self.model = (model or default_model or "").strip()
        if not self.model:
            raise RuntimeError("未配置可用模型名称，无法调用大模型。")
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url.strip() if isinstance(base_url, str) and base_url.strip() else None,
            timeout=timeout,
        )

    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        message = response.choices[0].message.content or ""
        return LLMResponse(text=message, raw_payload=response.model_dump())

    def complete_text(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        message = response.choices[0].message.content or ""
        return LLMResponse(text=message, raw_payload=response.model_dump())

    def transcribe_images(self, system_prompt: str, user_prompt: str, image_urls: list[str]) -> LLMResponse:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        content.extend({"type": "image_url", "image_url": {"url": image_url}} for image_url in image_urls)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        )
        message = response.choices[0].message.content or ""
        return LLMResponse(text=message, raw_payload=response.model_dump())


def parse_json_with_fallback(raw_text: str) -> dict[str, Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw_text[start : end + 1])
        raise
