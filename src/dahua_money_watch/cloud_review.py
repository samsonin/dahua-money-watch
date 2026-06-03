from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


HANDOVER_PROMPT = """You are reviewing a short security-camera clip from a shop counter.

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

AMOUNT_PROMPT = """You are reviewing a short security-camera clip that was already flagged as a likely payment handover.

Your task is to estimate the transferred money amount only if the cash/card/phone payment details are visible enough.
Do not guess. If denominations or exact amount are not readable, return amount_status "unknown".
If the amount is partially inferable but uncertain, return amount_status "estimated".
If denominations are clearly readable, return amount_status "confirmed".

Return only valid JSON with these keys:
{
  "amount_status": "confirmed" | "estimated" | "unknown",
  "amount": number | null,
  "currency": "RUB" | "unknown",
  "amount_confidence": number,
  "visible_denominations": [number],
  "cash_count_visible": number | null,
  "evidence": string,
  "recommended_action": "crm_compare" | "manual_review"
}
"""

ESCALATION_PROMPT = """You are doing a second-pass review of a shop counter payment candidate.

The cheap first pass was unsure, so your goal is to reduce manual review.
Use the frames to choose the most useful automatic outcome.

Return crm_compare when a payment and amount are clear enough for accounting comparison.
Return crm_compare_candidate when a payment is likely but the amount is estimated or partially visible.
Return ignore_auto when the scene is not a payment event.
Return manual_review only when the evidence is genuinely too ambiguous.

Return only valid JSON with these keys:
{
  "recommended_action": "ignore_auto" | "crm_compare_candidate" | "crm_compare" | "manual_review",
  "payment_likely": boolean,
  "money_handover_visible": boolean,
  "payment_type": "cash" | "card_or_phone" | "unknown",
  "confidence": number,
  "amount_status": "confirmed" | "estimated" | "unknown",
  "amount": number | null,
  "currency": "RUB" | "unknown",
  "amount_confidence": number,
  "visible_denominations": [number],
  "evidence": string
}
"""


class CloudReviewError(RuntimeError):
    pass


def is_fatal_vertex_permission_error(error: Any) -> bool:
    text = str(error)
    return (
        "PERMISSION_DENIED" in text
        or "CONSUMER_INVALID" in text
        or "Permission denied on resource project" in text
    )


def review_clip_with_vertex(
    clip_path: Path,
    project_id: str,
    location: str,
    model: str,
    prompt: str = HANDOVER_PROMPT,
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
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
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


def two_stage_money_review(
    clip_path: Path,
    project_id: str,
    location: str,
    model: str,
    frame_dir: Optional[Path] = None,
    timeout_seconds: int = 120,
    escalation_model: Optional[str] = None,
) -> Dict[str, Any]:
    handover = review_clip_with_vertex(
        clip_path,
        project_id,
        location,
        model,
        HANDOVER_PROMPT,
        timeout_seconds,
    )
    handover_response = handover.get("response", {})
    should_estimate_amount = (
        handover_response.get("payment_likely") is True
        or handover_response.get("money_handover_visible") is True
        or handover_response.get("recommended_action") == "likely_payment"
    )
    amount: Optional[Dict[str, Any]] = None
    if should_estimate_amount:
        amount = review_amount_from_frames_with_vertex(
            clip_path,
            project_id,
            location,
            model,
            frame_dir,
            timeout_seconds,
        )
    event = _money_event(clip_path, handover_response, amount["response"] if amount else None)
    escalation: Optional[Dict[str, Any]] = None
    if escalation_model and event.get("recommended_action") == "manual_review":
        escalation = review_escalation_from_frames_with_vertex(
            clip_path,
            project_id,
            location,
            escalation_model,
            frame_dir,
            timeout_seconds,
        )
        event = apply_escalation_event(event, escalation["response"])
    return {
        "clip": str(clip_path),
        "model": model,
        "location": location,
        "stage": "two_stage",
        "handover": handover,
        "amount": amount,
        "escalation": escalation,
        "event": event,
        "usage_metadata": {
            "handover": handover.get("usage_metadata", {}),
            "amount": (amount or {}).get("usage_metadata", {}),
            "escalation": (escalation or {}).get("usage_metadata", {}),
        },
    }


def review_amount_from_frames_with_vertex(
    clip_path: Path,
    project_id: str,
    location: str,
    model: str,
    frame_dir: Optional[Path] = None,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    cleanup = None
    if frame_dir is None:
        cleanup = tempfile.TemporaryDirectory()
        target_dir = Path(cleanup.name)
    else:
        target_dir = frame_dir
    try:
        frame_paths = extract_amount_frames(clip_path, target_dir)
        response = review_frames_with_vertex(frame_paths, project_id, location, model, AMOUNT_PROMPT, timeout_seconds)
        response["clip"] = str(clip_path)
        response["frames"] = [str(path) for path in frame_paths]
        return response
    finally:
        if cleanup is not None:
            cleanup.cleanup()


def review_escalation_from_frames_with_vertex(
    clip_path: Path,
    project_id: str,
    location: str,
    model: str,
    frame_dir: Optional[Path] = None,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    cleanup = None
    if frame_dir is None:
        cleanup = tempfile.TemporaryDirectory()
        target_dir = Path(cleanup.name)
    else:
        target_dir = frame_dir
    try:
        frame_paths = extract_amount_frames(clip_path, target_dir)
        response = review_frames_with_vertex(frame_paths, project_id, location, model, ESCALATION_PROMPT, timeout_seconds)
        response["clip"] = str(clip_path)
        response["frames"] = [str(path) for path in frame_paths]
        return response
    finally:
        if cleanup is not None:
            cleanup.cleanup()


def review_frames_with_vertex(
    frame_paths: List[Path],
    project_id: str,
    location: str,
    model: str,
    prompt: str,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = []
    for frame_path in frame_paths:
        parts.append(
            {
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": base64.b64encode(frame_path.read_bytes()).decode("ascii"),
                }
            }
        )
    parts.append({"text": prompt})
    payload = {
        "contents": [{"role": "USER", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
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
        "clip": "",
        "model": model,
        "location": location,
        "response": parsed,
        "raw_text": text,
        "usage_metadata": response.get("usageMetadata", {}),
    }


def extract_amount_frames(clip_path: Path, frame_dir: Path) -> List[Path]:
    frame_dir.mkdir(parents=True, exist_ok=True)
    duration = _clip_duration(clip_path)
    if duration <= 0:
        offsets = [0.0]
    else:
        offsets = [duration * ratio for ratio in (0.35, 0.45, 0.55, 0.65, 0.75)]
    safe_stem = re.sub(r"[^0-9A-Za-z_.-]+", "_", clip_path.stem)
    frames: List[Path] = []
    for index, offset in enumerate(offsets, 1):
        target = frame_dir / f"{safe_stem}_{index:02d}.jpg"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{max(0.0, offset):.3f}",
            "-i",
            str(clip_path),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(target),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if target.exists() and target.stat().st_size > 0:
            frames.append(target)
    if not frames:
        raise CloudReviewError(f"Could not extract amount frames from {clip_path}")
    return frames


def _clip_duration(clip_path: Path) -> float:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(clip_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return float(proc.stdout.strip())
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError):
        return 0.0


def _money_event(
    clip_path: Path,
    handover: Dict[str, Any],
    amount: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    amount_status = (amount or {}).get("amount_status", "unknown")
    action = "ignore"
    if handover.get("recommended_action") == "likely_payment":
        action = "manual_review" if amount_status == "unknown" else "crm_compare"
    elif handover.get("recommended_action") == "manual_review":
        action = "manual_review"
    return {
        "clip": str(clip_path),
        "payment_likely": bool(handover.get("payment_likely", False)),
        "money_handover_visible": bool(handover.get("money_handover_visible", False)),
        "payment_type": _payment_type(handover),
        "handover_confidence": float(handover.get("confidence") or 0.0),
        "amount_status": amount_status,
        "amount": (amount or {}).get("amount"),
        "currency": (amount or {}).get("currency", "unknown"),
        "amount_confidence": float((amount or {}).get("amount_confidence") or 0.0),
        "visible_denominations": (amount or {}).get("visible_denominations", []),
        "evidence": {
            "handover": handover.get("evidence", ""),
            "amount": (amount or {}).get("evidence", ""),
            "timestamp_hint": handover.get("timestamp_hint", ""),
        },
        "recommended_action": action,
    }


def _payment_type(handover: Dict[str, Any]) -> str:
    if handover.get("cash_visible"):
        return "cash"
    if handover.get("card_or_phone_payment"):
        return "card_or_phone"
    return "unknown"


def apply_escalation_event(event: Dict[str, Any], escalation: Dict[str, Any]) -> Dict[str, Any]:
    action = str(escalation.get("recommended_action") or "manual_review")
    normalized_action = "ignore" if action == "ignore_auto" else action
    if normalized_action not in {"ignore", "manual_review", "crm_compare_candidate", "crm_compare"}:
        normalized_action = "manual_review"

    merged = dict(event)
    merged["recommended_action"] = normalized_action
    merged["payment_likely"] = bool(escalation.get("payment_likely", normalized_action != "ignore"))
    merged["money_handover_visible"] = bool(escalation.get("money_handover_visible", normalized_action != "ignore"))
    merged["payment_type"] = str(escalation.get("payment_type") or merged.get("payment_type") or "unknown")
    merged["amount_status"] = str(escalation.get("amount_status") or merged.get("amount_status") or "unknown")
    merged["amount"] = escalation.get("amount", merged.get("amount"))
    merged["currency"] = str(escalation.get("currency") or merged.get("currency") or "unknown")
    merged["amount_confidence"] = float(escalation.get("amount_confidence") or merged.get("amount_confidence") or 0.0)
    merged["visible_denominations"] = escalation.get("visible_denominations") or merged.get("visible_denominations") or []
    merged["escalation_confidence"] = float(escalation.get("confidence") or 0.0)
    evidence = dict(merged.get("evidence") or {})
    evidence["escalation"] = str(escalation.get("evidence") or "")
    merged["evidence"] = evidence
    return merged


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
    service_account_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if service_account_file:
        return _service_account_access_token(service_account_file)
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


def _service_account_access_token(service_account_file: str) -> str:
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise CloudReviewError("google-auth is required when GOOGLE_APPLICATION_CREDENTIALS is used.") from exc
    credentials, _project_id = google.auth.load_credentials_from_file(
        service_account_file,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    credentials.refresh(Request())
    if not credentials.token:
        raise CloudReviewError("Service account credentials did not return an access token.")
    return str(credentials.token)


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
