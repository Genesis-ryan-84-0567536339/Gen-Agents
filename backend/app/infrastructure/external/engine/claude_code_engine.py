"""
Khung adapter Claude Code CLI — dot 2 CHI dung vo (_ProcessEngineBase dung
chung voi agy_engine.py: start/send/events/stop qua Sandbox.engine_*).
`_translate` raise NotImplementedError: dich NDJSON thuc te cua `claude`
(spec 01-dong-co-cli.md muc 4, spec 01 §8 muc 4) thuoc dot 3 — Issue #30
chi yeu cau spec 01 §8 muc 1-3 (xem docs/design/dot-2-cli-engine.md muc 2.2).
"""
from typing import List, Optional

from app.domain.external.engine import EngineContext, EngineEvent
from app.domain.external.sandbox import Sandbox
from app.infrastructure.external.engine.agy_engine import _ProcessEngineBase


class ClaudeCodeEngine(_ProcessEngineBase):
    """Khung dong co Claude Code — _build_argv/_build_user_line da ro theo
    spec 01 muc 4 (da do thuc), nhung _translate chua lam (dot 3)."""

    engine_name = "claude_code"

    def __init__(self, sandbox: Sandbox, binary: str = "claude"):
        super().__init__(sandbox, binary=binary or "claude")

    def _build_argv(self, ctx: EngineContext) -> List[str]:
        argv = [
            self._binary,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--model", ctx.model or "",
            "--settings", f"{ctx.home}/.claude/settings.json",
            "--mcp-config", f"{ctx.home}/mcp.json",
            "--strict-mcp-config",
            "--permission-mode", "bypassPermissions",
        ]
        if ctx.conversation_ref:
            argv += ["--resume", ctx.conversation_ref]
        return argv

    def _build_user_line(self, text: str, attachments: Optional[List[str]]) -> str:
        import json

        content_text = text
        for path in attachments or []:
            name = path.rsplit("/", 1)[-1]
            content_text += f"\n\nTệp đã tải lên: /home/ubuntu/upload/{name}"
        payload = {"type": "user", "message": {"role": "user", "content": content_text}}
        return json.dumps(payload, ensure_ascii=False)

    def _translate(self, parsed: dict) -> List[EngineEvent]:
        raise NotImplementedError(
            "Dich NDJSON cua Claude Code CLI la viec dot 3 (spec 01 §8 muc 4)"
        )
