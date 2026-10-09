import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.domain.repositories.engine_run_repository import EngineRunRepository
from app.infrastructure.models.documents import EngineRunDocument

logger = logging.getLogger(__name__)


class MongoEngineRunRepository(EngineRunRepository):
    """Mongo implementation — docs/design/dot-2-cli-engine.md muc 5."""

    async def open_turn(
        self,
        session_id: str,
        user_id: str,
        engine: str,
        conversation_ref: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Tuple[str, int]:
        existing_count = await EngineRunDocument.find(
            EngineRunDocument.session_id == session_id
        ).count()
        turn_index = existing_count + 1
        run_id = str(uuid.uuid4())
        doc = EngineRunDocument(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            engine=engine,
            conversation_ref=conversation_ref,
            turn_index=turn_index,
            started_at=datetime.now(UTC),
            status="RUNNING",
        )
        try:
            await doc.insert()
        except Exception:
            # Unique index (session_id, turn_index) co the da bi chiem (dua
            # hiem giua 2 luot cung luc) — thu lai dung mot lan voi index ke.
            logger.warning("engine_runs: turn_index %s cho session %s da bi chiem, thu lai", turn_index, session_id)
            turn_index = existing_count + 2
            doc.turn_index = turn_index
            await doc.insert()
        return run_id, turn_index

    async def append_lines(self, run_id: str, lines: List[Dict[str, Any]]) -> None:
        if not lines:
            return
        added_bytes = sum(len(line.get("raw", "")) for line in lines)
        await EngineRunDocument.find_one(EngineRunDocument.run_id == run_id).update(
            {"$push": {"lines": {"$each": lines}}, "$inc": {"bytes_total": added_bytes}}
        )

    async def mark_dropped(self, run_id: str, count: int) -> None:
        if count <= 0:
            return
        await EngineRunDocument.find_one(EngineRunDocument.run_id == run_id).update(
            {"$inc": {"lines_dropped": count}}
        )

    async def close_turn(self, run_id: str, status: str, usage: Optional[Dict[str, Any]] = None) -> None:
        update: Dict[str, Any] = {"status": status, "ended_at": datetime.now(UTC)}
        if usage:
            update["usage"] = usage
        await EngineRunDocument.find_one(EngineRunDocument.run_id == run_id).update(
            {"$set": update}
        )

    async def find_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        docs = await EngineRunDocument.find(
            EngineRunDocument.session_id == session_id
        ).sort("turn_index").to_list()
        return [doc.model_dump() for doc in docs]
