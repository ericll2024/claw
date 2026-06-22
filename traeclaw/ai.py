from __future__ import annotations

from typing import Any

from .db import AppDatabase, mask_secret
from .ai_provider import DeepSeekProvider


class AiSettings:
    @staticmethod
    def save(db: AppDatabase, payload: dict[str, Any]) -> None:
        db.set_setting("ai.enabled", "1" if payload.get("enabled") else "0")
        db.set_setting(
            "ai.default_provider",
            str(payload.get("default_provider") or "deepseek").strip() or "deepseek",
        )
        db.set_setting("ai.deepseek.api_base", str(payload.get("deepseek_api_base") or "").strip())
        api_key = str(payload.get("deepseek_api_key") or "").strip()
        if api_key:
            db.set_setting("ai.deepseek.api_key", api_key, is_secret=True)
        db.set_setting(
            "ai.deepseek.model",
            str(payload.get("deepseek_model") or "deepseek-chat").strip() or "deepseek-chat",
        )
        db.set_setting("ai.gemini_cli_enabled", "1" if payload.get("gemini_cli_enabled") else "0")
        db.set_setting(
            "ai.gemini_cli_command",
            str(payload.get("gemini_cli_command") or "gemini").strip() or "gemini",
        )

    @staticmethod
    def load_private(db: AppDatabase) -> dict[str, Any]:
        api_key = db.get_setting("ai.deepseek.api_key", "")
        return {
            "enabled": db.get_setting("ai.enabled", "0") == "1",
            "default_provider": db.get_setting("ai.default_provider", "deepseek") or "deepseek",
            "deepseek_api_base": db.get_setting("ai.deepseek.api_base", ""),
            "deepseek_api_key": api_key,
            "deepseek_api_key_configured": bool(api_key),
            "deepseek_model": db.get_setting("ai.deepseek.model", "deepseek-chat") or "deepseek-chat",
            "gemini_cli_enabled": db.get_setting("ai.gemini_cli_enabled", "0") == "1",
            "gemini_cli_command": db.get_setting("ai.gemini_cli_command", "gemini") or "gemini",
        }

    @staticmethod
    def load_public(db: AppDatabase) -> dict[str, Any]:
        private = AiSettings.load_private(db)
        return {
            "enabled": private["enabled"],
            "default_provider": private["default_provider"],
            "deepseek_api_base": private["deepseek_api_base"],
            "deepseek_api_key": mask_secret(private["deepseek_api_key"]),
            "deepseek_api_key_configured": private["deepseek_api_key_configured"],
            "deepseek_model": private["deepseek_model"],
            "gemini_cli_enabled": private["gemini_cli_enabled"],
            "gemini_cli_command": private["gemini_cli_command"],
        }


def test_deepseek_settings(db: AppDatabase, payload: dict[str, Any]) -> dict[str, Any]:
    saved = AiSettings.load_private(db)
    api_base = str(payload.get("deepseek_api_base") or "").strip() or saved["deepseek_api_base"]
    api_key = str(payload.get("deepseek_api_key") or "").strip() or saved["deepseek_api_key"]
    model = str(payload.get("deepseek_model") or "").strip() or saved["deepseek_model"]
    if not api_base:
        raise ValueError("请先填写 DeepSeek API Base")
    if not api_key:
        raise ValueError("请先填写 DeepSeek API Key")
    if not model:
        raise ValueError("请先填写 DeepSeek Model")

    provider = DeepSeekProvider(api_base=api_base, api_key=api_key, model=model)
    reply = provider.chat("hi")
    return {
        "ok": True,
        "provider": "deepseek",
        "model": model,
        "reply": reply.strip(),
    }
