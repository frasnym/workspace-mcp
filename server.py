"""Minimal Streamable HTTP MCP server for Gmail, Calendar and Tasks.

It wraps the Google APIs using the OAuth refresh token already on the Hermes
volume. Every request requires the bearer token from /opt/data/.env.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as HTTPRequest
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

PROTOCOL_VERSION = "2025-06-18"


def env_value(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


BEARER = env_value("WORKSPACE_MCP_TOKEN")
_CREDS: Credentials | None = None
_SERVICES: dict[str, Any] = {}


def credentials() -> Credentials:
    global _CREDS
    if _CREDS is None:
        _CREDS = Credentials(
            token=None,
            refresh_token=env_value("GOOGLE_REFRESH_TOKEN"),
            token_uri=env_value(
                "GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token"
            ),
            client_id=env_value("GOOGLE_MCP_CLIENT_ID"),
            client_secret=env_value("GOOGLE_MCP_CLIENT_SECRET"),
        )
    if not _CREDS.valid and _CREDS.refresh_token:
        _CREDS.refresh(Request())
    if not _CREDS.token:
        raise RuntimeError("no Google access token")
    return _CREDS


def service(name: str) -> Any:
    if name not in _SERVICES:
        versions = {
            "gmail": ("gmail", "v1"),
            "calendar": ("calendar", "v3"),
            "tasks": ("tasks", "v1"),
        }
        api, version = versions[name]
        _SERVICES[name] = build(
            api, version, credentials=credentials(), cache_discovery=False
        )
    return _SERVICES[name]


def header(headers: list[dict], name: str) -> str:
    for item in headers or []:
        if item.get("name", "").lower() == name:
            return item.get("value", "")
    return ""


def body_text(payload: dict) -> str:
    if not payload:
        return ""
    mime = payload.get("mimeType", "")
    if mime == "text/plain" and "body" in payload:
        data = payload["body"].get("data", "")
        if data:
            try:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
            except ValueError:
                return ""
    for part in payload.get("parts", []):
        text = body_text(part)
        if text:
            return text
    return ""


def message_shape(message: dict) -> dict:
    payload = message.get("payload", {})
    return {
        "id": message.get("id", ""),
        "threadId": message.get("threadId", ""),
        "subject": message.get("subject") or header(payload.get("headers"), "subject"),
        "sender": message.get("sender") or header(payload.get("headers"), "from"),
        "snippet": message.get("snippet", ""),
        "labelIds": message.get("labelIds", []),
        "plaintextBody": body_text(payload),
    }


def event_shape(event: dict) -> dict:
    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", "") or "(no title)",
        "start": event.get("start", {}),
        "end": event.get("end", {}),
        "location": event.get("location", ""),
    }


def task_shape(task: dict, list_id: str = "") -> dict:
    return {
        "id": task.get("id", ""),
        "title": task.get("title", ""),
        "deadlineDate": task.get("due", ""),
        "completed": bool(task.get("status") == "completed"),
        "deleted": bool(task.get("deleted")),
        "taskListId": list_id,
    }


def find_tasklist(task_id: str) -> str:
    lists = service("tasks").tasklists().list(maxResults=100).execute().get("items", [])
    for item in lists:
        found = (
            service("tasks").tasks().list(tasklist=item["id"], maxResults=100).execute()
        )
        if any(t.get("id") == task_id for t in found.get("items", [])):
            return item["id"]
    return "@default"


def s(
    name: str, description: str, props: dict, required: list[str] | None = None
) -> dict:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": props,
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


TOOLS = [
    s(
        "gmail_search",
        "Search Gmail threads",
        {"query": {"type": "string"}, "pageSize": {"type": "integer"}},
    ),
    s(
        "gmail_get_thread",
        "Get a thread",
        {"threadId": {"type": "string"}, "messageFormat": {"type": "string"}},
        ["threadId"],
    ),
    s(
        "gmail_get",
        "Get a message",
        {"messageId": {"type": "string"}, "messageFormat": {"type": "string"}},
        ["messageId"],
    ),
    s("list_labels", "List Gmail labels", {}),
    s(
        "gmail_modify_labels",
        "Add/remove message labels",
        {
            "messageId": {"type": "string"},
            "addLabelIds": {"type": "array", "items": {"type": "string"}},
            "removeLabelIds": {"type": "array", "items": {"type": "string"}},
        },
        ["messageId"],
    ),
    s(
        "gmail_trash",
        "Trash a message",
        {"messageId": {"type": "string"}},
        ["messageId"],
    ),
    s(
        "calendar_list",
        "List events in a window",
        {
            "startTime": {"type": "string"},
            "endTime": {"type": "string"},
            "timeZone": {"type": "string"},
            "pageSize": {"type": "integer"},
        },
    ),
    s(
        "event_create",
        "Create a calendar event",
        {
            "summary": {"type": "string"},
            "startTime": {"type": "string"},
            "endTime": {"type": "string"},
        },
    ),
    s(
        "event_update",
        "Update a calendar event",
        {"eventId": {"type": "string"}},
        ["eventId"],
    ),
    s(
        "event_delete",
        "Delete a calendar event",
        {"eventId": {"type": "string"}},
        ["eventId"],
    ),
    s("tasks_list_lists", "List task lists", {}),
    s("tasks_list", "List open tasks", {"pageSize": {"type": "integer"}}),
    s(
        "task_create",
        "Create a task",
        {"title": {"type": "string"}, "taskListId": {"type": "string"}},
    ),
    s(
        "task_update",
        "Update a task",
        {"taskId": {"type": "string"}, "title": {"type": "string"}},
        ["taskId"],
    ),
    s("task_complete", "Complete a task", {"taskId": {"type": "string"}}, ["taskId"]),
]


HANDLERS: dict[str, Callable[[dict], Any]] = {
    "gmail_search": lambda a: {
        "threads": service("gmail")
        .users()
        .threads()
        .list(userId="me", q=a.get("query", ""), maxResults=a.get("pageSize", 20))
        .execute()
        .get("threads", [])
    },
    "gmail_get_thread": lambda a: {
        "messages": [
            message_shape(m)
            for m in service("gmail")
            .users()
            .threads()
            .get(
                userId="me", id=a["threadId"], format=a.get("messageFormat", "minimal")
            )
            .execute()
            .get("messages", [])
        ]
    },
    "gmail_get": lambda a: message_shape(
        service("gmail")
        .users()
        .messages()
        .get(userId="me", id=a["messageId"], format=a.get("messageFormat", "full"))
        .execute()
    ),
    "list_labels": lambda a: {
        "labels": service("gmail")
        .users()
        .labels()
        .list(userId="me")
        .execute()
        .get("labels", [])
    },
    "gmail_modify_labels": lambda a: (
        service("gmail")
        .users()
        .messages()
        .modify(
            userId="me",
            id=a["messageId"],
            body={
                "addLabelIds": a.get("addLabelIds", []),
                "removeLabelIds": a.get("removeLabelIds", []),
            },
        )
        .execute()
    ),
    "gmail_trash": lambda a: (
        service("gmail")
        .users()
        .messages()
        .trash(userId="me", id=a["messageId"])
        .execute()
    ),
    "calendar_list": lambda a: {
        "events": [
            event_shape(e)
            for e in service("calendar")
            .events()
            .list(
                calendarId="primary",
                timeMin=a.get("startTime"),
                timeMax=a.get("endTime"),
                timeZone=a.get("timeZone"),
                maxResults=a.get("pageSize", 100),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
            .get("items", [])
        ]
    },
    "event_create": lambda a: event_shape(
        service("calendar").events().insert(calendarId="primary", body=a).execute()
    ),
    "event_update": lambda a: event_shape(
        service("calendar")
        .events()
        .patch(
            calendarId="primary",
            eventId=a["eventId"],
            body={k: v for k, v in a.items() if k != "eventId"},
        )
        .execute()
    ),
    "event_delete": lambda a: (
        service("calendar")
        .events()
        .delete(calendarId="primary", eventId=a["eventId"])
        .execute()
        or {}
    ),
    "tasks_list_lists": lambda a: {
        "taskLists": [
            {"id": i["id"], "title": i.get("title", "My Tasks")}
            for i in service("tasks")
            .tasklists()
            .list(maxResults=100)
            .execute()
            .get("items", [])
        ]
    },
    "tasks_list": lambda a: _tasks_list(a.get("pageSize", 100)),
    "task_create": lambda a: task_shape(
        service("tasks")
        .tasks()
        .insert(
            tasklist=a.get("taskListId", "@default"),
            body={k: v for k, v in a.items() if k != "taskListId"},
        )
        .execute()
    ),
    "task_update": lambda a: task_shape(
        service("tasks")
        .tasks()
        .update(
            tasklist=a.get("taskListId", find_tasklist(a["taskId"])),
            task=a["taskId"],
            body={k: v for k, v in a.items() if k not in ("taskId", "taskListId")},
        )
        .execute()
    ),
    "task_complete": lambda a: task_shape(
        service("tasks")
        .tasks()
        .complete(
            tasklist=a.get("taskListId", find_tasklist(a["taskId"])), task=a["taskId"]
        )
        .execute()
    ),
}


def _tasks_list(page_size: int) -> dict:
    tasks = []
    for lst in (
        service("tasks").tasklists().list(maxResults=100).execute().get("items", [])
    ):
        result = (
            service("tasks")
            .tasks()
            .list(tasklist=lst["id"], maxResults=page_size, showCompleted=False)
            .execute()
        )
        tasks.extend(task_shape(t, lst["id"]) for t in result.get("items", []))
    return {"tasks": tasks}


def dispatch(payload: dict) -> dict:
    method = payload.get("method", "")
    request_id = payload.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "workspace", "version": "1.0.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = payload.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name not in HANDLERS:
            raise ValueError(f"unknown tool: {name}")
        result = HANDLERS[name](args)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                ],
                "structuredContent": result,
            },
        }
    raise ValueError(f"unsupported method: {method}")


class BearerAuth(BaseHTTPMiddleware):
    async def dispatch(self, request: HTTPRequest, call_next: Callable) -> Response:
        if request.headers.get("authorization") != f"Bearer {BEARER}" or not BEARER:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def mcp_endpoint(request: HTTPRequest) -> Response:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "invalid JSON"}},
            status_code=400,
        )
    if isinstance(payload, list):
        return JSONResponse([dispatch(p) for p in payload if p.get("id") is not None])
    if payload.get("id") is None:
        return Response(status_code=202)
    try:
        return JSONResponse(dispatch(payload))
    except Exception as exc:  # noqa: BLE001 - JSON-RPC error boundary
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            }
        )


app = Starlette(routes=[Route("/mcp", mcp_endpoint, methods=["POST"])])
app.add_middleware(BearerAuth)
