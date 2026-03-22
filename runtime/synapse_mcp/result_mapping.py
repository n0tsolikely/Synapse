"""Mapping helpers from runtime outcomes to the MCP result envelope."""

from __future__ import annotations

from typing import Any


STATUS_OK = "ok"
STATUS_NOOP = "noop"
STATUS_PARTIAL = "partial"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"

_BLOCKED_CODES = {
    "POSTURE_TRANSITION_BLOCKED",
    "FORMALIZATION_BLOCKED",
    "QUEST_ACCEPTANCE_BLOCKED",
    "ONBOARDING_STATE_BLOCKED",
}


class BridgeFailure(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status: str = STATUS_FAILED,
        recovery_hint: str | None = None,
        data: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        runtime_status: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.recovery_hint = recovery_hint
        self.data = data or {}
        self.warnings = warnings or []
        self.runtime_status = runtime_status


def subject_context_payload(ctx: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ctx, dict):
        return {
            "subject": None,
            "engine_root": None,
            "data_root": None,
            "session_id": None,
        }
    return {
        "subject": ctx.get("subject"),
        "engine_root": ctx.get("engine_root"),
        "data_root": ctx.get("data_root"),
        "session_id": ctx.get("session_id"),
    }


def envelope(
    *,
    status: str,
    subject_context: dict[str, Any] | None,
    data: dict[str, Any] | None = None,
    runtime_status: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": status in {STATUS_OK, STATUS_NOOP},
        "status": status,
        "subject_context": subject_context_payload(subject_context),
        "runtime_status": runtime_status,
        "data": data or {},
        "warnings": warnings or [],
        "error": error,
    }


def ok(subject_context: dict[str, Any] | None, *, data: dict[str, Any] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    return envelope(status=STATUS_OK, subject_context=subject_context, data=data, warnings=warnings)


def noop(subject_context: dict[str, Any] | None, *, data: dict[str, Any] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    return envelope(status=STATUS_NOOP, subject_context=subject_context, data=data, warnings=warnings)


def partial(subject_context: dict[str, Any] | None, *, data: dict[str, Any] | None = None, runtime_status: dict[str, Any] | None = None, warnings: list[str] | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    return envelope(
        status=STATUS_PARTIAL,
        subject_context=subject_context,
        data=data,
        runtime_status=runtime_status,
        warnings=warnings,
        error=error,
    )


def blocked(subject_context: dict[str, Any] | None, *, code: str, message: str, recovery_hint: str | None = None, data: dict[str, Any] | None = None, runtime_status: dict[str, Any] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    return envelope(
        status=STATUS_BLOCKED,
        subject_context=subject_context,
        data=data,
        runtime_status=runtime_status,
        warnings=warnings,
        error={
            "code": code,
            "message": message,
            "recovery_hint": recovery_hint,
        },
    )


def failed(subject_context: dict[str, Any] | None, *, code: str, message: str, recovery_hint: str | None = None, data: dict[str, Any] | None = None, runtime_status: dict[str, Any] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    if code in _BLOCKED_CODES:
        return blocked(
            subject_context,
            code=code,
            message=message,
            recovery_hint=recovery_hint,
            data=data,
            runtime_status=runtime_status,
            warnings=warnings,
        )
    return envelope(
        status=STATUS_FAILED,
        subject_context=subject_context,
        data=data,
        runtime_status=runtime_status,
        warnings=warnings,
        error={
            "code": code,
            "message": message,
            "recovery_hint": recovery_hint,
        },
    )


def from_failure(subject_context: dict[str, Any] | None, failure: BridgeFailure) -> dict[str, Any]:
    if failure.status == STATUS_BLOCKED:
        return blocked(
            subject_context,
            code=failure.code,
            message=failure.message,
            recovery_hint=failure.recovery_hint,
            data=failure.data,
            runtime_status=failure.runtime_status,
            warnings=failure.warnings,
        )
    return failed(
        subject_context,
        code=failure.code,
        message=failure.message,
        recovery_hint=failure.recovery_hint,
        data=failure.data,
        runtime_status=failure.runtime_status,
        warnings=failure.warnings,
    )


def from_runtime_status(
    *,
    subject_context: dict[str, Any] | None,
    data: dict[str, Any] | None,
    runtime_status: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    operation_status = str(runtime_status.get("operation_status") or "").strip().lower()
    if operation_status == "partial":
        code = str(runtime_status.get("error_code") or "REDUCER_REFRESH_FAILED")
        return partial(
            subject_context,
            data=data,
            runtime_status=runtime_status,
            warnings=warnings,
            error={
                "code": code,
                "message": runtime_status.get("error_message") or "Runtime mutation partially succeeded.",
                "recovery_hint": runtime_status.get("recovery_hint"),
            },
        )
    return ok(subject_context, data=data, warnings=warnings)
