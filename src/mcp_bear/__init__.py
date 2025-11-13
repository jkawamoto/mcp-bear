#  __init__.py
#
#  Copyright (c) 2025 Junpei Kawamoto
#
#  This software is released under the MIT License.
#
#  http://opensource.org/licenses/mit-license.php
import asyncio
import base64
import json
import logging
import os
from asyncio import Future
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import cast, AsyncIterator, Final, Any, Mapping, Literal
from urllib.parse import urlencode, quote

import requests
from fastapi import FastAPI, Request, HTTPException
from mcp.server import FastMCP
from mcp.server.fastmcp import Context
from pydantic import Field, BaseModel
from starlette.datastructures import QueryParams
from uvicorn import Config, Server
from uvicorn.config import LOGGING_CONFIG

BASE_URL = "bear://x-callback-url"

LOGGER = logging.getLogger(__name__)


@dataclass
class ErrorResponse(Exception):
    errorCode: int
    errorMessage: str

    def __str__(self) -> str:
        return self.errorMessage


@dataclass
class AppContext:
    futures: dict[str, Future[QueryParams]]


@asynccontextmanager
async def app_lifespan(_server: FastMCP, uds: Path) -> AsyncIterator[AppContext]:
    callback = FastAPI()
    futures: dict[str, Future[QueryParams]] = {}

    @callback.post("/{req_id}/success", status_code=HTTPStatus.NO_CONTENT, include_in_schema=False)
    def success(req_id: str, req: Request) -> None:
        if req_id not in futures:
            raise HTTPException(status_code=404, detail="Request not found")

        futures[req_id].set_result(req.query_params)

    @callback.post("/{req_id}/error", status_code=HTTPStatus.NO_CONTENT, include_in_schema=False)
    def error(req_id: str, req: Request) -> None:
        if req_id not in futures:
            raise HTTPException(status_code=404, detail="Request not found")

        q = req.query_params
        futures[req_id].set_exception(
            ErrorResponse(
                errorCode=int(q.get("error-Code") or "0"),
                errorMessage=q.get("errorMessage") or "",
            )
        )

    log_config = deepcopy(LOGGING_CONFIG)
    log_config["handlers"]["access"]["stream"] = "ext://sys.stderr"
    server = Server(
        Config(
            app=callback,
            uds=str(uds),
            log_level="warning",
            log_config=log_config,
            h11_max_incomplete_event_size=1024 * 1024,  # 1MB
        )
    )

    LOGGER.info(f"Starting callback server on {uds}")
    server_task = asyncio.create_task(server.serve())
    try:
        yield AppContext(futures=futures)
    finally:
        LOGGER.info("Stopping callback server")
        server.should_exit = True
        await server_task

        if uds.exists():
            os.unlink(uds)


class Note(BaseModel):
    """Note model."""

    note: str = Field(description="note text")
    identifier: str = Field(description="note unique identifier")
    title: str = Field(description="note title")
    tags: list[str] | None = Field(description="list of tags", default=None)
    is_trashed: str = Field(description="yes if the note is trashed", default="no")
    modificationDate: str = Field(description="note modification date in ISO 8601 format")
    creationDate: str = Field(description="note creation date in ISO 8601 format")


class NoteID(BaseModel):
    """Note identifier."""

    identifier: str = Field(description="note unique identifier")
    title: str = Field(description="note title")


class NoteInfo(BaseModel):
    """Note information."""

    title: str = Field(description="note title")
    identifier: str = Field(description="note unique identifier")
    tags: list[str] | None = Field(description="list of tags", default=None)
    modificationDate: str = Field(description="note modification date in ISO 8601 format")
    creationDate: str = Field(description="note creation date in ISO 8601 format")
    pin: str = Field(description="note pin status", default="no")


class ModifiedNote(BaseModel):
    """Modified note."""

    note: str = Field(description="note text")
    title: str = Field(description="note title")


def server(token: str, uds: Path) -> FastMCP:
    mcp = FastMCP("Bear", lifespan=partial(app_lifespan, uds=uds))

    async def _request(
        ctx: Context[Any, AppContext],
        path: str,
        params: dict[str, str],
    ) -> QueryParams:
        req_id = ctx.request_id
        params = {
            **params,
            "x-success": f"xfwder://{uds.stem}/{req_id}/success",
            "x-error": f"xfwder://{uds.stem}/{req_id}/error",
        }

        future = Future[QueryParams]()
        ctx.request_context.lifespan_context.futures[req_id] = future
        try:
            proc = await asyncio.create_subprocess_exec(
                "open",
                "-g",
                "-j",
                f"{BASE_URL}/{path}?{urlencode(params, quote_via=quote)}",
            )
            returncode = await proc.wait()
            if returncode != 0:
                raise RuntimeError(f"failed to open Bear (exit code: {returncode}).")
            return await future

        finally:
            del ctx.request_context.lifespan_context.futures[req_id]

    @mcp.tool()
    async def open_note(
        ctx: Context[Any, AppContext],
        id: str | None = Field(description="note unique identifier", default=None),
        title: str | None = Field(description="note title", default=None),
    ) -> Note:
        """Open a note identified by its title or id and return its content."""
        params = {
            "new_window": "no",
            "float": "no",
            "show_window": "no",
            "open_note": "no",
            "selected": "no",
            # Removed "pin": "no" to preserve existing pin status
            "edit": "no",
        }
        if id is not None:
            params["id"] = id
        if title is not None:
            params["title"] = title

        return Note.model_validate(_fix_tags(await _request(ctx, "open-note", params)))

    @mcp.tool()
    async def create(
        ctx: Context[Any, AppContext],
        title: str | None = Field(description="note title", default=None),
        text: str | None = Field(description="note body", default=None),
        tags: list[str] | None = Field(description="list of tags", default=None),
        timestamp: bool = Field(description="prepend the current date and time to the text", default=False),
    ) -> NoteID:
        """Create a new note and return its unique identifier. Empty notes are not allowed."""
        params = {
            "open_note": "no",
            "new_window": "no",
            "float": "no",
            "show_window": "no",
        }
        if title is not None:
            params["title"] = title
        if text is not None:
            if title:
                # remove the title from the note text to avoid being duplicated
                text = text.removeprefix("# " + title)
            params["text"] = text
        if tags is not None:
            params["tags"] = ",".join(tags)
        if timestamp:
            params["timestamp"] = "yes"

        return NoteID.model_validate(await _request(ctx, "create", params))

    @mcp.tool()
    async def replace_note(
        ctx: Context[Any, AppContext],
        id: str | None = Field(description="note unique identifier", default=None),
        title: str | None = Field(description="new title for the note", default=None),
        text: str | None = Field(description="new text to replace note content", default=None),
        tags: list[str] | None = Field(description="list of tags to add to the note", default=None),
        timestamp: bool = Field(description="prepend the current date and time to the text", default=False),
    ) -> ModifiedNote:
        """Replace the content of an existing note identified by its id."""
        mode = "replace_all" if title is not None else "replace"
        params = {
            "mode": mode,
            "open_note": "no",
            "new_window": "no",
            "show_window": "no",
            "edit": "no",
        }
        if id is not None:
            params["id"] = id
        if text is not None:
            params["text"] = text
        if title is not None:
            params["title"] = title
        if tags is not None:
            params["tags"] = ",".join(tags)
        if timestamp:
            params["timestamp"] = "yes"

        return ModifiedNote.model_validate(await _request(ctx, "add-text", params))

    @mcp.tool()
    async def add_title(
        ctx: Context[Any, AppContext],
        id: str = Field(description="note unique identifier"),
        title: str = Field(description="new title for the note"),
    ) -> None:
        """Add a title to a note identified by its id."""
        if not title.startswith("# "):
            title = "# " + title
        params = {
            "id": id,
            "text": title,
            "mode": "prepend",
            "open_note": "no",
            "new_window": "no",
            "show_window": "no",
            "edit": "no",
        }
        await _request(ctx, "add-text", params)

    @mcp.tool()
    async def add_file(
        ctx: Context[Any, AppContext],
        id: str | None = Field(description="note unique identifier", default=None),
        title: str | None = Field(description="note title", default=None),
        file: str = Field(description="base64 representation of a file or a URL to a file to add to the note"),
        header: str | None = Field(
            description="if specified add the file to the corresponding header inside the note", default=None
        ),
        filename: str = Field(description="file name with extension"),
        mode: Literal["prepend", "append"] | None = Field(description="adding mode", default=None),
    ) -> None:
        """Append or prepend a file to a note identified by its title or id."""
        if file.startswith("http://") or file.startswith("https://"):
            res = requests.get(file)
            res.raise_for_status()
            file = base64.b64encode(res.content).decode("ascii")

        params = {
            "selected": "no",
            "open_note": "no",
            "new_window": "no",
            "show_window": "no",
            "edit": "no",
            "file": file,
            "filename": filename,
        }
        if id is not None:
            params["id"] = id
        if title is not None:
            params["title"] = title
        if header is not None:
            params["header"] = header
        if mode is not None:
            params["mode"] = mode

        await _request(ctx, "add-file", params)

    @mcp.tool()
    async def tags(
        ctx: Context[Any, AppContext],
    ) -> list[str]:
        """Return all the tags currently displayed in Bear’s sidebar."""
        params = {
            "token": token,
        }

        res = await _request(ctx, "tags", params)
        raw_tags = res.get("tags")
        if raw_tags is None:
            return []

        notes = cast(list[dict[str, str]], json.loads(raw_tags))
        return [note["name"] for note in notes if "name" in note]

    @mcp.tool()
    async def open_tag(
        ctx: Context[Any, AppContext],
        name: str = Field(description="tag name or a list of tags divided by comma"),
    ) -> list[NoteInfo]:
        """Show all the notes which have a selected tag in bear."""
        params = {
            "name": name,
            "token": token,
        }

        res = await _request(ctx, "open-tag", params)
        return parse_notes(res.get("notes"))

    @mcp.tool()
    async def rename_tag(
        ctx: Context[Any, AppContext],
        name: str = Field(description="tag name"),
        new_name: str = Field(description="new tag name"),
    ) -> None:
        """Rename an existing tag.

        This call can’t be performed if the app is a locked state.
        If the tag contains any locked note this call will not be performed.
        """
        params = {
            "name": name,
            "new_name": new_name,
            "show_window": "no",
        }

        await _request(ctx, "rename-tag", params)

    @mcp.tool()
    async def delete_tag(
        ctx: Context[Any, AppContext],
        name: str = Field(description="tag name"),
    ) -> None:
        """Delete an existing tag.

         This call can’t be performed if the app is a locked state.
        If the tag contains any locked note this call will not be performed.
        """
        params = {
            "name": name,
            "show_window": "no",
        }

        await _request(ctx, "delete-tag", params)

    async def move_note(ctx: Context[Any, AppContext], id: str | None, search: str | None, dest: str) -> None:
        """Move a note identified by its title or id to the given destination."""
        params = {
            "show_window": "no",
        }
        if id is not None:
            params["id"] = id
        if search is not None:
            params["search"] = search

        await _request(ctx, dest, params)

    @mcp.tool()
    async def trash(
        ctx: Context[Any, AppContext],
        id: str | None = Field(description="note unique identifier", default=None),
        search: str | None = Field(description="string to search.", default=None),
    ) -> None:
        """Move a note to bear trash and select the Trash sidebar item.

        This call can’t be performed if the app is a locked state. Encrypted notes can’t be used with this call.
        The search term is ignored if an id is provided.
        """
        await move_note(ctx, id, search, "trash")

    @mcp.tool()
    async def archive(
        ctx: Context[Any, AppContext],
        id: str | None = Field(description="note unique identifier", default=None),
        search: str | None = Field(description="string to search.", default=None),
    ) -> None:
        """Move a note to bear archive and select the Archive sidebar item.

        This call can’t be performed if the app is a locked state. Encrypted notes can’t be accessed with this call.
        The search term is ignored if an id is provided.
        """
        await move_note(ctx, id, search, "archive")

    async def sidebar_items(ctx: Context[Any, AppContext], kind: str, search: str | None) -> list[NoteInfo]:
        """List notes in the specified sidebar."""
        params = {
            "show_window": "no",
            "token": token,
        }
        if search is not None:
            params["search"] = search

        res = await _request(ctx, kind, params)
        return parse_notes(res.get("notes"))

    @mcp.tool()
    async def untagged(
        ctx: Context[Any, AppContext],
        search: str | None = Field(description="string to search", default=None),
    ) -> list[NoteInfo]:
        """Select the Untagged sidebar item."""
        return await sidebar_items(ctx, "untagged", search)

    @mcp.tool()
    async def todo(
        ctx: Context[Any, AppContext],
        search: str | None = Field(description="string to search", default=None),
    ) -> list[NoteInfo]:
        """Select the Todo sidebar item."""
        return await sidebar_items(ctx, "todo", search)

    @mcp.tool()
    async def today(
        ctx: Context[Any, AppContext],
        search: str | None = Field(description="string to search", default=None),
    ) -> list[NoteInfo]:
        """Select the Today sidebar item."""
        return await sidebar_items(ctx, "today", search)

    @mcp.tool()
    async def locked(
        ctx: Context[Any, AppContext],
        search: str | None = Field(description="string to search", default=None),
    ) -> list[NoteInfo]:
        """Select the Locked sidebar item."""
        return await sidebar_items(ctx, "locked", search)

    @mcp.tool()
    async def search(
        ctx: Context[Any, AppContext],
        term: str | None = Field(description="string to search", default=None),
        tag: str | None = Field(description="tag to search into", default=None),
    ) -> list[NoteInfo]:
        """Show search results in Bear for all notes or for a specific tag."""
        params = {
            "show_window": "no",
            "token": token,
        }
        if term is not None:
            params["term"] = term
        if tag is not None:
            params["tag"] = tag

        res = await _request(ctx, "search", params)
        return parse_notes(res.get("notes"))

    @mcp.tool()
    async def grab_url(
        ctx: Context[Any, AppContext],
        url: str = Field(description="url to grab"),
        tags: list[str] | None = Field(
            description="list of tags. If tags are specified in the Bear’s web content preferences, this parameter is ignored.",
            default=None,
        ),
    ) -> NoteID:
        """Create a new note with the content of a web page and return its unique identifier."""
        params = {
            "url": url,
        }
        if tags is not None:
            params["tags"] = ",".join(tags)

        return NoteID.model_validate(await _request(ctx, "grab-url", params))

    return mcp


def _fix_tags(obj: dict | QueryParams) -> Mapping[str, Any]:
    if "tags" not in obj:
        return obj
    tags = obj["tags"]
    if isinstance(tags, str):
        return {**obj, "tags": json.loads(tags)}
    return obj


def parse_notes(raw: str | None) -> list[NoteInfo]:
    if raw is None:
        return []
    return [NoteInfo.model_validate(_fix_tags(obj)) for obj in json.loads(raw)]


__all__: Final = ["server"]
