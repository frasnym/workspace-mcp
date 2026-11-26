"""Streamable HTTP MCP server for Gmail, Calendar and Tasks.

It wraps the Google APIs using the OAuth refresh token already on the Hermes
volume. Every request requires the bearer token from /opt/data/.env.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as HTTPRequest
from starlette.responses import JSONResponse, Response

mcp = MCPServer("workspace")
logger = logging.getLogger("uvicorn.error")


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


@mcp.tool()
def gmail_search(query: str = "", pageSize: int = 20) -> dict[str, Any]:
    """Search Gmail threads"""
    return {
        "threads": service("gmail")
        .users()
        .threads()
        .list(userId="me", q=query, maxResults=pageSize)
        .execute()
        .get("threads", [])
    }


@mcp.tool()
def gmail_get_thread(threadId: str, messageFormat: str = "minimal") -> dict[str, Any]:
    """Get a thread"""
    return {
        "messages": [
            message_shape(m)
            for m in service("gmail")
            .users()
            .threads()
            .get(userId="me", id=threadId, format=messageFormat)
            .execute()
            .get("messages", [])
        ]
    }


@mcp.tool()
def gmail_get(messageId: str, messageFormat: str = "full") -> dict[str, Any]:
    """Get a message"""
    return message_shape(
        service("gmail")
        .users()
        .messages()
        .get(userId="me", id=messageId, format=messageFormat)
        .execute()
    )


@mcp.tool()
def list_labels() -> dict[str, Any]:
    """List Gmail labels"""
    return {
        "labels": service("gmail")
        .users()
        .labels()
        .list(userId="me")
        .execute()
        .get("labels", [])
    }


@mcp.tool()
def gmail_modify_labels(
    messageId: str,
    addLabelIds: list[str] | None = None,
    removeLabelIds: list[str] | None = None,
) -> dict[str, Any]:
    """Add/remove message labels"""
    return (
        service("gmail")
        .users()
        .messages()
        .modify(
            userId="me",
            id=messageId,
            body={
                "addLabelIds": addLabelIds or [],
                "removeLabelIds": removeLabelIds or [],
            },
        )
        .execute()
    )


@mcp.tool()
def gmail_trash(messageId: str) -> dict[str, Any]:
    """Trash a message"""
    return (
        service("gmail").users().messages().trash(userId="me", id=messageId).execute()
    )


@mcp.tool()
def gmail_trash_bulk(messageIds: list[str]) -> dict[str, Any]:
    """Trash messages in bulk (up to 1000 per call)"""
    return (
        service("gmail")
        .users()
        .messages()
        .batchModify(userId="me", body={"ids": messageIds, "addLabelIds": ["TRASH"]})
        .execute()
        or {}
    )


@mcp.tool()
def calendar_list(
    startTime: str | None = None,
    endTime: str | None = None,
    timeZone: str | None = None,
    pageSize: int = 100,
    calendarId: str | None = None,
) -> dict[str, Any]:
    """List events in a window"""
    if calendarId is None:
        calendar_ids = [
            item["id"]
            for item in service("calendar")
            .calendarList()
            .list(maxResults=100)
            .execute()
            .get("items", [])
        ]
    else:
        calendar_ids = [calendarId]
    events = []
    for item in calendar_ids:
        result = (
            service("calendar")
            .events()
            .list(
                calendarId=item,
                timeMin=startTime,
                timeMax=endTime,
                timeZone=timeZone,
                maxResults=pageSize,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events.extend(event_shape(e) for e in result.get("items", []))
    events.sort(
        key=lambda e: e["start"].get("dateTime") or e["start"].get("date") or ""
    )
    return {"events": events}


@mcp.tool()
def calendars_list() -> dict[str, Any]:
    """List accessible calendars"""
    return {
        "calendars": [
            {"id": item["id"], "summary": item.get("summary", "")}
            for item in service("calendar")
            .calendarList()
            .list(maxResults=100)
            .execute()
            .get("items", [])
        ]
    }


@mcp.tool()
def event_create(
    summary: str = "",
    startTime: str = "",
    endTime: str = "",
    calendarId: str = "primary",
) -> dict[str, Any]:
    """Create a calendar event"""
    return event_shape(
        service("calendar")
        .events()
        .insert(
            calendarId=calendarId,
            body={"summary": summary, "startTime": startTime, "endTime": endTime},
        )
        .execute()
    )


@mcp.tool()
def event_update(
    eventId: str,
    summary: str | None = None,
    startTime: str | None = None,
    endTime: str | None = None,
    location: str | None = None,
    calendarId: str = "primary",
) -> dict[str, Any]:
    """Update a calendar event"""
    body = {
        key: value
        for key, value in {
            "summary": summary,
            "startTime": startTime,
            "endTime": endTime,
            "location": location,
        }.items()
        if value is not None
    }
    return event_shape(
        service("calendar")
        .events()
        .patch(calendarId=calendarId, eventId=eventId, body=body)
        .execute()
    )


@mcp.tool()
def event_delete(eventId: str, calendarId: str = "primary") -> dict[str, Any]:
    """Delete a calendar event"""
    return (
        service("calendar")
        .events()
        .delete(calendarId=calendarId, eventId=eventId)
        .execute()
        or {}
    )


@mcp.tool()
def tasks_list_lists() -> dict[str, Any]:
    """List task lists"""
    return {
        "taskLists": [
            {"id": i["id"], "title": i.get("title", "My Tasks")}
            for i in service("tasks")
            .tasklists()
            .list(maxResults=100)
            .execute()
            .get("items", [])
        ]
    }


@mcp.tool()
def tasks_list(pageSize: int = 100) -> dict[str, Any]:
    """List open tasks"""
    tasks = []
    for lst in (
        service("tasks").tasklists().list(maxResults=100).execute().get("items", [])
    ):
        result = (
            service("tasks")
            .tasks()
            .list(tasklist=lst["id"], maxResults=pageSize, showCompleted=False)
            .execute()
        )
        tasks.extend(task_shape(t, lst["id"]) for t in result.get("items", []))
    tasks.sort(key=lambda t: (not t["deadlineDate"], t["deadlineDate"]))
    return {"tasks": tasks}


@mcp.tool()
def task_create(title: str = "", taskListId: str = "@default") -> dict[str, Any]:
    """Create a task"""
    return task_shape(
        service("tasks")
        .tasks()
        .insert(tasklist=taskListId, body={"title": title})
        .execute()
    )


@mcp.tool()
def task_update(
    taskId: str,
    title: str | None = None,
    taskListId: str | None = None,
) -> dict[str, Any]:
    """Update a task"""
    body = {"title": title} if title is not None else {}
    return task_shape(
        service("tasks")
        .tasks()
        .update(
            tasklist=taskListId or find_tasklist(taskId),
            task=taskId,
            body=body,
        )
        .execute()
    )


@mcp.tool()
def task_complete(taskId: str, taskListId: str | None = None) -> dict[str, Any]:
    """Complete a task"""
    return task_shape(
        service("tasks")
        .tasks()
        .complete(tasklist=taskListId or find_tasklist(taskId), task=taskId)
        .execute()
    )


@mcp.tool()
def task_delete(taskId: str, taskListId: str | None = None) -> dict[str, Any]:
    """Delete a task"""
    return (
        service("tasks")
        .tasks()
        .delete(tasklist=taskListId or find_tasklist(taskId), task=taskId)
        .execute()
        or {}
    )


class BearerAuth(BaseHTTPMiddleware):
    async def dispatch(self, request: HTTPRequest, call_next: Any) -> Response:
        if request.headers.get("authorization") != f"Bearer {BEARER}" or not BEARER:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.body()
        logger.debug("MCP request body: %s", body.decode("utf-8", "replace"))
        return await call_next(request)


# A reverse proxy owns Host filtering; the SDK's localhost-only default would reject it.
security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
app = mcp.streamable_http_app(
    transport_security=security,
    json_response=True,
    stateless_http=True,
)
app.add_middleware(BearerAuth)
