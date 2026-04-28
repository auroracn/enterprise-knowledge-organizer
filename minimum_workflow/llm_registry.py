"""系统 LLM 模型注册表。

用于：
1. 统一 provider 的可选模型、默认模型、base_url；
2. 默认 provider = deepseek（`deepseek-v4-pro`），历史 qwen 保留可用；
3. runtime_config / cli / pipeline 从此处统一取默认值，避免硬编码。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMProviderSpec:
    name: str
    display_name: str
    default_base_url: str
    default_model: str
    available_models: tuple[str, ...]
    auth_header_style: str = "bearer"  # 预留，当前都是 OpenAI 兼容 Bearer


# DeepSeek V4：`deepseek-v4-pro` 为主力，`deepseek-v4-flash` 轻量 & 便宜。
# 官方 OpenAI 兼容 BASE URL 可带 /v1 也可不带；这里统一用 /v1 便于客户端拼 /chat/completions。
# 老别名 deepseek-chat / deepseek-reasoner 保留给历史调用者。
DEEPSEEK = LLMProviderSpec(
    name="deepseek",
    display_name="DeepSeek V4",
    default_base_url="https://api.deepseek.com/v1",
    default_model="deepseek-v4-pro",
    available_models=(
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-chat",       # 兼容别名 → v4-flash 非思考
        "deepseek-reasoner",   # 兼容别名 → v4-flash 思考
    ),
)

QWEN = LLMProviderSpec(
    name="qwen",
    display_name="通义千问（阿里百炼）",
    default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_model="qwen-plus",
    available_models=(
        "qwen-plus",
        "qwen-max",
        "qwen3.6-plus",
    ),
)


LLM_PROVIDERS: dict[str, LLMProviderSpec] = {
    DEEPSEEK.name: DEEPSEEK,
    QWEN.name: QWEN,
}

# 全局默认 provider。用户改默认时调整此常量。
DEFAULT_LLM_PROVIDER = "deepseek"


def get_provider_spec(name: str | None) -> LLMProviderSpec:
    """按名取 provider；传空/未知时回退默认。"""
    if name and name.lower() in LLM_PROVIDERS:
        return LLM_PROVIDERS[name.lower()]
    return LLM_PROVIDERS[DEFAULT_LLM_PROVIDER]


def list_provider_names() -> list[str]:
    """已注册 provider 名称列表（默认在最前）。"""
    names = [DEFAULT_LLM_PROVIDER]
    for name in LLM_PROVIDERS:
        if name not in names:
            names.append(name)
    return names
