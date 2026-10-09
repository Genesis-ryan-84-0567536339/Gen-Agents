"""
Engine Service — chay CLI engine (agy / claude) nhu mot tien trinh dai trong
may nhiem vu, giu stdin mo, day stdout/stderr qua vong dem phat lai (deque).

Vi sao khong dung ShellService (tmux): xem docs/design/dot-2-cli-engine.md
muc 1.1 — tmux lam bien dang dong NDJSON (ANSI, wrap, rstrip), stdin la to
hop phim khong phai byte stream, va sentinel PS1 tron vao dong output.

Thiet ke:
- `asyncio.create_subprocess_exec(*argv, stdin=PIPE, stdout=PIPE, stderr=PIPE,
  cwd=cwd, env={**os.environ, **env}, limit=ENGINE_MAX_LINE_BYTES)` — PHAI
  truyen `limit` lon hon 64 KiB mac dinh cua StreamReader, vi dong NDJSON co
  `tool_info.output` thuong vuot ngay.
- Doc bang `readuntil(b"\\n")`; neu `LimitOverrunError`/`ValueError` (dong qua
  dai) thi phat mot dong `{"truncated": true, ...}` RỒI DOC TIEP — khong kill
  tien trinh.
- Moi dong (stdout VA stderr, cung mot deque, khac truong "stream") duoc gan
  `seq` tang don dieu tu 1, luu trong `deque(maxlen=ENGINE_BUFFER_LINES)`.
  `events(from_seq=N)` phat lai tu N+1 roi tiep tuc stream song — day la co
  che giup backend khong mat su kien khi phien di qua WAITING (Task moi,
  ket noi SSE moi).
- `start` idempotent: engine_id da ton tai VA con song -> tra `reused=True`,
  khong spawn them.
- `stop`: `terminate()` -> cho 5s -> `kill()`.
- Allowlist `ENGINE_ALLOWED_BINARIES` (so theo `os.path.basename(argv[0])`)
  la chot an toan cuoi — argv do backend dung (spec 01 muc 3/4).
"""
import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Deque, Dict, List, Optional

from app.core.config import settings
from app.core.exceptions import AppException, BadRequestException, ResourceNotFoundException

logger = logging.getLogger(__name__)


@dataclass
class EngineLine:
    seq: int
    stream: str  # "stdout" | "stderr"
    ts: float
    line: str
    truncated: bool = False


@dataclass
class EngineProcess:
    engine_id: str
    process: asyncio.subprocess.Process
    started_at: float
    cwd: str
    argv: List[str]
    lines: Deque[EngineLine] = field(default_factory=lambda: deque(maxlen=settings.ENGINE_BUFFER_LINES))
    seq: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    new_line_event: asyncio.Event = field(default_factory=asyncio.Event)
    reader_tasks: List[asyncio.Task] = field(default_factory=list)
    exited_at: Optional[float] = None
    stdin_bytes_total: int = 0

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    @property
    def returncode(self) -> Optional[int]:
        return self.process.returncode


def _allowed_binaries() -> set:
    return {
        name.strip()
        for name in (settings.ENGINE_ALLOWED_BINARIES or "").split(",")
        if name.strip()
    }


class EngineService:
    """Quan ly registry cac tien trinh CLI engine, theo `engine_id`."""

    def __init__(self) -> None:
        self._engines: Dict[str, EngineProcess] = {}
        self._reap_lock = asyncio.Lock()

    def _check_allowlist(self, argv: List[str]) -> None:
        if not argv:
            raise BadRequestException("argv rong")
        basename = os.path.basename(argv[0])
        allowed = _allowed_binaries()
        if allowed and basename not in allowed:
            raise BadRequestException(
                f"Binary '{basename}' khong trong ENGINE_ALLOWED_BINARIES ({sorted(allowed)})"
            )

    async def start(
        self, engine_id: str, argv: List[str], env: Dict[str, str], cwd: str
    ) -> Dict[str, object]:
        self._check_allowlist(argv)

        existing = self._engines.get(engine_id)
        if existing is not None and existing.alive:
            logger.info("engine %s da chay (pid=%s), tai su dung", engine_id, existing.process.pid)
            return {
                "engine_id": engine_id,
                "pid": existing.process.pid,
                "alive": True,
                "started_at": existing.started_at,
                "reused": True,
            }

        if not os.path.isdir(cwd):
            raise BadRequestException(f"cwd khong ton tai: {cwd}")

        full_env = {**os.environ, **(env or {})}
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=full_env,
                limit=settings.ENGINE_MAX_LINE_BYTES,
            )
        except FileNotFoundError as exc:
            raise BadRequestException(f"Khong tim thay binary: {argv[0]} ({exc})")
        except Exception as exc:
            logger.exception("khong khoi chay duoc engine %s", engine_id)
            raise AppException(message=f"Khong khoi chay duoc engine: {exc}")

        engine = EngineProcess(
            engine_id=engine_id,
            process=process,
            started_at=time.time(),
            cwd=cwd,
            argv=list(argv),
        )
        self._engines[engine_id] = engine
        engine.reader_tasks.append(
            asyncio.create_task(self._pump(engine, process.stdout, "stdout"))
        )
        engine.reader_tasks.append(
            asyncio.create_task(self._pump(engine, process.stderr, "stderr"))
        )
        logger.info("da khoi chay engine %s pid=%s argv0=%s", engine_id, process.pid, argv[0])
        return {
            "engine_id": engine_id,
            "pid": process.pid,
            "alive": True,
            "started_at": engine.started_at,
            "reused": False,
        }

    async def _append_line(self, engine: EngineProcess, stream: str, line: str, truncated: bool = False) -> None:
        async with engine.lock:
            engine.seq += 1
            engine.lines.append(
                EngineLine(seq=engine.seq, stream=stream, ts=time.time(), line=line, truncated=truncated)
            )
            # CHI set(), KHONG tu clear() ngay o day — xem ghi chu trong
            # events() ben duoi ve ly do "set roi clear ngay" la mot race
            # that (mat tin hieu).
            engine.new_line_event.set()

    async def _pump(self, engine: EngineProcess, stream: Optional[asyncio.StreamReader], label: str) -> None:
        """Doc tung dong tu stdout/stderr, phat vao deque. Dong qua dai (vuot
        `limit`) khong lam chet pump — chi phat dong {"truncated": true}."""
        if stream is None:
            return
        try:
            while True:
                try:
                    raw = await stream.readuntil(b"\n")
                except asyncio.IncompleteReadError as exc:
                    # EOF — phan con lai (khong co \n cuoi) van la du lieu hop le
                    if exc.partial:
                        text = exc.partial.decode("utf-8", errors="replace")
                        await self._append_line(engine, label, text)
                    break
                except (asyncio.LimitOverrunError, ValueError):
                    # Dong vuot ENGINE_MAX_LINE_BYTES — doc het phan con lai de
                    # khong ket dong chars) roi phat dong truncated, KHONG kill.
                    consumed = 0
                    while True:
                        chunk = await stream.read(settings.ENGINE_MAX_LINE_BYTES)
                        consumed += len(chunk)
                        if not chunk or b"\n" in chunk:
                            break
                    await self._append_line(
                        engine,
                        label,
                        f'{{"truncated": true, "bytes": {consumed}}}',
                        truncated=True,
                    )
                    continue
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace").rstrip("\n")
                await self._append_line(engine, label, text)
        except Exception:
            logger.exception("engine %s pump(%s) loi, dung doc", engine.engine_id, label)
        finally:
            # Danh dau tien trinh da ket thuc khi ca hai pump xong (an toan
            # goi lai nhieu lan)
            try:
                await engine.process.wait()
            except Exception:
                pass
            if engine.exited_at is None:
                engine.exited_at = time.time()
            engine.new_line_event.set()

    async def send(self, engine_id: str, line: str) -> Dict[str, object]:
        engine = self._engines.get(engine_id)
        if engine is None or not engine.alive:
            raise ResourceNotFoundException(f"Engine {engine_id} khong ton tai hoac da chet")
        payload = (line if line.endswith("\n") else line + "\n").encode("utf-8")
        try:
            engine.process.stdin.write(payload)
            await engine.process.stdin.drain()
        except Exception as exc:
            logger.exception("ghi stdin engine %s loi", engine_id)
            raise AppException(message=f"Khong ghi duoc stdin: {exc}")
        engine.stdin_bytes_total += len(payload)
        return {"ok": True, "bytes": len(payload)}

    async def status(self, engine_id: str) -> Dict[str, object]:
        engine = self._engines.get(engine_id)
        if engine is None:
            return {"alive": False, "returncode": None, "last_seq": 0, "started_at": None}
        return {
            "alive": engine.alive,
            "returncode": engine.returncode,
            "last_seq": engine.seq,
            "started_at": engine.started_at,
        }

    async def stop(self, engine_id: str, signal: Optional[str] = None) -> Dict[str, object]:
        engine = self._engines.get(engine_id)
        if engine is None:
            return {"ok": True, "returncode": None}
        if engine.alive:
            try:
                if (signal or "TERM").upper() == "KILL":
                    engine.process.kill()
                else:
                    engine.process.terminate()
                    try:
                        await asyncio.wait_for(engine.process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        engine.process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(engine.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
        return {"ok": True, "returncode": engine.returncode}

    async def events(self, engine_id: str, from_seq: int = 0) -> AsyncIterator[EngineLine]:
        """Phat lai cac dong co seq > from_seq, roi tiep tuc stream song cho
        den khi tien trinh chet VA deque da can het."""
        engine = self._engines.get(engine_id)
        if engine is None:
            raise ResourceNotFoundException(f"Engine {engine_id} khong ton tai")

        last_seq = from_seq
        while True:
            async with engine.lock:
                pending = [item for item in engine.lines if item.seq > last_seq]
                # QUAN TRONG — tranh mat tin hieu (da bat qua thuc te, bang
                # chung dot 2): clear() PHAI xay ra NGAY SAU khi chup anh
                # (snapshot) "pending", VA trong CUNG mot lan giu lock voi
                # lan set() gan nhat ma no se huy. Neu _append_line() tu
                # set()-roi-clear() ngay (kieu "pulse"), mot waiter goi
                # wait() SAU khi pulse da tat se cho het 15s cho mot tin
                # hieu khong bao gio den nua (du du lieu moi da nam san
                # trong engine.lines). Cach o day dam bao: bat ky dong nao
                # duoc them vao SAU snapshot nay (ke ca dung luc nay) se tu
                # set() lai, nen wait() ben duoi se tra ve ngay thay vi cho
                # mu 15 giay.
                engine.new_line_event.clear()
            for item in pending:
                last_seq = item.seq
                yield item
            if not engine.alive and last_seq >= engine.seq:
                return
            try:
                await asyncio.wait_for(engine.new_line_event.wait(), timeout=15)
            except asyncio.TimeoutError:
                continue

    async def reap_expired(self) -> None:
        """Xoa cac engine da chet qua `ENGINE_KEEP_AFTER_EXIT_SECONDS`."""
        async with self._reap_lock:
            now = time.time()
            expired = [
                engine_id
                for engine_id, engine in self._engines.items()
                if not engine.alive
                and engine.exited_at is not None
                and now - engine.exited_at > settings.ENGINE_KEEP_AFTER_EXIT_SECONDS
            ]
            for engine_id in expired:
                del self._engines[engine_id]
                logger.info("da xoa engine %s khoi registry (qua han giu lai)", engine_id)


engine_service = EngineService()
