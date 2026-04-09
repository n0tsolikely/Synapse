"""Provider seam for model-backed continuity observation."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib import error as urllib_error
from urllib import request as urllib_request

from jsonschema import Draft202012Validator, ValidationError


class ContinuityModelAdapterError(RuntimeError):
    """Raised when the continuity observer backend cannot be invoked safely."""


DEFAULT_CONTINUITY_OBSERVER_BACKEND = "noop"
SUPPORTED_CONTINUITY_OBSERVER_BACKENDS = {
    "noop",
    "fixture",
    "openai_responses",
    "gemini_generate_content",
}
SELECTABLE_CONTINUITY_OBSERVER_BACKENDS = {
    "noop",
    "openai_responses",
    "gemini_generate_content",
}
CONTINUITY_OBSERVER_PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    "openai_responses": {
        "label": "OpenAI Responses",
        "credential_env_vars": ("OPENAI_API_KEY",),
    },
    "gemini_generate_content": {
        "label": "Gemini GenerateContent",
        "credential_env_vars": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    },
}
DEFAULT_OPENAI_RESPONSES_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_RESPONSES_TIMEOUT_SECONDS = 30
DEFAULT_GEMINI_GENERATE_CONTENT_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_GENERATE_CONTENT_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_GENERATE_CONTENT_TIMEOUT_SECONDS = 30
CONTINUITY_OBSERVER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "observer_status": {
            "type": "string",
            "enum": ["ok", "degraded"],
        },
        "provider_status": {
            "type": "string",
            "minLength": 1,
        },
        "degraded": {
            "type": "boolean",
        },
        "degraded_reason": {
            "type": ["string", "null"],
        },
        "rationale": {
            "type": "string",
            "minLength": 1,
        },
        "intents": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "artifact_family": {
                        "type": "string",
                        "enum": [
                            "noop",
                            "semantic_capture",
                            "decision_log",
                            "disclosure_log",
                            "open_obligation",
                        ],
                    },
                    "action_type": {
                        "type": "string",
                        "enum": ["create", "update", "noop"],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "rationale": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "source_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "kind": {"type": "string"},
                                "id": {"type": "string"},
                                "path": {"type": "string"},
                            },
                            "required": [],
                        },
                    },
                    "truth_state_label": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "uncertainty_markers": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                    },
                    "draft_safe": {
                        "type": "boolean",
                    },
                    "gated_publication": {
                        "type": "boolean",
                    },
                    "supersedes": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                    },
                    "updates": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                    },
                    "payload": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "why": {"type": "string"},
                            "raw_text": {"type": "string"},
                            "trigger": {"type": "string"},
                            "expected": {"type": "string"},
                            "provable": {"type": "string"},
                            "impact": {"type": "string"},
                            "decision_needed": {"type": "string"},
                            "run_id": {"type": "string"},
                            "session_id": {"type": "string"},
                            "changed_files": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "captures": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "kind": {"type": "string"},
                                        "summary": {"type": "string"},
                                    },
                                    "required": ["kind", "summary"],
                                },
                            },
                            "status_labels": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "safe_options": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [],
                    },
                },
                "required": [
                    "artifact_family",
                    "action_type",
                    "confidence",
                    "rationale",
                    "source_refs",
                    "truth_state_label",
                    "uncertainty_markers",
                    "draft_safe",
                    "gated_publication",
                    "supersedes",
                    "updates",
                    "payload",
                ],
            },
        },
    },
    "required": [
        "observer_status",
        "provider_status",
        "degraded",
        "degraded_reason",
        "rationale",
        "intents",
    ],
}


def configured_continuity_observer_backend(explicit_backend: str | None = None) -> str:
    backend = str(explicit_backend or os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_BACKEND") or DEFAULT_CONTINUITY_OBSERVER_BACKEND).strip().lower()
    return backend or DEFAULT_CONTINUITY_OBSERVER_BACKEND


def continuity_observer_provider_options(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    env_map = dict(env or os.environ)
    options: list[dict[str, Any]] = []
    for backend, spec in CONTINUITY_OBSERVER_PROVIDER_SPECS.items():
        credential_env_vars = [str(item) for item in spec.get("credential_env_vars") or [] if str(item).strip()]
        matched_env_vars = [name for name in credential_env_vars if str(env_map.get(name) or "").strip()]
        options.append(
            {
                "backend": backend,
                "label": str(spec.get("label") or backend),
                "credential_env_vars": credential_env_vars,
                "available": bool(matched_env_vars),
                "matched_env_vars": matched_env_vars,
            }
        )
    return options


def invoke_continuity_observer_backend(*, packet: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    selected = configured_continuity_observer_backend(backend)
    if selected == "noop":
        return {
            "observer_status": "degraded",
            "backend": "noop",
            "provider_status": "not_configured",
            "degraded": True,
            "degraded_reason": "observer_backend_not_configured",
            "rationale": "No continuity-observer backend is configured for this runtime.",
            "intents": [],
        }
    if selected == "fixture":
        return _fixture_backend_response(packet)
    if selected == "openai_responses":
        return _openai_responses_backend(packet)
    if selected == "gemini_generate_content":
        return _gemini_generate_content_backend(packet)
    return {
        "observer_status": "degraded",
        "backend": selected,
        "provider_status": "unsupported_backend",
        "degraded": True,
        "degraded_reason": f"unsupported_backend:{selected}",
        "rationale": "Configured continuity-observer backend is not supported by this runtime build.",
        "intents": [],
    }


def _fixture_backend_response(packet: dict[str, Any]) -> dict[str, Any]:
    raw_fixture = str(os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_FIXTURE_JSON") or "").strip()
    if raw_fixture:
        try:
            payload = json.loads(raw_fixture)
        except json.JSONDecodeError as exc:
            raise ContinuityModelAdapterError("SYNAPSE_CONTINUITY_OBSERVER_FIXTURE_JSON is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ContinuityModelAdapterError("SYNAPSE_CONTINUITY_OBSERVER_FIXTURE_JSON must decode to an object.")
        return {
            "observer_status": str(payload.get("observer_status") or "ok").strip().lower() or "ok",
            "backend": "fixture",
            "provider_status": str(payload.get("provider_status") or "fixture").strip() or "fixture",
            "degraded": bool(payload.get("degraded", False)),
            "degraded_reason": str(payload.get("degraded_reason") or "").strip() or None,
            "rationale": str(payload.get("rationale") or "Deterministic continuity observer fixture response.").strip(),
            "intents": list(payload.get("intents") or []),
        }

    summary = str(packet.get("summary") or "").strip()
    notes = [str(item).strip() for item in list(packet.get("notes") or []) if str(item).strip()]
    source_refs = [dict(item) for item in list(packet.get("source_refs") or []) if isinstance(item, dict)]
    intents: list[dict[str, Any]] = []
    if summary or notes:
        captures: list[dict[str, Any]] = []
        if summary:
            captures.append({"kind": "repo_fact", "summary": summary})
        captures.extend({"kind": "repo_fact", "summary": note} for note in notes[:3])
        intents.append(
            {
                "artifact_family": "semantic_capture",
                "action_type": "create",
                "confidence": "medium",
                "rationale": "Fixture backend captured the bounded continuity packet into a draft-safe semantic capture.",
                "source_refs": source_refs,
                "truth_state_label": "working_capture",
                "uncertainty_markers": [],
                "draft_safe": True,
                "gated_publication": False,
                "supersedes": [],
                "updates": [],
                "payload": {
                    "title": summary or f"{packet.get('trigger') or 'continuity'} continuity update",
                    "captures": captures,
                    "raw_text": "\n".join([summary, *notes]).strip(),
                },
            }
        )
    if bool(packet.get("decision_boundary")):
        title = summary or "Observer decision boundary"
        intents.append(
            {
                "artifact_family": "decision_log",
                "action_type": "create",
                "confidence": "medium",
                "rationale": "Fixture backend observed an explicit decision boundary in the bounded continuity packet.",
                "source_refs": source_refs,
                "truth_state_label": "decision_draft",
                "uncertainty_markers": [],
                "draft_safe": True,
                "gated_publication": False,
                "supersedes": [],
                "updates": [],
                "payload": {
                    "title": title,
                    "summary": summary or title,
                    "why": "Deterministic fixture observer promoted the explicit decision boundary into the decision ledger.",
                },
            }
        )
    if bool(packet.get("uncertainty_present")):
        trigger = summary or (notes[0] if notes else "Continuity observer surfaced uncertainty.")
        intents.append(
            {
                "artifact_family": "disclosure_log",
                "action_type": "create",
                "confidence": "medium",
                "rationale": "Fixture backend observed unresolved uncertainty in the bounded continuity packet.",
                "source_refs": source_refs,
                "truth_state_label": "uncertainty_disclosure",
                "uncertainty_markers": ["uncertainty_present"],
                "draft_safe": True,
                "gated_publication": False,
                "supersedes": [],
                "updates": [],
                "payload": {
                    "trigger": trigger,
                    "expected": "Continuity should remain truthful while the uncertain condition is unresolved.",
                    "provable": "The bounded continuity packet marked uncertainty_present=true.",
                    "status_labels": ["UNCERTAINTY", "RISK"],
                    "impact": trigger,
                    "safe_options": [
                        "Continue draft-safe continuity updates only.",
                        "Clarify the uncertain condition before stronger canon changes.",
                    ],
                    "decision_needed": "Confirm whether the executor should continue, pause, or capture more evidence.",
                },
            }
        )
    return {
        "observer_status": "ok",
        "backend": "fixture",
        "provider_status": "fixture",
        "degraded": False,
        "degraded_reason": None,
        "rationale": "Deterministic fixture observer derived draft-safe intents from the bounded continuity packet.",
        "intents": intents,
    }


def _openai_responses_backend(packet: dict[str, Any]) -> dict[str, Any]:
    api_key = str(os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": "not_configured",
            "degraded": True,
            "degraded_reason": "missing_openai_api_key",
            "rationale": "OPENAI_API_KEY is not configured for the openai_responses continuity backend.",
            "intents": [],
        }

    request_payload = _openai_responses_request_payload(packet)
    request_body = json.dumps(request_payload).encode("utf-8")
    request = urllib_request.Request(
        url=str(os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_BASE_URL") or DEFAULT_OPENAI_RESPONSES_URL),
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    timeout_raw = str(os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_TIMEOUT_SECONDS") or "").strip()
    timeout = DEFAULT_OPENAI_RESPONSES_TIMEOUT_SECONDS
    if timeout_raw:
        try:
            timeout = max(1, int(timeout_raw))
        except ValueError:
            timeout = DEFAULT_OPENAI_RESPONSES_TIMEOUT_SECONDS

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            response_text = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": f"http_error:{exc.code}",
            "degraded": True,
            "degraded_reason": "openai_http_error",
            "rationale": body or f"OpenAI Responses API returned HTTP {exc.code}.",
            "intents": [],
        }
    except urllib_error.URLError as exc:
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": "network_error",
            "degraded": True,
            "degraded_reason": "openai_network_error",
            "rationale": str(exc.reason or exc),
            "intents": [],
        }

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": "invalid_api_response",
            "degraded": True,
            "degraded_reason": "openai_invalid_json",
            "rationale": f"OpenAI Responses API returned invalid JSON: {exc}",
            "intents": [],
        }

    if not isinstance(payload, dict):
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": "invalid_api_response",
            "degraded": True,
            "degraded_reason": "openai_invalid_payload",
            "rationale": "OpenAI Responses API returned a non-object payload.",
            "intents": [],
        }

    refusal = _extract_openai_refusal(payload)
    if refusal:
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": "refusal",
            "degraded": True,
            "degraded_reason": "openai_refusal",
            "rationale": refusal,
            "intents": [],
        }

    if str(payload.get("status") or "").strip().lower() != "completed":
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": str(payload.get("status") or "incomplete").strip().lower() or "incomplete",
            "degraded": True,
            "degraded_reason": "openai_incomplete_response",
            "rationale": json.dumps(payload.get("incomplete_details") or payload.get("error") or {}, sort_keys=True) or "OpenAI response did not complete.",
            "intents": [],
        }

    raw_output = _extract_openai_output_text(payload)
    if not raw_output:
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": "missing_output_text",
            "degraded": True,
            "degraded_reason": "openai_missing_output_text",
            "rationale": "OpenAI Responses API did not return output_text content.",
            "intents": [],
        }

    try:
        parsed_output = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": "invalid_backend_json",
            "degraded": True,
            "degraded_reason": "openai_backend_output_not_json",
            "rationale": f"OpenAI backend output was not valid JSON: {exc}",
            "intents": [],
        }

    coerced_output = _coerce_model_backend_output(parsed_output)

    try:
        Draft202012Validator(CONTINUITY_OBSERVER_RESPONSE_SCHEMA).validate(coerced_output)
    except ValidationError as exc:
        return {
            "observer_status": "degraded",
            "backend": "openai_responses",
            "provider_status": "schema_mismatch",
            "degraded": True,
            "degraded_reason": "openai_backend_output_schema_mismatch",
            "rationale": f"OpenAI backend output did not match the required schema: {exc.message}",
            "intents": [],
        }

    normalized = dict(coerced_output)
    normalized["backend"] = "openai_responses"
    return normalized


def _gemini_generate_content_backend(packet: dict[str, Any]) -> dict[str, Any]:
    api_key, matched_env_var = _gemini_api_key()
    if not api_key:
        return {
            "observer_status": "degraded",
            "backend": "gemini_generate_content",
            "provider_status": "not_configured",
            "degraded": True,
            "degraded_reason": "missing_gemini_api_key",
            "rationale": "Neither GEMINI_API_KEY nor GOOGLE_API_KEY is configured for the gemini_generate_content continuity backend.",
            "intents": [],
        }

    request_payload = _gemini_generate_content_request_payload(packet)
    request_body = json.dumps(request_payload).encode("utf-8")
    model = str(
        os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_GEMINI_MODEL")
        or os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_MODEL")
        or DEFAULT_GEMINI_GENERATE_CONTENT_MODEL
    ).strip() or DEFAULT_GEMINI_GENERATE_CONTENT_MODEL
    base_url = str(os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_GEMINI_BASE_URL") or "").strip()
    request_url = base_url or DEFAULT_GEMINI_GENERATE_CONTENT_URL_TEMPLATE.format(model=model)
    request = urllib_request.Request(
        url=request_url,
        data=request_body,
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    timeout_raw = str(
        os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_GEMINI_TIMEOUT_SECONDS")
        or os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_TIMEOUT_SECONDS")
        or ""
    ).strip()
    timeout = DEFAULT_GEMINI_GENERATE_CONTENT_TIMEOUT_SECONDS
    if timeout_raw:
        try:
            timeout = max(1, int(timeout_raw))
        except ValueError:
            timeout = DEFAULT_GEMINI_GENERATE_CONTENT_TIMEOUT_SECONDS

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            response_text = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        return {
            "observer_status": "degraded",
            "backend": "gemini_generate_content",
            "provider_status": f"http_error:{exc.code}",
            "degraded": True,
            "degraded_reason": "gemini_http_error",
            "rationale": body or f"Gemini GenerateContent returned HTTP {exc.code}.",
            "intents": [],
        }
    except urllib_error.URLError as exc:
        return {
            "observer_status": "degraded",
            "backend": "gemini_generate_content",
            "provider_status": "network_error",
            "degraded": True,
            "degraded_reason": "gemini_network_error",
            "rationale": str(exc.reason or exc),
            "intents": [],
        }

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        return {
            "observer_status": "degraded",
            "backend": "gemini_generate_content",
            "provider_status": "invalid_api_response",
            "degraded": True,
            "degraded_reason": "gemini_invalid_json",
            "rationale": f"Gemini GenerateContent returned invalid JSON: {exc}",
            "intents": [],
        }

    if not isinstance(payload, dict):
        return {
            "observer_status": "degraded",
            "backend": "gemini_generate_content",
            "provider_status": "invalid_api_response",
            "degraded": True,
            "degraded_reason": "gemini_invalid_payload",
            "rationale": "Gemini GenerateContent returned a non-object payload.",
            "intents": [],
        }

    block_reason = str(((payload.get("promptFeedback") or {}).get("blockReason")) or "").strip()
    if block_reason:
        return {
            "observer_status": "degraded",
            "backend": "gemini_generate_content",
            "provider_status": "prompt_blocked",
            "degraded": True,
            "degraded_reason": "gemini_prompt_blocked",
            "rationale": block_reason,
            "intents": [],
        }

    raw_output = _extract_gemini_output_text(payload)
    if not raw_output:
        finish_reason = _extract_gemini_finish_reason(payload)
        return {
            "observer_status": "degraded",
            "backend": "gemini_generate_content",
            "provider_status": finish_reason or "missing_output_text",
            "degraded": True,
            "degraded_reason": "gemini_missing_output_text",
            "rationale": finish_reason or "Gemini GenerateContent did not return text content.",
            "intents": [],
        }

    try:
        parsed_output = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        return {
            "observer_status": "degraded",
            "backend": "gemini_generate_content",
            "provider_status": "invalid_backend_json",
            "degraded": True,
            "degraded_reason": "gemini_backend_output_not_json",
            "rationale": f"Gemini backend output was not valid JSON: {exc}",
            "intents": [],
        }

    coerced_output = _coerce_model_backend_output(parsed_output)
    try:
        Draft202012Validator(CONTINUITY_OBSERVER_RESPONSE_SCHEMA).validate(coerced_output)
    except ValidationError as exc:
        return {
            "observer_status": "degraded",
            "backend": "gemini_generate_content",
            "provider_status": "schema_mismatch",
            "degraded": True,
            "degraded_reason": "gemini_backend_output_schema_mismatch",
            "rationale": f"Gemini backend output did not match the required schema: {exc.message}",
            "intents": [],
        }

    normalized = dict(coerced_output)
    normalized["backend"] = "gemini_generate_content"
    normalized["provider_status"] = str(normalized.get("provider_status") or "ok").strip() or "ok"
    if matched_env_var:
        normalized["provider_credential_env"] = matched_env_var
    return normalized


def _openai_responses_request_payload(packet: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator.check_schema(CONTINUITY_OBSERVER_RESPONSE_SCHEMA)
    packet_json = json.dumps(packet, indent=2, sort_keys=True)
    model = str(os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_MODEL") or DEFAULT_OPENAI_RESPONSES_MODEL).strip()
    max_output_tokens_raw = str(os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_MAX_OUTPUT_TOKENS") or "").strip()
    max_output_tokens = 1400
    if max_output_tokens_raw:
        try:
            max_output_tokens = max(256, int(max_output_tokens_raw))
        except ValueError:
            max_output_tokens = 1400
    return {
        "model": model or DEFAULT_OPENAI_RESPONSES_MODEL,
        "store": False,
        "max_output_tokens": max_output_tokens,
        "input": [
            {
                "role": "system",
                "content": _continuity_observer_system_prompt(),
            },
            {
                "role": "user",
                "content": (
                    "Return JSON only. Evaluate this bounded Synapse continuity packet and produce only draft-safe observer intents.\n\n"
                    "Continuity packet JSON:\n"
                    f"{packet_json}"
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_object",
            }
        },
    }


def _gemini_generate_content_request_payload(packet: dict[str, Any]) -> dict[str, Any]:
    packet_json = json.dumps(packet, indent=2, sort_keys=True)
    max_output_tokens_raw = str(
        os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_GEMINI_MAX_OUTPUT_TOKENS")
        or os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_MAX_OUTPUT_TOKENS")
        or ""
    ).strip()
    max_output_tokens = 1400
    if max_output_tokens_raw:
        try:
            max_output_tokens = max(256, int(max_output_tokens_raw))
        except ValueError:
            max_output_tokens = 1400
    return {
        "systemInstruction": {
            "parts": [{"text": _continuity_observer_system_prompt()}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Return JSON only. Evaluate this bounded Synapse continuity packet and produce only draft-safe observer intents.\n\n"
                            "Continuity packet JSON:\n"
                            f"{packet_json}"
                        )
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
        },
    }


def _continuity_observer_system_prompt() -> str:
    return (
        "You are the Synapse continuity observer. "
        "You classify bounded execution evidence into draft-safe continuity intents. "
        "Output JSON only. "
        "Never invent canonical publication. "
        "Allowed artifact families are noop, semantic_capture, decision_log, disclosure_log, and open_obligation only. "
        "observer_status must be exactly ok or degraded. "
        "action_type must be exactly create, update, or noop. "
        "confidence must be exactly low, medium, or high. "
        "supersedes and updates must be arrays, never null. "
        "If evidence is weak, output noop or open_obligation instead of stronger intents. "
        "Preserve evidence refs. "
        "Use truthful degraded reasoning inside the rationale when uncertainty remains. "
        "The top-level JSON object must contain observer_status, provider_status, degraded, degraded_reason, rationale, and intents. "
        "Each intent must contain artifact_family, action_type, confidence, rationale, source_refs, truth_state_label, uncertainty_markers, draft_safe, gated_publication, supersedes, updates, and payload. "
        "JSON only."
    )


def _gemini_api_key() -> tuple[str, str | None]:
    for env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = str(os.environ.get(env_var) or "").strip()
        if value:
            return value, env_var
    return "", None


def _extract_gemini_output_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in list(payload.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        for part in list(content.get("parts") or []):
            if not isinstance(part, dict):
                continue
            text = str(part.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _extract_gemini_finish_reason(payload: dict[str, Any]) -> str:
    for candidate in list(payload.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        reason = str(candidate.get("finishReason") or "").strip()
        if reason:
            return reason
    return ""


def _extract_openai_output_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for output in list(payload.get("output") or []):
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        for content in list(output.get("content") or []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text":
                text = str(content.get("text") or "").strip()
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _extract_openai_refusal(payload: dict[str, Any]) -> str | None:
    for output in list(payload.get("output") or []):
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        for content in list(output.get("content") or []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                refusal = str(content.get("refusal") or "").strip()
                if refusal:
                    return refusal
    return None


def _coerce_model_backend_output(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    normalized = dict(payload)
    normalized["observer_status"] = _coerce_openai_observer_status(normalized.get("observer_status"))
    normalized["provider_status"] = str(normalized.get("provider_status") or "completed").strip() or "completed"
    normalized["degraded"] = bool(normalized.get("degraded", False))
    degraded_reason = normalized.get("degraded_reason")
    normalized["degraded_reason"] = None if degraded_reason in (None, "") else str(degraded_reason)
    normalized["rationale"] = str(normalized.get("rationale") or "").strip()
    normalized["intents"] = [_coerce_openai_intent(item) for item in list(normalized.get("intents") or []) if isinstance(item, dict)]
    return normalized


def _coerce_openai_observer_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"ok", "completed"}:
        return "ok"
    if normalized in {"degraded", "not_configured", "invalid", "failed"}:
        return "degraded"
    if normalized in {"valid", "active", "ready"}:
        return "ok"
    return normalized or "degraded"


def _coerce_openai_action_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"create", "update", "noop"}:
        return normalized
    if normalized in {"finalize", "new", "draft", "capture"}:
        return "create"
    if normalized in {"revise", "refresh", "amend"}:
        return "update"
    return normalized or "create"


def _coerce_openai_confidence(value: Any) -> str:
    if isinstance(value, (int, float)):
        if value >= 0.8:
            return "high"
        if value >= 0.4:
            return "medium"
        return "low"
    normalized = str(value or "").strip().lower()
    if normalized in {"low", "medium", "high"}:
        return normalized
    if normalized in {"strong", "certain", "validated"}:
        return "high"
    if normalized in {"moderate", "draft"}:
        return "medium"
    if normalized in {"weak", "uncertain"}:
        return "low"
    return normalized or "medium"


def _coerce_openai_source_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {"kind": "", "id": "", "path": ""}
    return {
        "kind": str(value.get("kind") or "").strip(),
        "id": str(value.get("id") or "").strip(),
        "path": str(value.get("path") or "").strip(),
    }


def _coerce_openai_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload: dict[str, Any] = {}
    scalar_fields = (
        "title",
        "summary",
        "why",
        "raw_text",
        "trigger",
        "expected",
        "provable",
        "impact",
        "decision_needed",
        "run_id",
        "session_id",
    )
    for field in scalar_fields:
        current = value.get(field)
        if current not in (None, ""):
            payload[field] = str(current)
    list_fields = {
        "status_labels": str,
        "safe_options": str,
        "changed_files": str,
    }
    for field, caster in list_fields.items():
        current = value.get(field)
        if isinstance(current, list):
            payload[field] = [caster(item) for item in current if str(item).strip()]
    captures = value.get("captures")
    if isinstance(captures, list):
        payload["captures"] = [
            {
                "kind": str(item.get("kind") or "").strip(),
                "summary": str(item.get("summary") or "").strip(),
            }
            for item in captures
            if isinstance(item, dict) and str(item.get("kind") or "").strip() and str(item.get("summary") or "").strip()
        ]
    return payload


def _coerce_openai_intent(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_family": str(value.get("artifact_family") or "").strip().lower(),
        "action_type": _coerce_openai_action_type(value.get("action_type")),
        "confidence": _coerce_openai_confidence(value.get("confidence")),
        "rationale": str(value.get("rationale") or "").strip(),
        "source_refs": [_coerce_openai_source_ref(item) for item in list(value.get("source_refs") or [])],
        "truth_state_label": str(value.get("truth_state_label") or "").strip(),
        "uncertainty_markers": [str(item).strip() for item in list(value.get("uncertainty_markers") or []) if str(item).strip()],
        "draft_safe": bool(value.get("draft_safe", True)),
        "gated_publication": bool(value.get("gated_publication", False)),
        "supersedes": [str(item).strip() for item in list(value.get("supersedes") or []) if str(item).strip()],
        "updates": [str(item).strip() for item in list(value.get("updates") or []) if str(item).strip()],
        "payload": _coerce_openai_payload(value.get("payload")),
    }
