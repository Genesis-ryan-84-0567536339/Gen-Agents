#!/usr/bin/env python3
"""
Gia lap toi thieu giao thuc NDJSON cua agy (docs/spec/01-dong-co-cli.md muc 3)
de test tang sandbox (test_engine_api.py) va test tang backend (CI job e2e,
docs/design/dot-2-cli-engine.md muc 7.2-7.3) khong can agy that/dang nhap.

Doc tung dong stream-json tren stdin:
    {"event":"user","message":{"content":[{"type":"text","text":"..."}]}}
Voi MOI luot (dong) nhan duoc, in ra:
    1) init (chi lan dau tien, khoa boi bien moi truong FAKE_AGY_SENT_INIT -
       nhung vi moi tien trinh la 1 lan start nen chi can in 1 lan o dau doi
       song tien trinh)
    2) step_update agent_response (text_delta)
    3) step_update tool ACTIVE + DONE (gia lap run_command)
    4) step_update tool ACTIVE + DONE cho plan_update (MCP) — danh dau
       step_type=tool, tool_name chua tien to gia lap sandbox__plan_update
    5) FAKE_AGY_MODE=ask -> step_update tool cho message_ask_user, KHONG
       phat result (CLI "dung lai" sau khi hoi — dung ngu nghia 1.5 cua
       thiet ke: dung o bien luot, tien trinh van song)
       FAKE_AGY_MODE=error -> result ERROR (noi dung dung mau
       docs/evidence/dot-1/agy-p-auth-failed.txt)
       FAKE_AGY_MODE=demo (CHI danh cho bang chung nghiem thu, KHONG dung
       trong pytest) -> thuc su mo Chrome qua CDP + ghi file qua tool API
       truoc khi phat dong NDJSON browser_navigate/file_write tuong ung
       Nguoc lai -> result SUCCESS kem usage

conversation_id co dinh de test kiem duoc --conversation noi lai.
"""
import json
import os
import sys
import urllib.request

CONVERSATION_ID = os.environ.get("FAKE_AGY_CONVERSATION_ID", "fake-conv-001")
MODE = os.environ.get("FAKE_AGY_MODE", "success")
# MODE=ask chi hoi o luot nay (mac dinh luot 1); cac luot sau tra SUCCESS binh
# thuong — mo phong kich ban "hoi -> tra loi -> tiep tuc cung conversation_id"
# (docs/design/dot-2-cli-engine.md muc 8, kich ban 3).
ASK_AT_TURN = int(os.environ.get("FAKE_AGY_ASK_TURN", "1"))

_init_sent = False


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _emit_init() -> None:
    global _init_sent
    if _init_sent:
        return
    _init_sent = True
    _emit({
        "event": "init",
        "conversation_id": CONVERSATION_ID,
        "init": {
            "model": os.environ.get("FAKE_AGY_MODEL", "gemini-3.8-flash-low"),
            "cwd": os.getcwd(),
            "tools": ["run_command", "view_file", "sandbox__plan_update", "sandbox__message_ask_user"],
            "permission_mode": "request-review",
        },
    })


def _emit_big_line_if_requested(step: int) -> None:
    """FAKE_AGY_BIG_LINE_KB=N: in them mot dong step_update voi tool_info.output
    dai N KiB — dung de kiem `limit=ENGINE_MAX_LINE_BYTES` trong
    sandbox/app/services/engine.py khong lam vo dong (StreamReader mac dinh
    chi 64 KiB, xem docs/design/dot-2-cli-engine.md muc 1.3)."""
    big_kb = os.environ.get("FAKE_AGY_BIG_LINE_KB")
    if not big_kb:
        return
    size = int(big_kb) * 1024
    _emit({
        "event": "step_update",
        "step_update": {
            "step_index": step,
            "state": "DONE",
            "step_type": "tool",
            "tool_name": "run_command",
            "tool_info": {"name": "run_command", "output": "x" * size},
        },
    })


def _demo_browser_and_file() -> tuple[str, str]:
    """CHI danh cho bang chung nghiem thu dot 2 (khong dung trong pytest):
    thuc su dieu khien Chrome qua CDP HTTP (/json/new) va ghi file qua tool
    API REST :8080 — giong NHU agy that se goi MCP server cua sandbox —
    truoc khi phat dong NDJSON tuong ung, de noVNC + file ket qua la THAT,
    khong chi la dong gia lap."""
    url = os.environ.get("FAKE_AGY_DEMO_URL", "https://example.com")
    cdp_base = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
    req = urllib.request.Request(f"{cdp_base}/json/new?{url}", method="PUT")
    with urllib.request.urlopen(req, timeout=10) as resp:
        tab = json.loads(resp.read().decode("utf-8"))
    tab_title = tab.get("url", url)

    summary_path = "/home/ubuntu/output/tom-tat.md"
    summary_content = f"# Tom tat\n\nDa mo trang: {tab_title}\n\n(Ghi boi fake_agy.py, bang chung dot 2 Issue #30)\n"
    payload = json.dumps({"file": summary_path, "content": summary_content, "append": False}).encode("utf-8")
    tool_api_base = os.environ.get("TOOL_API_BASE_URL", "http://127.0.0.1:8080")
    req2 = urllib.request.Request(
        f"{tool_api_base}/api/v1/file/write", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req2, timeout=10) as resp2:
        resp2.read()
    return url, summary_path


def _handle_turn(turn_index: int) -> None:
    _emit_init()
    step = turn_index * 10
    _emit_big_line_if_requested(step)

    _emit({
        "event": "step_update",
        "step_update": {
            "step_index": step + 1,
            "state": "ACTIVE",
            "step_type": "agent_response",
            "text_delta": "OK, dang xu ly.",
        },
    })

    # Tool gia lap: run_command (tool goc cua agy, khong qua MCP)
    _emit({
        "event": "step_update",
        "step_update": {
            "step_index": step + 2,
            "state": "ACTIVE",
            "step_type": "tool",
            "tool_name": "run_command",
            "tool_info": {"name": "run_command", "parameters": {"CommandLine": "echo hi"}},
        },
    })
    _emit({
        "event": "step_update",
        "step_update": {
            "step_index": step + 2,
            "state": "DONE",
            "step_type": "tool",
            "tool_name": "run_command",
            "tool_info": {"name": "run_command", "output": "hi\r\n"},
        },
    })

    # Tool tien do qua MCP: plan_update (danh cho test do tien to ten tool MCP
    # agy thuc su in ra, muc 1b cua thiet ke — fake nay dung tien to doan
    # sandbox__ lam vi du, test backend thuc te se do agy that rieng)
    _emit({
        "event": "step_update",
        "step_update": {
            "step_index": step + 3,
            "state": "ACTIVE",
            "step_type": "tool",
            "tool_name": "sandbox__plan_update",
            "tool_info": {
                "name": "sandbox__plan_update",
                "parameters": {"steps": [{"id": "1", "status": "running"}], "reflection": ""},
            },
        },
    })
    _emit({
        "event": "step_update",
        "step_update": {
            "step_index": step + 3,
            "state": "DONE",
            "step_type": "tool",
            "tool_name": "sandbox__plan_update",
            "tool_info": {"name": "sandbox__plan_update", "output": "Da ghi nhan plan_update (1 buoc)."},
            "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        },
    })

    if MODE == "demo" and turn_index == 1:
        url, summary_path = _demo_browser_and_file()
        _emit({
            "event": "step_update",
            "step_update": {
                "step_index": step + 5,
                "state": "ACTIVE",
                "step_type": "tool",
                "tool_name": "browser_navigate",
                "tool_info": {"name": "browser_navigate", "parameters": {"url": url}},
            },
        })
        _emit({
            "event": "step_update",
            "step_update": {
                "step_index": step + 5,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": "browser_navigate",
                "tool_info": {"name": "browser_navigate", "output": f"Da mo {url}"},
            },
        })
        _emit({
            "event": "step_update",
            "step_update": {
                "step_index": step + 6,
                "state": "ACTIVE",
                "step_type": "tool",
                "tool_name": "file_write",
                "tool_info": {"name": "file_write", "parameters": {"file": summary_path}},
            },
        })
        _emit({
            "event": "step_update",
            "step_update": {
                "step_index": step + 6,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": "file_write",
                "tool_info": {"name": "file_write", "output": "Da ghi file."},
            },
        })

    if MODE == "ask" and turn_index == ASK_AT_TURN:
        _emit({
            "event": "step_update",
            "step_update": {
                "step_index": step + 4,
                "state": "ACTIVE",
                "step_type": "tool",
                "tool_name": "sandbox__message_ask_user",
                "tool_info": {
                    "name": "sandbox__message_ask_user",
                    "parameters": {"text": "Ban muon tiep tuc khong?"},
                },
            },
        })
        _emit({
            "event": "step_update",
            "step_update": {
                "step_index": step + 4,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": "sandbox__message_ask_user",
                "tool_info": {"name": "sandbox__message_ask_user", "output": "Da ghi nhan, dang cho."},
            },
        })
        # Dung ngu nghia 1.5: KHONG phat result cho luot nay. Tien trinh VAN
        # SONG va tiep tuc doc dong stdin ke tiep (luot tra loi) trong vong
        # lap main() — khong sleep/block o day.
        return

    if MODE == "error":
        _emit({
            "event": "result",
            "result": {
                "conversation_id": CONVERSATION_ID,
                "status": "ERROR",
                "response": "",
                "error": "authentication failed or timed out",
                "duration_seconds": 0,
                "num_turns": turn_index,
                "usage": {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "cache_read_tokens": 0, "total_tokens": 0},
            },
        })
        return

    _emit({
        "event": "result",
        "result": {
            "conversation_id": CONVERSATION_ID,
            "status": "SUCCESS",
            "response": "OK\n",
            "duration_seconds": 0.01,
            "num_turns": turn_index,
            "usage": {
                "input_tokens": 13441,
                "output_tokens": 10,
                "thinking_tokens": 0,
                "cache_read_tokens": 0,
                "total_tokens": 13451,
            },
        },
    })


def main() -> None:
    turn_index = 0
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("event") != "user":
            continue
        turn_index += 1
        _handle_turn(turn_index)


if __name__ == "__main__":
    main()
