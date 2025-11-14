#  test_server.py
#
#  Copyright (c) 2025 Junpei Kawamoto
#
#  This software is released under the MIT License.
#
#  http://opensource.org/licenses/mit-license.php

import asyncio
import json
import random
from asyncio.subprocess import Process
from pathlib import Path
from typing import Generator, Tuple, AsyncGenerator, Any
from unittest.mock import patch, MagicMock
from urllib.parse import urlparse, parse_qs, urlencode, quote

import pytest
from mcp.server import FastMCP
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.context import RequestContext

from mcp_bear import server, AppContext, BASE_URL, Note, NoteID, NoteInfo, ModifiedNote
from mcp_bear.cli import generate_file_suffix

BEAR_TOKEN = "abcdefg"


def _encode_tags(obj: dict) -> dict:
    if "tags" in obj:
        obj["tags"] = json.dumps(obj["tags"])
    return obj


@pytest.fixture
def temp_socket() -> Generator[Path, None, None]:
    while True:
        uds = Path("/tmp").joinpath(f"mcp-bear-{generate_file_suffix()}.sock")
        if not uds.exists():
            break
    yield uds


@pytest.fixture
async def mcp_server(temp_socket: Path) -> AsyncGenerator[Tuple[FastMCP, Context[Any, AppContext]], None]:
    s = server(BEAR_TOKEN, temp_socket)
    async with s._mcp_server.lifespan(s) as lifespan_context:  # type: ignore
        # noinspection PyTypeChecker
        ctx = Context(
            request_context=RequestContext(  # type: ignore
                request_id=random.randint(1, 100),
                meta=None,
                session=None,
                lifespan_context=lifespan_context,
                request=None,
            )
        )

        yield s, ctx


@pytest.fixture
def mock_create_subprocess_exec() -> Generator[MagicMock, None, None]:
    original_exec = asyncio.create_subprocess_exec

    with patch("asyncio.create_subprocess_exec") as mock_exec:

        async def side_effect(cmd: str, *args: str, **_kwargs: Any) -> Process:
            queries = parse_qs(urlparse(args[2]).query)
            callback_url = (queries.get("x-success") or [""])[0]

            return await original_exec(
                cmd, args[0], args[1], f"{callback_url}?{urlencode(mock_exec.stubbed_queries, quote_via=quote)}"
            )

        mock_exec.side_effect = side_effect
        yield mock_exec


@pytest.fixture
def mock_create_subprocess_exec_error() -> Generator[MagicMock, None, None]:
    original_exec = asyncio.create_subprocess_exec

    with patch("asyncio.create_subprocess_exec") as mock_exec:

        async def side_effect(cmd: str, *args: str, **_kwargs: Any) -> Process:
            queries = parse_qs(urlparse(args[2]).query)
            callback_url = (queries.get("x-error") or [""])[0]
            params = {"error-Code": "499", "errorMessage": "test error message"}

            return await original_exec(cmd, args[0], args[1], f"{callback_url}?{urlencode(params, quote_via=quote)}")

        mock_exec.side_effect = side_effect
        yield mock_exec


@pytest.fixture
def mock_requests_get() -> Generator[MagicMock, None, None]:
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"mocked http request"
        mock_get.return_value = mock_response
        yield mock_get


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments", [{"id": "1234567890"}, {"title": "test note"}, {"id": "1234567890", "title": "test note"}]
)
async def test_open_note(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
) -> None:
    s, ctx = mcp_server
    expect = Note(
        note="test note" * 16 * 1024,  # > 16KB
        identifier="1234567890",
        title="test note",
        tags=["a", "b"],
        modificationDate="2023-01-01T00:00:00Z",
        creationDate="2023-01-01T00:00:00Z",
    )
    mock_create_subprocess_exec.stubbed_queries = _encode_tags(expect.model_dump())

    res = await s._tool_manager.call_tool("open_note", arguments=arguments, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "new_window": "no",
        "float": "no",
        "show_window": "no",
        "open_note": "no",
        "selected": "no",
        "edit": "no",
        **arguments,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/open-note?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_open_note_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("open_note", arguments={"id": "1234567890", "title": "test note"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments,expect_req_params",
    [
        ({"text": "test note"}, {"text": "test note"}),
        ({"title": "test title", "text": "test note"}, {"title": "test title", "text": "test note"}),
        ({"title": "test title", "text": "# test title\ntest note"}, {"title": "test title", "text": "\ntest note"}),
        (
            {"title": "test title", "text": "test note", "tags": ["a", "b"]},
            {"title": "test title", "text": "test note", "tags": "a,b"},
        ),
        (
            {"title": "test title", "text": "test note", "timestamp": True},
            {"title": "test title", "text": "test note", "timestamp": "yes"},
        ),
    ],
)
async def test_create(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
    expect_req_params: dict,
) -> None:
    s, ctx = mcp_server
    expect = NoteID(identifier="1234567890", title="test title")
    mock_create_subprocess_exec.stubbed_queries = expect.model_dump()

    res = await s._tool_manager.call_tool("create", arguments=arguments, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "open_note": "no",
        "new_window": "no",
        "float": "no",
        "show_window": "no",
        **expect_req_params,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/create?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_create_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("create", arguments={"text": "test note"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments,expect_req_params",
    [
        ({"id": "123456"}, {"id": "123456"}),
        ({"text": "test note"}, {"text": "test note"}),
        (
            {"title": "test title", "text": "test note"},
            {
                "text": "test note",
                "title": "test title",
            },
        ),
        (
            {"title": "test title", "text": "test note", "tags": ["a", "b"]},
            {"text": "test note", "title": "test title", "tags": "a,b"},
        ),
        (
            {"title": "test title", "text": "test note", "timestamp": True},
            {"text": "test note", "title": "test title", "timestamp": "yes"},
        ),
    ],
)
async def test_replace_note(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
    expect_req_params: dict,
) -> None:
    s, ctx = mcp_server
    expect = ModifiedNote(note="updated note", title="test title")
    mock_create_subprocess_exec.stubbed_queries = expect.model_dump()

    res = await s._tool_manager.call_tool("replace_note", arguments=arguments, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "mode": "replace_all" if "title" in arguments else "replace",
        "open_note": "no",
        "new_window": "no",
        "show_window": "no",
        "edit": "no",
        **expect_req_params,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/add-text?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_replace_note_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("replace_note", arguments={"id": "123456", "text": "new text"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "argument,expect",
    [
        ("title", "# title"),
        ("# title", "# title"),
    ],
)
async def test_add_title(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    argument: str,
    expect: str,
) -> None:
    s, ctx = mcp_server
    mock_create_subprocess_exec.stubbed_queries = {}

    await s._tool_manager.call_tool("add_title", arguments={"id": "123", "title": argument}, context=ctx)
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "id": "123",
        "text": expect,
        "mode": "prepend",
        "open_note": "no",
        "new_window": "no",
        "show_window": "no",
        "edit": "no",
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/add-text?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_add_title_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("add_title", arguments={"id": "123456", "title": "new title"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments,expect_req_params",
    [
        (
            {"id": "123456", "file": "dGVzdA==", "filename": "test.txt"},
            {"file": "dGVzdA==", "filename": "test.txt", "id": "123456"},
        ),
        (
            {"title": "sample note", "file": "dGVzdA==", "filename": "test.txt"},
            {
                "file": "dGVzdA==",
                "filename": "test.txt",
                "title": "sample note",
            },
        ),
        (
            {"id": "123456", "file": "dGVzdA==", "filename": "test.txt", "header": "supplement"},
            {
                "file": "dGVzdA==",
                "filename": "test.txt",
                "id": "123456",
                "header": "supplement",
            },
        ),
        (
            {"id": "123456", "file": "dGVzdA==", "filename": "test.txt", "mode": "prepend"},
            {
                "file": "dGVzdA==",
                "filename": "test.txt",
                "id": "123456",
                "mode": "prepend",
            },
        ),
    ],
)
async def test_add_file(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
    expect_req_params: dict,
) -> None:
    s, ctx = mcp_server
    mock_create_subprocess_exec.stubbed_queries = {}

    await s._tool_manager.call_tool("add_file", arguments=arguments, context=ctx)
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "selected": "no",
        "open_note": "no",
        "new_window": "no",
        "show_window": "no",
        "edit": "no",
        **expect_req_params,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/add-file?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments,expect_req_params",
    [
        (
            {"id": "123456", "file": "http://example.com", "filename": "test.txt"},
            {
                "file": "bW9ja2VkIGh0dHAgcmVxdWVzdA==",
                "filename": "test.txt",
                "id": "123456",
            },
        ),
        (
            {"title": "sample note", "file": "https://example.com", "filename": "test.txt"},
            {
                "file": "bW9ja2VkIGh0dHAgcmVxdWVzdA==",
                "filename": "test.txt",
                "title": "sample note",
            },
        ),
    ],
)
async def test_add_file_http_request(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    mock_requests_get: MagicMock,
    arguments: dict,
    expect_req_params: dict,
) -> None:
    s, ctx = mcp_server
    mock_create_subprocess_exec.stubbed_queries = {}

    await s._tool_manager.call_tool("add_file", arguments=arguments, context=ctx)
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "selected": "no",
        "open_note": "no",
        "new_window": "no",
        "show_window": "no",
        "edit": "no",
        **expect_req_params,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/add-file?{urlencode(req_params, quote_via=quote)}"
    )
    mock_requests_get.assert_called_once_with(arguments["file"])


@pytest.mark.anyio
async def test_add_file_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("add_file", arguments={"file": "dGVzdA==", "filename": "test.txt"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
async def test_tags(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
) -> None:
    s, ctx = mcp_server

    mock_create_subprocess_exec.stubbed_queries = {
        "tags": json.dumps(
            [
                {"name": "a"},
                {"name": "b"},
                {"name": "c"},
            ]
        )
    }

    res = await s._tool_manager.call_tool("tags", arguments={}, context=ctx)
    assert res == ["a", "b", "c"]
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "token": BEAR_TOKEN,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/tags?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_tags_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("tags", arguments={}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
async def test_open_tag(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
) -> None:
    s, ctx = mcp_server
    expect = [
        NoteInfo(
            title="note a",
            identifier="1",
            tags=["test", "data"],
            modificationDate="2023-01-01T00:00:00Z",
            creationDate="2023-01-01T00:00:00Z",
        ),
        NoteInfo(
            title="note b", identifier="2", modificationDate="2023-01-01T00:00:00Z", creationDate="2023-01-01T00:00:00Z"
        ),
    ]

    mock_create_subprocess_exec.stubbed_queries = {
        "notes": json.dumps([info.model_dump() for info in expect]),
    }

    res = await s._tool_manager.call_tool("open_tag", arguments={"name": "test_tag"}, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "name": "test_tag",
        "token": BEAR_TOKEN,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/open-tag?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_open_tag_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("open_tag", arguments={"name": "a"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
async def test_rename_tag(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
) -> None:
    s, ctx = mcp_server
    mock_create_subprocess_exec.stubbed_queries = {}

    await s._tool_manager.call_tool("rename_tag", arguments={"name": "old name", "new_name": "new name"}, context=ctx)
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "name": "old name",
        "new_name": "new name",
        "show_window": "no",
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/rename-tag?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_rename_tag_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool(
            "rename_tag", arguments={"name": "old name", "new_name": "new name"}, context=ctx
        )

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
async def test_delete_tag(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
) -> None:
    s, ctx = mcp_server
    mock_create_subprocess_exec.stubbed_queries = {}

    await s._tool_manager.call_tool("delete_tag", arguments={"name": "tag name"}, context=ctx)
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "name": "tag name",
        "show_window": "no",
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/delete-tag?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_delete_tag_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("delete_tag", arguments={"name": "tag name"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments", [{"id": "1234567890"}, {"search": "test note"}, {"id": "1234567890", "search": "test note"}]
)
async def test_trash(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
) -> None:
    s, ctx = mcp_server
    mock_create_subprocess_exec.stubbed_queries = {}

    await s._tool_manager.call_tool("trash", arguments=arguments, context=ctx)
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "show_window": "no",
        **arguments,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/trash?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_trash_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("trash", arguments={"search": "tag name"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments", [{"id": "1234567890"}, {"search": "test note"}, {"id": "1234567890", "search": "test note"}]
)
async def test_archive(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
) -> None:
    s, ctx = mcp_server
    mock_create_subprocess_exec.stubbed_queries = {}

    await s._tool_manager.call_tool("archive", arguments=arguments, context=ctx)
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "show_window": "no",
        **arguments,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/archive?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_archive_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("archive", arguments={"search": "tag name"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("arguments", [{}, {"search": "keyword"}])
async def test_untagged(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
) -> None:
    s, ctx = mcp_server
    expect = [
        NoteInfo(
            title="note a",
            identifier="1",
            tags=["test", "data"],
            modificationDate="2023-01-01T00:00:00Z",
            creationDate="2023-01-01T00:00:00Z",
        ),
        NoteInfo(
            title="note b", identifier="2", modificationDate="2023-01-01T00:00:00Z", creationDate="2023-01-01T00:00:00Z"
        ),
    ]

    mock_create_subprocess_exec.stubbed_queries = {"notes": json.dumps([info.model_dump() for info in expect])}

    res = await s._tool_manager.call_tool("untagged", arguments=arguments, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "show_window": "no",
        "token": BEAR_TOKEN,
        **arguments,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/untagged?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_untagged_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("untagged", arguments={}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("arguments", [{}, {"search": "keyword"}])
async def test_todo(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
) -> None:
    s, ctx = mcp_server
    expect = [
        NoteInfo(
            title="note a",
            identifier="1",
            tags=["test", "data"],
            modificationDate="2023-01-01T00:00:00Z",
            creationDate="2023-01-01T00:00:00Z",
        ),
        NoteInfo(
            title="note b", identifier="2", modificationDate="2023-01-01T00:00:00Z", creationDate="2023-01-01T00:00:00Z"
        ),
    ]

    mock_create_subprocess_exec.stubbed_queries = {"notes": json.dumps([info.model_dump() for info in expect])}

    res = await s._tool_manager.call_tool("todo", arguments=arguments, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "show_window": "no",
        "token": BEAR_TOKEN,
        **arguments,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/todo?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_todo_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("todo", arguments={}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("arguments", [{}, {"search": "keyword"}])
async def test_today(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
) -> None:
    s, ctx = mcp_server
    expect = [
        NoteInfo(
            title="note a",
            identifier="1",
            tags=["test", "data"],
            modificationDate="2023-01-01T00:00:00Z",
            creationDate="2023-01-01T00:00:00Z",
        ),
        NoteInfo(
            title="note b", identifier="2", modificationDate="2023-01-01T00:00:00Z", creationDate="2023-01-01T00:00:00Z"
        ),
    ]

    mock_create_subprocess_exec.stubbed_queries = {"notes": json.dumps([info.model_dump() for info in expect])}

    res = await s._tool_manager.call_tool("today", arguments=arguments, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "show_window": "no",
        "token": BEAR_TOKEN,
        **arguments,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/today?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_today_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("today", arguments={}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("arguments", [{}, {"search": "keyword"}])
async def test_locked(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
) -> None:
    s, ctx = mcp_server
    expect = [
        NoteInfo(
            title="note a",
            identifier="1",
            tags=["test", "data"],
            modificationDate="2023-01-01T00:00:00Z",
            creationDate="2023-01-01T00:00:00Z",
        ),
        NoteInfo(
            title="note b", identifier="2", modificationDate="2023-01-01T00:00:00Z", creationDate="2023-01-01T00:00:00Z"
        ),
    ]

    mock_create_subprocess_exec.stubbed_queries = {"notes": json.dumps([info.model_dump() for info in expect])}

    res = await s._tool_manager.call_tool("locked", arguments=arguments, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "show_window": "no",
        "token": BEAR_TOKEN,
        **arguments,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/locked?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_locked_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("locked", arguments={}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments", [{"term": "1234567890"}, {"tag": "test note"}, {"term": "1234567890", "tag": "test note"}]
)
async def test_search(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    arguments: dict,
) -> None:
    s, ctx = mcp_server
    expect = [
        NoteInfo(
            title="note a",
            identifier="1",
            tags=["test", "data"],
            modificationDate="2023-01-01T00:00:00Z",
            creationDate="2023-01-01T00:00:00Z",
        ),
        NoteInfo(
            title="note b", identifier="2", modificationDate="2023-01-01T00:00:00Z", creationDate="2023-01-01T00:00:00Z"
        ),
    ]

    mock_create_subprocess_exec.stubbed_queries = {"notes": json.dumps([info.model_dump() for info in expect])}

    res = await s._tool_manager.call_tool("search", arguments=arguments, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    req_params = {
        "show_window": "no",
        "token": BEAR_TOKEN,
        **arguments,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/search?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_search_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("search", arguments={"tags": "tag"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("tags", [None, ["tag 1"], ["tag 1", "tag 2"]])
async def test_grab_url(
    temp_socket: Path,
    mcp_server: Tuple[FastMCP, Context],
    mock_create_subprocess_exec: MagicMock,
    tags: list[str] | None,
) -> None:
    s, ctx = mcp_server
    expect = NoteID(identifier="1234567890", title="test title")

    mock_create_subprocess_exec.stubbed_queries = expect.model_dump()

    arguments: dict[str, Any] = {"url": "https://bear.app"}
    arguments.update({"tags": tags} if tags else {})

    res = await s._tool_manager.call_tool("grab_url", arguments=arguments, context=ctx)
    assert res == expect
    assert len(ctx.request_context.lifespan_context.futures) == 0

    additional_params = {"tags": ",".join(tags)} if tags else {}
    req_params = {
        "url": "https://bear.app",
        **additional_params,
        "x-success": f"xfwder://{temp_socket.stem}/{ctx.request_id}/success",
        "x-error": f"xfwder://{temp_socket.stem}/{ctx.request_id}/error",
    }
    mock_create_subprocess_exec.assert_called_once_with(
        "open", "-g", "-j", f"{BASE_URL}/grab-url?{urlencode(req_params, quote_via=quote)}"
    )


@pytest.mark.anyio
async def test_grab_url_failed(
    mcp_server: Tuple[FastMCP, Context[Any, AppContext]], mock_create_subprocess_exec_error: MagicMock
) -> None:
    s, ctx = mcp_server
    with pytest.raises(ToolError) as excinfo:
        await s._tool_manager.call_tool("grab_url", arguments={"url": "https://bear.app"}, context=ctx)

    assert "test error message" in str(excinfo.value)
    assert len(ctx.request_context.lifespan_context.futures) == 0
