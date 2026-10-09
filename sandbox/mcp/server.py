"""
MCP server chạy trong máy nhiệm vụ (sandbox) — Issue #29 / docs/spec/02-mcp-trong-sandbox.md.

Phơi 25 tool cho CLI engine (agy / Claude Code) qua transport streamable-http
(bind 127.0.0.1:8081, không expose ra ngoài container) + stdio (lối vào thứ
hai, rẻ, dùng chung implementation).

CÁCH CHẠY (xem supervisord.conf, program mcp):
    cd /app && /app/.venv/bin/python mcp/server.py            # streamable-http (mac dinh)
    cd /app && /app/.venv/bin/python mcp/server.py --stdio    # stdio

QUAN TRỌNG: chạy bằng đường dẫn script tương đối (`mcp/server.py`) từ cwd
`/app`, KHÔNG dùng `python -m` và KHÔNG thêm `/app` vào PYTHONPATH — xem giải
thích trong config.py. Nếu chạy sai cách, `import mcp` (SDK) có thể bị che
bởi chính thư mục này.
"""
import argparse
import logging
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from config import MCP_HOST, MCP_PORT
import rest_client
import browser_tools
import progress

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("gen_agents.mcp.server")

mcp = FastMCP(
    "gen-agents-sandbox",
    host=MCP_HOST,
    port=MCP_PORT,
    instructions=(
        "Tool cho agent CLI chay trong may nhiem vu Gen-Agents: shell/file qua "
        "tool API noi bo, browser qua CDP Chrome (screenshot + toa do, khong co "
        "cay [index]), va 3 tool bao cao tien do/hoi nguoi dung."
    ),
)

# ---------------------------------------------------------------------------
# Shell (5 tool)
# ---------------------------------------------------------------------------


@mcp.tool(
    structured_output=False,
    description="Execute commands in a specified shell session. Use for running code, installing packages, or managing files.",
)
async def shell_exec(command: str, id: Optional[str] = None, exec_dir: Optional[str] = None) -> dict:
    """
    Args:
        command: Shell command to execute.
        id: Unique identifier of the target shell session; if not provided, one will be auto-created.
        exec_dir: Working directory for command execution (must use absolute path).
    """
    return await rest_client.shell_exec(id, exec_dir, command)


@mcp.tool(
    structured_output=False,
    description="View the content of a specified shell session. Use for checking command execution results or monitoring output.",
)
async def shell_view(id: str) -> dict:
    """
    Args:
        id: Unique identifier of the target shell session.
    """
    return await rest_client.shell_view(id)


@mcp.tool(
    structured_output=False,
    description="Wait for the running process in a specified shell session to return. Use after running commands that require longer runtime.",
)
async def shell_wait(id: str, seconds: Optional[int] = None) -> dict:
    """
    Args:
        id: Unique identifier of the target shell session.
        seconds: Wait duration in seconds.
    """
    return await rest_client.shell_wait(id, seconds)


@mcp.tool(
    structured_output=False,
    description="Write input to a running process in a specified shell session. Use for responding to interactive command prompts.",
)
async def shell_write_to_process(id: str, input: str, press_enter: bool) -> dict:
    """
    Args:
        id: Unique identifier of the target shell session.
        input: Input content to write to the process.
        press_enter: Whether to press Enter key after input.
    """
    return await rest_client.shell_write_to_process(id, input, press_enter)


@mcp.tool(
    structured_output=False,
    description="Terminate a running process in a specified shell session. Use for stopping long-running processes or handling frozen commands.",
)
async def shell_kill_process(id: str) -> dict:
    """
    Args:
        id: Unique identifier of the target shell session.
    """
    return await rest_client.shell_kill_process(id)


# ---------------------------------------------------------------------------
# File (5 tool)
# ---------------------------------------------------------------------------


@mcp.tool(
    structured_output=False,
    description="Read file content. Use for checking file contents, analyzing logs, or reading configuration files.",
)
async def file_read(
    file: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    sudo: bool = False,
) -> dict:
    """
    Args:
        file: Absolute path of the file to read.
        start_line: Starting line to read from, 0-based. If not specified, starts from the beginning.
        end_line: Ending line number (exclusive). If not specified, reads to the end of the file.
        sudo: Whether to use sudo privileges.
    """
    return await rest_client.file_read(file, start_line, end_line, sudo)


@mcp.tool(
    structured_output=False,
    description="Overwrite or append content to a file. Use for creating new files, appending content, or modifying existing files.",
)
async def file_write(
    file: str,
    content: str,
    append: bool = False,
    leading_newline: bool = False,
    trailing_newline: bool = False,
    sudo: bool = False,
) -> dict:
    """
    Args:
        file: Absolute path of the file to write to.
        content: Text content to write.
        append: Whether to use append mode.
        leading_newline: Whether to add a leading newline.
        trailing_newline: Whether to add a trailing newline.
        sudo: Whether to use sudo privileges.
    """
    return await rest_client.file_write(file, content, append, leading_newline, trailing_newline, sudo)


@mcp.tool(
    structured_output=False,
    description="Replace specified string in a file. Use for updating specific content in files or fixing errors in code.",
)
async def file_str_replace(file: str, old_str: str, new_str: str, sudo: bool = False) -> dict:
    """
    Args:
        file: Absolute path of the file to perform replacement on.
        old_str: Original string to be replaced.
        new_str: New string to replace with.
        sudo: Whether to use sudo privileges.
    """
    return await rest_client.file_str_replace(file, old_str, new_str, sudo)


@mcp.tool(
    structured_output=False,
    description="Search for matching text within file content. Use for finding specific content or patterns in files.",
)
async def file_find_in_content(file: str, regex: str, sudo: bool = False) -> dict:
    """
    Args:
        file: Absolute path of the file to search within.
        regex: Regular expression pattern to match.
        sudo: Whether to use sudo privileges.
    """
    return await rest_client.file_find_in_content(file, regex, sudo)


@mcp.tool(
    structured_output=False,
    description="Find files by name pattern in specified directory. Use for locating files with specific naming patterns.",
)
async def file_find_by_name(path: str, glob: str) -> dict:
    """
    Args:
        path: Absolute path of directory to search.
        glob: Filename pattern using glob syntax wildcards.
    """
    return await rest_client.file_find_by_name(path, glob)


# ---------------------------------------------------------------------------
# Browser (12 tool) — xem browser_tools.py
# ---------------------------------------------------------------------------

mcp.tool(
    structured_output=False, description="View content of the current browser page (screenshot + url + title).")(
    browser_tools.browser_view
)
mcp.tool(
    structured_output=False, description="Navigate browser to specified URL.")(browser_tools.browser_navigate)
mcp.tool(
    structured_output=False,
    description="Open a fresh tab and navigate to specified URL (reset page state; does not kill the shared Chrome process)."
)(browser_tools.browser_restart)
mcp.tool(
    structured_output=False, description="Click an element on the current browser page by selector, visible text, or coordinate.")(
    browser_tools.browser_click
)
mcp.tool(
    structured_output=False, description="Overwrite text in an editable element by selector or coordinate.")(browser_tools.browser_input)
mcp.tool(
    structured_output=False, description="Move mouse cursor to a position on the current page.")(browser_tools.browser_move_mouse)
mcp.tool(
    structured_output=False, description="Simulate a key press on the current browser page.")(browser_tools.browser_press_key)
mcp.tool(
    structured_output=False, description="Select an option (by index) from a dropdown element matched by CSS selector.")(
    browser_tools.browser_select_option
)
mcp.tool(
    structured_output=False, description="Scroll the current browser page up.")(browser_tools.browser_scroll_up)
mcp.tool(
    structured_output=False, description="Scroll the current browser page down.")(browser_tools.browser_scroll_down)
mcp.tool(
    structured_output=False, description="Execute JavaScript code in the browser console of the current page.")(
    browser_tools.browser_console_exec
)
mcp.tool(
    structured_output=False, description="View browser console output of the current page.")(browser_tools.browser_console_view)


# ---------------------------------------------------------------------------
# Tiến độ & hỏi người dùng (3 tool) — xem progress.py
# ---------------------------------------------------------------------------

mcp.tool(
    structured_output=False,
    description="Update authoritative plan step statuses for the Plan panel. Call after finishing/starting a planned step."
)(progress.plan_update)
mcp.tool(
    structured_output=False,
    description="Ask the user a question and wait for a response. Use only when blocked without user input."
)(progress.message_ask_user)
mcp.tool(
    structured_output=False,
    description="Send a one-sentence progress/notification message to the user, no response required."
)(progress.message_notify_user)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gen-Agents sandbox MCP server")
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Chay qua stdio thay vi streamable-http (lam loi vao thu hai, dung chung tool).",
    )
    args = parser.parse_args()

    if args.stdio:
        logger.info("Khoi dong MCP server qua stdio (25 tool)")
        mcp.run(transport="stdio")
    else:
        logger.info("Khoi dong MCP server qua streamable-http tai http://%s:%s/mcp (25 tool)", MCP_HOST, MCP_PORT)
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
