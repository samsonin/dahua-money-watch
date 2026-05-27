from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_PROMPT = """You are reviewing a short security-camera clip from a shop counter.

Decide whether the clip shows a likely payment or money handover event.
Look for visible cash, bank card, phone payment, receipt exchange, or hands meeting over the counter.
Be conservative: if the evidence is weak, mark it for manual_review instead of likely_payment.

Return only valid JSON with these keys:
{
  "money_handover_visible": boolean,
  "payment_likely": boolean,
  "confidence": number,
  "cash_visible": boolean,
  "card_or_phone_payment": boolean,
  "hands_near_counter": boolean,
  "evidence": string,
  "timestamp_hint": string,
  "recommended_action": "ignore" | "manual_review" | "likely_payment"
}
"""


class CloudReviewError(RuntimeError):
    pass


def review_clip_with_vertex(
    clip_path: Path,
    project_id: str,
    location: str,
    model: str,
    prompt: str = DEFAULT_PROMPT,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    data = clip_path.read_bytes()
    payload = {
        "contents": [
            {
                "role": "USER",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "video/mp4",
                            "data": base64.b64encode(data).decode("ascii"),
                        }
                    },
                    {"text": prompt},
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
        },
    }
    url = (
        f"https://aiplatform.googleapis.com/v1/projects/{project_id}"
        f"/locations/{location}/publishers/google/models/{model}:generateContent"
    )
    response = _post_json(url, payload, _access_token(), timeout_seconds)
    text = _response_text(response)
    parsed = _parse_json_text(text)
    return {
        "clip": str(clip_path),
        "model": model,
        "location": location,
        "response": parsed,
        "raw_text": text,
        "usage_metadata": response.get("usageMetadata", {}),
    }


def default_gcloud_project() -> Optional[str]:
    try:
        proc = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    value = proc.stdout.strip()
    if not value or value == "(unset)":
        return None
    return value


def _access_token() -> str:
    env_token = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN")
    if env_token:
        return env_token
    try:
        proc = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise CloudReviewError(
            "Google access token is unavailable. Run `gcloud auth login` "
            "or set GOOGLE_OAUTH_ACCESS_TOKEN."
        ) from exc
    token = proc.stdout.strip()
    if not token:
        raise CloudReviewError("Google access token command returned an empty token.")
    return token


def _post_json(url: str, payload: Dict[str, Any], token: str, timeout_seconds: int) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise CloudReviewError(f"Vertex AI request failed with HTTP {exc.code}: {detail}") from exc


def _response_text(response: Dict[str, Any]) -> str:
    candidates = response.get("candidates") or []
    parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
    text = "".join(str(part.get("text", "")) for part in parts).strip()
    if not text:
        raise CloudReviewError(f"Vertex AI response did not contain text: {response}")
    return text


def _parse_json_text(text: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise CloudReviewError(f"Model response is not JSON: {text}")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise CloudReviewError(f"Model response JSON must be an object: {parsed}")
    return parsed
