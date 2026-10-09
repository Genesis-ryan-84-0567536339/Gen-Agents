from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import hashlib
import json
import yaml
from typing import List, Optional, Dict, Any, Union
import os
from pathlib import Path
import asyncio
import logging
import sys

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False

class ChatCompletionResponse(BaseModel):
    #id: str
    #object: str
    #created: int
    #model: str
    choices: List[Dict[str, Any]]

# Runtime override for MOCK_DATA_FILE, set via POST /mock/scenario (used by
# e2e tests to switch scripts without restarting the container).
scenario_override: Optional[str] = None


def current_mock_file() -> str:
    return scenario_override or os.getenv("MOCK_DATA_FILE", "default.yaml")


def load_mock_data():
    mock_file = current_mock_file()
    mock_file_path = Path(__file__).parent / "mock_datas" / mock_file

    with open(mock_file_path, 'r', encoding='utf-8') as f:
        logger.info(f"Loading mock data from {mock_file}")
        if mock_file.endswith('.json'):
            return json.load(f)
        else:
            return yaml.safe_load(f)

# Issue #35 — nguyen nhan goc: PlanActFlow chay HAI agent co registry tool
# khac nhau (PlannerAgent: create_plan/update_plan; Executor: message_*/
# shell_*/file_*/mcp...) nhung mock truoc day chi co MOT con tro toan cuc
# (`current_index`), nen lan goi dau cua agent thu hai (dung 2 message, giong
# heuristic reset) vo tinh "cuop" lai dong script cua agent dau. Sua: mot con
# tro RIENG cho moi agent, khoa boi hash system prompt (`messages[0].content`)
# — moi agent mot system prompt khac nhau nen hash khac nhau on dinh suot
# phien. Xem docs/design/dot-2-cli-engine.md muc 7.
#
# QUAN TRONG — tai sao van giu MOT khoa toan cuc cho dang list cu: 10 scenario
# flat-list con lai (vd plan_act_wait_e2e.yaml) duoc viet cho dung MOT con tro
# CHIA SE tuan tu qua ca hai agent (planner doc entry 0, executor tiep tuc tu
# entry 1, 2, 3...) — day la ban than co che cu truoc Issue #35 ma cac file
# nay dang dua vao. Neu doi sang con tro rieng-tung-hash cho CA list cu, moi
# agent se doc lai tu dau danh sach dung chung -> vo tinh lai sai (da kiem
# thuc: test_e2e_plan_act_wait_and_resume do dung khi lam vay). Vi vay: dang
# list -> MOT khoa co dinh _GLOBAL_KEY (dung behavior cu nguyen ven); dang
# dict {"planner":[...], "executor":[...]} (file da vá cho #35) -> khoa rieng
# theo hash, nhu mo ta o tren.
_GLOBAL_KEY = "__global__"
cursors: Dict[str, int] = {}
# Khi mock_data la dict {"planner": [...], "executor": [...]} (thay vi list
# cu), gan mot "role" cho moi hash LAN DAU gap (PlannerAgent luon chay truoc
# ExecutionAgent trong PlanActFlow nen thu tu gap-lan-dau == thu tu vai).
_hash_to_role: Dict[str, str] = {}
_pending_roles: List[str] = []


def _system_prompt_hash(request: "ChatCompletionRequest") -> str:
    content = request.messages[0].content if request.messages else ""
    return hashlib.sha1((content or "").encode("utf-8")).hexdigest()[:16]


def _resolve_script(mock_data: Union[list, dict], key: str) -> list:
    """Tra ve dung danh sach response cho agent goi request nay."""
    global _pending_roles
    if not isinstance(mock_data, dict):
        return mock_data
    role = _hash_to_role.get(key)
    if role is None:
        if not _pending_roles:
            _pending_roles = list(mock_data.keys())
        role = _pending_roles.pop(0) if _pending_roles else next(iter(mock_data))
        _hash_to_role[key] = role
        logger.info(f"Gan agent voi hash {key} vao vai '{role}'")
    return mock_data[role]


def _reset_cursors() -> None:
    cursors.clear()
    _hash_to_role.clear()
    _pending_roles.clear()


class ScenarioRequest(BaseModel):
    file: str


@app.get("/mock/scenario")
async def get_scenario():
    """Inspect the active scenario and replay position."""
    try:
        data = load_mock_data()
        total = {k: len(v) for k, v in data.items()} if isinstance(data, dict) else len(data)
    except FileNotFoundError:
        total = None
    return {"file": current_mock_file(), "cursors": dict(cursors), "responses": total}


@app.post("/mock/scenario")
async def set_scenario(request: ScenarioRequest):
    """Switch the active scenario file and reset all per-agent cursors."""
    global scenario_override
    if "/" in request.file or "\\" in request.file:
        raise HTTPException(status_code=400, detail="Invalid scenario file name")
    path = Path(__file__).parent / "mock_datas" / request.file
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Scenario not found: {request.file}")
    scenario_override = request.file
    _reset_cursors()
    data = load_mock_data()
    total = {k: len(v) for k, v in data.items()} if isinstance(data, dict) else len(data)
    logger.info(f"Scenario switched to {request.file} ({total} responses)")
    return {"file": request.file, "index": 0, "responses": total}


@app.post("/mock/reset")
async def reset_scenario():
    """Reset all per-agent replay cursors (and clear any scenario override)."""
    global scenario_override
    scenario_override = None
    _reset_cursors()
    return {"file": current_mock_file(), "index": 0}

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    mock_data = load_mock_data()
    if not mock_data:
        logger.error("No mock data available")
        raise HTTPException(status_code=500, detail="No mock data available")

    # Dang dict (da vá cho Issue #35): con tro RIENG theo hash system prompt.
    # Dang list cu: MOT con tro CHIA SE (_GLOBAL_KEY) — xem chu thich o dinh
    # file ve ly do khong doi sang per-hash cho dang list.
    hash_key = _system_prompt_hash(request)
    script = _resolve_script(mock_data, hash_key)
    key = hash_key if isinstance(mock_data, dict) else _GLOBAL_KEY
    index = cursors.get(key, 0)

    if len(request.messages) == 2 and index > 1:
        index = 0
        logger.info(f"Reset cursor to 0 for key {key}")

    delay = float(os.getenv("MOCK_DELAY", "1"))
    if delay > 0:
        logger.debug(f"Applying mock delay of {delay} seconds")
        await asyncio.sleep(delay)

    response = script[index]
    cursors[key] = (index + 1) % len(script)
    logger.info(f"Returning mock response {cursors[key]}/{len(script)} for agent hash {key}")
    return response
