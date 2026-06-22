from __future__ import annotations

import json
import shlex
import subprocess
import urllib.request
from typing import Any


def extract_json_payload(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        parts = candidate.split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{") and cleaned.endswith("}"):
                return json.loads(cleaned)
    if candidate.startswith("{") and candidate.endswith("}"):
        return json.loads(candidate)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(candidate[start : end + 1])
    raise ValueError("AI response did not contain JSON payload")


class DeepSeekProvider:
    def __init__(self, api_base: str, api_key: str, model: str):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str) -> dict[str, Any]:
        content = self.chat(prompt, system_prompt="Return JSON only.")
        return extract_json_payload(content)

    def chat(self, prompt: str, system_prompt: str = "") -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": _build_messages(system_prompt, prompt),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        return str((((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "")


class GeminiCliProvider:
    def __init__(self, command: str = "gemini"):
        self.command = command or "gemini"

    def generate(self, prompt: str) -> dict[str, Any]:
        cmd = shlex.split(self.command) + ["-p", prompt]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(str(exc))
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "Gemini CLI failed").strip())
        return extract_json_payload(completed.stdout or "")


def _build_messages(system_prompt: str, prompt: str) -> list[dict[str, str]]:
    messages = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages
