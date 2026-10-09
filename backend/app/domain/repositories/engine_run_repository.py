from typing import Any, Dict, List, Optional, Protocol, Tuple


class EngineRunRepository(Protocol):
    """Luu NDJSON tho + usage cua tung luot CLI engine (agy/Claude Code) —
    docs/design/dot-2-cli-engine.md muc 5. Mot document / mot luot (khong
    phai mot dong) — xem `EngineRunDocument`."""

    async def open_turn(
        self,
        session_id: str,
        user_id: str,
        engine: str,
        conversation_ref: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Tuple[str, int]:
        """Tao document cho mot luot moi (tu tinh `turn_index` tiep theo cua
        session nay). Tra `(run_id, turn_index)`."""
        ...

    async def append_lines(self, run_id: str, lines: List[Dict[str, Any]]) -> None:
        """`$push` nhieu dong {seq, stream, ts, raw} cung luc (ghi gop)."""
        ...

    async def mark_dropped(self, run_id: str, count: int) -> None:
        """Tang `lines_dropped` khi vuot tran kich thuoc (GEN_ENGINE_RAW_MAX_BYTES)."""
        ...

    async def close_turn(self, run_id: str, status: str, usage: Optional[Dict[str, Any]] = None) -> None:
        """Dong luot: ghi `status` (SUCCESS|ERROR|WAITING), `ended_at`, va
        `usage` cuoi cung cua luot (neu co)."""
        ...

    async def find_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        """Toan bo luot cua mot session, sap theo `turn_index` tang dan —
        dung cho nghiem thu (mo lai phien cu thay lich su)."""
        ...
