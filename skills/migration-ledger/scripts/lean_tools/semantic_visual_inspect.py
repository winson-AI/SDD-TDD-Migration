"""Read-only primitives extracted from the user supplied Lean bundle.

No standalone CLI, default output directory, config lookup, retries, or workflow authority.
Managed lean_visual_worker owns configuration, execution bounds, paths and status.
"""
from __future__ import annotations
import base64
import json
import mimetypes
from pathlib import Path
import re
from typing import Any
import urllib.request

def image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{data}"


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def build_prompt(visual_id: str, score: dict[str, Any]) -> str:
    score_summary = {
        "status": score.get("status"),
        "reference_size": score.get("reference_size"),
        "candidate_size": score.get("candidate_size"),
        "normalized_size": score.get("normalized_size"),
        "ignored_top_px": score.get("ignored_top_px"),
        "metrics": score.get("metrics"),
    }
    return (
        "You are inspecting Android-to-KMP UI visual parity. "
        "Use the two screenshots and deterministic score evidence to select semantic, actionable UI issues.\n\n"
        f"visual_id: {visual_id}\n"
        f"score evidence:\n{json.dumps(score_summary, ensure_ascii=False, indent=2)}\n\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Output zero, one, or two issues; never more than two.\n"
        "- Ignore phone status indicators such as time, signal, Wi-Fi, battery, and simulator chrome.\n"
        "- Treat small uniform scale/resolution differences as acceptable unless they cause clipping, overlap, wrong anchors, unreadable text, or materially different visible content.\n"
        "- Do not report pure pixel noise, antialiasing, or dynamic remote image content when layout/crop is correct.\n"
        "- Prefer root-cause issues over symptoms.\n\n"
        "Required JSON schema:\n"
        "{\n"
        '  "status": "COMPLETE",\n'
        '  "visual_id": "<id>",\n'
        '  "overall": 0-100,\n'
        '  "comparability": 0.0-1.0,\n'
        '  "issues": [\n'
        "    {\n"
        '      "area": "named UI region",\n'
        '      "problem": "engineering defect",\n'
        '      "likely_code_area": "component/modifier/state owner to inspect",\n'
        '      "severity": "low|medium|high|critical",\n'
        '      "evidence": "reference/candidate screenshots plus score artifacts"\n'
        "    }\n"
        "  ]\n"
        "}"
    )


def call_model(model: dict[str, Any], visual_id: str, reference: Path, candidate: Path, score: dict[str, Any], timeout: int) -> dict[str, Any]:
    request_payload = {
        "model": model["name"],
        "temperature": float(model.get("temperature", 0.1)),
        "max_tokens": int(model.get("max_tokens", 4096)),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_prompt(visual_id, score)},
                    {"type": "text", "text": "Reference Android screenshot:"},
                    {"type": "image_url", "image_url": {"url": image_data_url(reference)}},
                    {"type": "text", "text": "Candidate KMP screenshot:"},
                    {"type": "image_url", "image_url": {"url": image_data_url(candidate)}},
                ],
            }
        ],
    }
    data = json.dumps(request_payload).encode("utf-8")
    request = urllib.request.Request(
        chat_completions_url(str(model["base_url"])),
        data=data,
        headers={
            "Authorization": f"Bearer {model['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # The parent process also enforces a wall-clock deadline; socket timeout alone
        # does not bound a provider that continuously streams a slow response.
        body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ValueError("visual model response exceeds 2 MiB")
        response_payload = json.loads(body.decode("utf-8"))
    content = response_payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return extract_json(str(content))


def normalize_result(raw: dict[str, Any], visual_id: str, model: dict[str, Any]) -> dict[str, Any]:
    issues = raw.get("issues") if isinstance(raw.get("issues"), list) else []
    safe_issues = []
    for issue in issues[:2]:
        if not isinstance(issue, dict):
            continue
        safe_issues.append(
            {
                "area": str(issue.get("area") or ""),
                "problem": str(issue.get("problem") or ""),
                "likely_code_area": str(issue.get("likely_code_area") or ""),
                "severity": str(issue.get("severity") or "medium"),
                "evidence": str(issue.get("evidence") or ""),
            }
        )
    return {
        "status": "COMPLETE",
        "visual_id": str(raw.get("visual_id") or visual_id),
        "model": {
            "provider": model.get("provider") or "",
            "name": model.get("name") or "",
            "base_url": model.get("base_url") or "",
        },
        "overall": raw.get("overall"),
        "comparability": raw.get("comparability"),
        "issues": safe_issues,
    }
