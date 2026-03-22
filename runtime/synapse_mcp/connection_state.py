"""Connection-local context defaults for the Synapse MCP server."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from uuid import uuid4


@dataclass
class ConnectionState:
    workspace_root: str = field(default_factory=lambda: os.getcwd())
    default_subject: str | None = None
    default_engine_root: str | None = None
    default_data_root: str | None = None
    default_session_id: str | None = None
    server_instance_id: str = field(default_factory=lambda: f"mcp-{uuid4().hex}")

    def defaults_payload(self) -> dict[str, str | None]:
        return {
            "workspace_root": self.workspace_root,
            "subject": self.default_subject,
            "engine_root": self.default_engine_root,
            "data_root": self.default_data_root,
            "session_id": self.default_session_id,
            "server_instance_id": self.server_instance_id,
        }

    def update_subject_defaults(self, *, subject: str, engine_root: str, data_root: str) -> None:
        self.default_subject = subject
        self.default_engine_root = engine_root
        self.default_data_root = data_root

    def update_session_default(self, session_id: str | None) -> None:
        if session_id:
            self.default_session_id = session_id

    def clear_defaults(self) -> None:
        self.default_subject = None
        self.default_engine_root = None
        self.default_data_root = None
        self.default_session_id = None

    def update_after_bootstrap(self, *, subject: str, engine_root: str, data_root: str, session_id: str | None) -> None:
        self.update_subject_defaults(subject=subject, engine_root=engine_root, data_root=data_root)
        self.update_session_default(session_id)

    def update_after_onboarding(self, *, subject: str, engine_root: str, data_root: str, session_id: str | None) -> None:
        self.update_subject_defaults(subject=subject, engine_root=engine_root, data_root=data_root)
        if session_id and not self.default_session_id:
            self.default_session_id = session_id
