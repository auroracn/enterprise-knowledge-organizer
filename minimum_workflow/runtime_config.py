from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from minimum_workflow.contracts import PROJECT_ROOT
from minimum_workflow.llm_registry import (
    DEFAULT_LLM_PROVIDER,
    LLM_PROVIDERS,
    LLMProviderSpec,
    get_provider_spec,
)


DEFAULT_PROFILE_ID = "chanfengdikongzl"


_CONFIG_FIELD_ALIASES: list[tuple[str, str, tuple[str, ...]]] = [
    ("qwen", "api_key", ("qwen_api_key", "qwen-key", "qwen api key")),
    ("qwen", "base_url", ("qwen api连接", "qwen_api_base", "qwen_base_url")),
    ("qwen", "model", ("qwen模型", "qwen_model", "qwen model")),
    ("deepseek", "api_key", ("deepseek_api_key", "deepseek-key", "deepseek api key")),
    ("deepseek", "base_url", ("deepseek api连接", "deepseek_api_base", "deepseek_base_url")),
    ("deepseek", "model", ("deepseek模型", "deepseek_model", "deepseek model")),
    ("mineru", "token", ("mineru vlm大模型 用于转换md格式key", "mineru_token", "mineru token")),
    ("dify", "api_url", ("dify_api_url", "dify api url")),
    ("dify", "api_key", ("dify_api_key", "dify api key")),
    ("dify", "default_dataset_ids", ("dify_default_dataset_ids", "dify default dataset ids")),
    ("dify", "verify_ssl", ("dify_verify_ssl", "dify verify ssl")),
    ("ragflow", "api_url", ("ragflow_api_url", "ragflow api url")),
    ("ragflow", "api_key", ("ragflow_api_key", "ragflow api key")),
    ("ragflow", "default_dataset_ids", ("ragflow_default_dataset_ids", "ragflow default dataset ids")),
    ("ragflow", "verify_ssl", ("ragflow_verify_ssl", "ragflow verify ssl")),
]

_ENV_FIELD_ALIASES: dict[tuple[str, str], tuple[str, ...]] = {
    ("qwen", "api_key"): ("QWEN_API_KEY",),
    ("qwen", "base_url"): ("QWEN_BASE_URL",),
    ("qwen", "model"): ("QWEN_MODEL",),
    ("deepseek", "api_key"): ("DEEPSEEK_API_KEY",),
    ("deepseek", "base_url"): ("DEEPSEEK_BASE_URL",),
    ("deepseek", "model"): ("DEEPSEEK_MODEL",),
    ("mineru", "token"): ("MINERU_TOKEN",),
    ("dify", "api_url"): ("DIFY_API_URL",),
    ("dify", "api_key"): ("DIFY_API_KEY",),
    ("dify", "default_dataset_ids"): ("DIFY_DEFAULT_DATASET_IDS",),
    ("ragflow", "api_url"): ("RAGFLOW_API_URL",),
    ("ragflow", "api_key"): ("RAGFLOW_API_KEY",),
    ("ragflow", "default_dataset_ids"): ("RAGFLOW_DEFAULT_DATASET_IDS",),
}


def _resolve_config_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("${") and text.endswith("}") and len(text) > 3:
        return os.getenv(text[2:-1].strip(), "").strip()
    return text


def _env_override_value(section: str, field: str) -> str:
    for env_name in _ENV_FIELD_ALIASES.get((section, field), ()):
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    return ""


def _flatten_json(data: dict) -> dict[str, str]:
    flat: dict[str, str] = {}
    for section, field, aliases in _CONFIG_FIELD_ALIASES:
        configured_value = str((data.get(section) or {}).get(field, "") or "")
        value = _env_override_value(section, field) or _resolve_config_value(configured_value)
        if not value:
            continue
        for alias in aliases:
            flat[alias.lower()] = value
    return flat


def _build_env_settings() -> dict[str, str]:
    flat: dict[str, str] = {}
    for section, field, aliases in _CONFIG_FIELD_ALIASES:
        value = _env_override_value(section, field)
        if not value:
            continue
        for alias in aliases:
            flat[alias.lower()] = value
    return flat


def _resolve_default_profile() -> str:
    return os.getenv("KNOWLEDGE_PROFILE", DEFAULT_PROFILE_ID).strip() or DEFAULT_PROFILE_ID


# 配置统一用 JSON profile：`配置文件.<profile>.json`。不再读 legacy txt。
def load_runtime_settings(config_path: Path | None = None) -> dict[str, str]:
    env_settings = _build_env_settings()
    if config_path is not None:
        if config_path.suffix.lower() == ".json" and config_path.exists():
            try:
                file_settings = _flatten_json(json.loads(config_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                return env_settings
            return {**file_settings, **env_settings}
        return env_settings

    profile = _resolve_default_profile()
    candidates = [
        PROJECT_ROOT / f"配置文件.{profile}.json",
        PROJECT_ROOT / "配置文件.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        flat = _flatten_json(data)
        if flat:
            return {**flat, **env_settings}
    return env_settings


def get_runtime_setting(*keys: str, settings: dict[str, str] | None = None) -> str | None:
    resolved_settings = settings or load_runtime_settings()
    for key in keys:
        value = resolved_settings.get(key.lower())
        if value:
            return value
    return None


# ---------------------------------------------------------------------------
# LLM runtime 统一解析（新增：支持 DeepSeek / Qwen 统一接口）
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LLMRuntime:
    """OpenAI 兼容的 LLM runtime 参数三元组。下游 qwen_client 可直接消费。"""
    provider: str      # "deepseek" / "qwen" / ...
    api_key: str
    base_url: str
    model: str

    def is_usable(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


def resolve_llm_runtime(
    *,
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    settings: dict[str, str] | None = None,
    allow_fallback: bool = True,
) -> LLMRuntime:
    """解析 LLM runtime。优先级：
       1) 显式 CLI 参数（api_key/base_url/model）
       2) 配置文件里该 provider 的字段
       3) provider 的默认值（base_url/model 有默认；api_key 必须由用户配置）
       4) allow_fallback=True 时，若主 provider 缺 api_key，回退到任何已配的其它 provider
    """
    resolved_settings = settings if settings is not None else load_runtime_settings()
    primary_spec: LLMProviderSpec = get_provider_spec(provider)

    def _read(section_name: str, field: str) -> str:
        for sect, fld, aliases in _CONFIG_FIELD_ALIASES:
            if sect == section_name and fld == field:
                for alias in aliases:
                    val = resolved_settings.get(alias.lower())
                    if val:
                        return val
                break
        return ""

    def _build(spec: LLMProviderSpec) -> LLMRuntime:
        return LLMRuntime(
            provider=spec.name,
            api_key=(api_key or _read(spec.name, "api_key") or "").strip(),
            base_url=(base_url or _read(spec.name, "base_url") or spec.default_base_url).strip().rstrip("/"),
            model=(model or _read(spec.name, "model") or spec.default_model).strip(),
        )

    runtime = _build(primary_spec)
    if runtime.is_usable():
        return runtime

    if allow_fallback:
        for alt_name, alt_spec in LLM_PROVIDERS.items():
            if alt_name == primary_spec.name:
                continue
            alt_runtime = _build(alt_spec)
            if alt_runtime.is_usable():
                return alt_runtime

    # 仍不可用：返回默认 provider 的占位（api_key 为空），调用方自行判断
    return runtime
