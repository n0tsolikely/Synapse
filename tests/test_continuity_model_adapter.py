import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.continuity_model_adapter import (
    continuity_observer_provider_options,
    invoke_continuity_observer_backend,
)


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class ContinuityModelAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = {
            "packet_schema_version": 1,
            "subject": "ObserverSubject",
            "trigger": "close-turn",
            "boundary": "strict",
            "session_id": "SID-1",
            "run_id": "RUN-1",
            "summary": "Lock the observer seam.",
            "notes": ["Observer should emit JSON only."],
            "changed_files": ["runtime/synapse.py"],
            "decision_boundary": True,
            "uncertainty_present": False,
            "source_refs": [{"kind": "raw_turn", "id": "RAW-1"}],
        }

    def test_openai_backend_degrades_when_api_key_missing(self) -> None:
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            payload = invoke_continuity_observer_backend(packet=self.packet, backend="openai_responses")
        self.assertEqual(payload["backend"], "openai_responses")
        self.assertEqual(payload["provider_status"], "not_configured")
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["degraded_reason"], "missing_openai_api_key")

    def test_openai_backend_returns_schema_valid_output(self) -> None:
        api_payload = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "observer_status": "ok",
                                    "provider_status": "completed",
                                    "degraded": False,
                                    "degraded_reason": None,
                                    "rationale": "The packet contains an explicit decision boundary with bounded source refs.",
                                    "intents": [
                                        {
                                            "artifact_family": "decision_log",
                                            "action_type": "create",
                                            "confidence": "medium",
                                            "rationale": "The packet marks a decision boundary.",
                                            "source_refs": [{"kind": "raw_turn", "id": "RAW-1"}],
                                            "truth_state_label": "decision_draft",
                                            "uncertainty_markers": [],
                                            "draft_safe": True,
                                            "gated_publication": False,
                                            "supersedes": [],
                                            "updates": [],
                                            "payload": {
                                                "title": "Lock the observer seam.",
                                                "summary": "Lock the observer seam.",
                                                "why": "Decision boundary was explicit.",
                                            },
                                        }
                                    ],
                                }
                            ),
                        }
                    ],
                }
            ],
        }
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch(
            "synapse_runtime.continuity_model_adapter.urllib_request.urlopen",
            return_value=_FakeHTTPResponse(api_payload),
        ):
            payload = invoke_continuity_observer_backend(packet=self.packet, backend="openai_responses")
        self.assertEqual(payload["backend"], "openai_responses")
        self.assertEqual(payload["observer_status"], "ok")
        self.assertFalse(payload["degraded"])
        self.assertEqual(payload["provider_status"], "completed")
        self.assertEqual(payload["intents"][0]["artifact_family"], "decision_log")

    def test_openai_backend_coerces_sloppy_but_salvageable_output(self) -> None:
        api_payload = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "observer_status": "valid",
                                    "provider_status": "completed",
                                    "degraded": False,
                                    "degraded_reason": None,
                                    "rationale": "The packet contains a real decision boundary.",
                                    "intents": [
                                        {
                                            "artifact_family": "decision_log",
                                            "action_type": "finalize",
                                            "confidence": 0.92,
                                            "rationale": "Decision boundary is explicit.",
                                            "source_refs": [{"kind": "raw_turn", "id": "RAW-1"}],
                                            "truth_state_label": "decision_draft",
                                            "uncertainty_markers": [],
                                            "draft_safe": True,
                                            "gated_publication": False,
                                            "supersedes": None,
                                            "updates": None,
                                            "payload": {
                                                "title": "Lock the observer seam.",
                                                "summary": "Lock the observer seam.",
                                            },
                                        }
                                    ],
                                }
                            ),
                        }
                    ],
                }
            ],
        }
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch(
            "synapse_runtime.continuity_model_adapter.urllib_request.urlopen",
            return_value=_FakeHTTPResponse(api_payload),
        ):
            payload = invoke_continuity_observer_backend(packet=self.packet, backend="openai_responses")
        self.assertEqual(payload["observer_status"], "ok")
        self.assertEqual(payload["provider_status"], "completed")
        self.assertFalse(payload["degraded"])
        self.assertEqual(payload["intents"][0]["action_type"], "create")
        self.assertEqual(payload["intents"][0]["confidence"], "high")
        self.assertEqual(payload["intents"][0]["supersedes"], [])
        self.assertEqual(payload["intents"][0]["updates"], [])

    def test_openai_backend_degrades_on_refusal(self) -> None:
        api_payload = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "refusal",
                            "refusal": "I can't comply with that request.",
                        }
                    ],
                }
            ],
        }
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch(
            "synapse_runtime.continuity_model_adapter.urllib_request.urlopen",
            return_value=_FakeHTTPResponse(api_payload),
        ):
            payload = invoke_continuity_observer_backend(packet=self.packet, backend="openai_responses")
        self.assertEqual(payload["provider_status"], "refusal")
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["degraded_reason"], "openai_refusal")

    def test_openai_backend_degrades_on_http_error(self) -> None:
        http_error = urllib_error.HTTPError(
            url="https://api.openai.com/v1/responses",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"rate limit"}}'),
        )
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch(
            "synapse_runtime.continuity_model_adapter.urllib_request.urlopen",
            side_effect=http_error,
        ):
            payload = invoke_continuity_observer_backend(packet=self.packet, backend="openai_responses")
        self.assertEqual(payload["provider_status"], "http_error:429")
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["degraded_reason"], "openai_http_error")

    def test_openai_backend_degrades_on_schema_mismatch(self) -> None:
        api_payload = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "observer_status": "ok",
                                    "provider_status": "completed",
                                    "degraded": False,
                                    "degraded_reason": None,
                                    "rationale": "bad",
                                    "intents": [
                                        {
                                            "artifact_family": "publish_truth",
                                        }
                                    ],
                                }
                            ),
                        }
                    ],
                }
            ],
        }
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch(
            "synapse_runtime.continuity_model_adapter.urllib_request.urlopen",
            return_value=_FakeHTTPResponse(api_payload),
        ):
            payload = invoke_continuity_observer_backend(packet=self.packet, backend="openai_responses")
        self.assertEqual(payload["provider_status"], "schema_mismatch")
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["degraded_reason"], "openai_backend_output_schema_mismatch")

    def test_provider_options_detect_openai_and_gemini_envs(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-openai-key",
                "GEMINI_API_KEY": "test-gemini-key",
                "GOOGLE_API_KEY": "",
            },
            clear=False,
        ):
            options = continuity_observer_provider_options()
        by_backend = {item["backend"]: item for item in options}
        self.assertTrue(by_backend["openai_responses"]["available"])
        self.assertEqual(by_backend["openai_responses"]["matched_env_vars"], ["OPENAI_API_KEY"])
        self.assertTrue(by_backend["gemini_generate_content"]["available"])
        self.assertEqual(by_backend["gemini_generate_content"]["matched_env_vars"], ["GEMINI_API_KEY"])

    def test_gemini_backend_degrades_when_api_key_missing(self) -> None:
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
            payload = invoke_continuity_observer_backend(packet=self.packet, backend="gemini_generate_content")
        self.assertEqual(payload["backend"], "gemini_generate_content")
        self.assertEqual(payload["provider_status"], "not_configured")
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["degraded_reason"], "missing_gemini_api_key")

    def test_gemini_backend_returns_schema_valid_output(self) -> None:
        api_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "observer_status": "ok",
                                        "provider_status": "ok",
                                        "degraded": False,
                                        "degraded_reason": None,
                                        "rationale": "The packet contains an explicit decision boundary with bounded source refs.",
                                        "intents": [
                                            {
                                                "artifact_family": "decision_log",
                                                "action_type": "create",
                                                "confidence": "medium",
                                                "rationale": "The packet marks a decision boundary.",
                                                "source_refs": [{"kind": "raw_turn", "id": "RAW-1"}],
                                                "truth_state_label": "decision_draft",
                                                "uncertainty_markers": [],
                                                "draft_safe": True,
                                                "gated_publication": False,
                                                "supersedes": [],
                                                "updates": [],
                                                "payload": {
                                                    "title": "Lock the observer seam.",
                                                    "summary": "Lock the observer seam.",
                                                    "why": "Decision boundary was explicit.",
                                                },
                                            }
                                        ],
                                    }
                                )
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "test-gemini-key"}, clear=False), mock.patch(
            "synapse_runtime.continuity_model_adapter.urllib_request.urlopen",
            return_value=_FakeHTTPResponse(api_payload),
        ):
            payload = invoke_continuity_observer_backend(packet=self.packet, backend="gemini_generate_content")
        self.assertEqual(payload["backend"], "gemini_generate_content")
        self.assertEqual(payload["observer_status"], "ok")
        self.assertFalse(payload["degraded"])
        self.assertEqual(payload["intents"][0]["artifact_family"], "decision_log")

    def test_gemini_backend_degrades_on_prompt_block(self) -> None:
        api_payload = {
            "promptFeedback": {
                "blockReason": "SAFETY",
            }
        }
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "test-gemini-key"}, clear=False), mock.patch(
            "synapse_runtime.continuity_model_adapter.urllib_request.urlopen",
            return_value=_FakeHTTPResponse(api_payload),
        ):
            payload = invoke_continuity_observer_backend(packet=self.packet, backend="gemini_generate_content")
        self.assertEqual(payload["provider_status"], "prompt_blocked")
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["degraded_reason"], "gemini_prompt_blocked")


if __name__ == "__main__":
    unittest.main()
