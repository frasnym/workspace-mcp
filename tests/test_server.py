import asyncio
import unittest
from unittest import mock

from starlette.requests import Request
from starlette.responses import Response

import server


class RecordingCalendar:
    """Calendar API stand-in that records calls and returns a canned result."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def events(self):
        return self

    def calendarList(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def insert(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def patch(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def delete(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        return self.result


class MultiCalendarApi:
    """Calendar API stand-in with distinct calendar and event responses."""

    def __init__(self, calendars, events_by_calendar):
        self.calendars = calendars
        self.events_by_calendar = events_by_calendar
        self.calls = []
        self.resource = None

    def calendarList(self):
        self.resource = "calendars"
        return self

    def events(self):
        self.resource = "events"
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        if self.resource == "calendars":
            return {"items": self.calendars}
        return {"items": self.events_by_calendar[self.calls[-1]["calendarId"]]}


class RecordingGmailMessages:
    """Gmail messages API stand-in that records batchModify calls."""

    def __init__(self):
        self.calls = []

    def users(self):
        return self

    def messages(self):
        return self

    def batchModify(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        return {}


class GmailToolTests(unittest.TestCase):
    def test_gmail_trash_bulk_adds_trash_label_to_every_id(self):
        api = RecordingGmailMessages()
        with mock.patch.object(server, "service", return_value=api):
            server.gmail_trash_bulk(messageIds=["m1", "m2", "m3"])

        self.assertEqual(
            api.calls,
            [
                {
                    "userId": "me",
                    "body": {"ids": ["m1", "m2", "m3"], "addLabelIds": ["TRASH"]},
                }
            ],
        )


class CalendarToolTests(unittest.TestCase):
    def call_with_api(self, tool, *args, result=None, **kwargs):
        api = RecordingCalendar(result if result is not None else {})
        with mock.patch.object(server, "service", return_value=api):
            value = tool(*args, **kwargs)
        return api, value

    def test_calendar_list_merges_events_from_all_calendars(self):
        api = MultiCalendarApi(
            calendars=[{"id": "primary"}, {"id": "family@example.com"}],
            events_by_calendar={
                "primary": [{"id": "e1", "summary": "Personal"}],
                "family@example.com": [{"id": "e2", "summary": "Family dinner"}],
            },
        )
        with mock.patch.object(server, "service", return_value=api):
            result = server.calendar_list()

        self.assertEqual(
            [event["summary"] for event in result["events"]],
            ["Personal", "Family dinner"],
        )
        self.assertEqual(
            [call["calendarId"] for call in api.calls if "calendarId" in call],
            ["primary", "family@example.com"],
        )

    def test_calendar_list_sorts_merged_events_by_start_time(self):
        api = MultiCalendarApi(
            calendars=[{"id": "primary"}, {"id": "family@example.com"}],
            events_by_calendar={
                "primary": [
                    {
                        "id": "e1",
                        "summary": "Late",
                        "start": {"dateTime": "2026-11-26T22:30:00+07:00"},
                    }
                ],
                "family@example.com": [
                    {
                        "id": "e2",
                        "summary": "All day",
                        "start": {"date": "2026-11-26"},
                    },
                    {
                        "id": "e3",
                        "summary": "Early",
                        "start": {"dateTime": "2026-11-26T09:30:00+07:00"},
                    },
                ],
            },
        )
        with mock.patch.object(server, "service", return_value=api):
            result = server.calendar_list()

        self.assertEqual(
            [event["summary"] for event in result["events"]],
            ["All day", "Early", "Late"],
        )

    def test_calendar_list_queries_only_requested_calendar(self):
        api = MultiCalendarApi(
            calendars=[{"id": "primary"}, {"id": "family@example.com"}],
            events_by_calendar={
                "family@example.com": [{"id": "e2", "summary": "Family dinner"}]
            },
        )
        with mock.patch.object(server, "service", return_value=api):
            result = server.calendar_list(calendarId="family@example.com")

        self.assertEqual(
            [event["summary"] for event in result["events"]], ["Family dinner"]
        )
        self.assertEqual(
            [call["calendarId"] for call in api.calls if "calendarId" in call],
            ["family@example.com"],
        )

    def test_event_create_inserts_into_requested_calendar(self):
        api, _ = self.call_with_api(
            server.event_create, summary="Dinner", calendarId="family@example.com"
        )
        self.assertEqual(api.calls[-1]["calendarId"], "family@example.com")

    def test_event_update_patches_in_requested_calendar(self):
        api, _ = self.call_with_api(
            server.event_update, eventId="e1", calendarId="family@example.com"
        )
        self.assertEqual(api.calls[-1]["calendarId"], "family@example.com")

    def test_event_delete_removes_from_requested_calendar(self):
        api, _ = self.call_with_api(
            server.event_delete, eventId="e1", calendarId="family@example.com"
        )
        self.assertEqual(api.calls[-1]["calendarId"], "family@example.com")

    def test_calendars_list_returns_calendar_ids_and_names(self):
        _, value = self.call_with_api(
            server.calendars_list,
            result={
                "items": [
                    {
                        "id": "family@example.com",
                        "summary": "Family",
                        "kind": "calendar#calendarListEntry",
                    },
                    {
                        "id": "primary",
                        "summary": "me@example.com",
                        "kind": "calendar#calendarListEntry",
                    },
                ]
            },
        )
        self.assertEqual(
            value,
            {
                "calendars": [
                    {"id": "family@example.com", "summary": "Family"},
                    {"id": "primary", "summary": "me@example.com"},
                ]
            },
        )


class RecordingTasks:
    """Tasks API stand-in with tasks grouped by task list."""

    def __init__(self, tasks_by_list):
        self.tasks_by_list = tasks_by_list
        self.calls = []
        self.resource = None

    def tasklists(self):
        self.resource = "lists"
        return self

    def tasks(self):
        self.resource = "tasks"
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        if self.resource == "lists":
            return {"items": [{"id": "l1"}]}
        return {"items": self.tasks_by_list[self.calls[-1]["tasklist"]]}


class TasksToolTests(unittest.TestCase):
    def test_tasks_list_sorts_by_due_date_oldest_first(self):
        api = RecordingTasks(
            tasks_by_list={
                "l1": [
                    {"id": "t1", "title": "Later", "due": "2026-11-27T09:00:00Z"},
                    {"id": "t2", "title": "No due", "status": "needsAction"},
                    {"id": "t3", "title": "Earlier", "due": "2026-11-26T09:00:00Z"},
                ]
            }
        )
        with mock.patch.object(server, "service", return_value=api):
            result = server.tasks_list()

        self.assertEqual(
            [task["title"] for task in result["tasks"]],
            ["Earlier", "Later", "No due"],
        )


class RequestLoggingTests(unittest.TestCase):
    def test_logs_mcp_request_body(self):
        payload = b'{"jsonrpc":"2.0","method":"tools/call","id":1}'
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [(b"authorization", b"Bearer test-token")],
        }

        async def receive():
            return {"type": "http.request", "body": payload, "more_body": False}

        async def call_next(_):
            return Response("ok")

        request = Request(scope, receive)
        with mock.patch.object(server, "BEARER", "test-token"):
            with self.assertLogs("uvicorn.error", level="DEBUG") as logs:
                asyncio.run(server.BearerAuth(app=None).dispatch(request, call_next))

        self.assertEqual(logs.records[0].levelname, "DEBUG")
        self.assertIn(payload.decode(), "\n".join(logs.output))


class SDKServerTests(unittest.TestCase):
    def test_server_uses_official_sdk(self):
        self.assertTrue(
            hasattr(server, "mcp"), "server must expose an MCPServer instance"
        )

    def test_hand_written_protocol_is_removed(self):
        self.assertFalse(hasattr(server, "TOOLS"))
        self.assertFalse(hasattr(server, "dispatch"))

    def test_all_eighteen_tools_keep_their_names(self):
        names = {tool.name for tool in server.mcp._tool_manager.list_tools()}
        self.assertEqual(
            names,
            {
                "gmail_search",
                "gmail_get_thread",
                "gmail_get",
                "list_labels",
                "gmail_modify_labels",
                "gmail_trash",
                "gmail_trash_bulk",
                "calendar_list",
                "event_create",
                "event_update",
                "event_delete",
                "calendars_list",
                "tasks_list_lists",
                "tasks_list",
                "task_create",
                "task_update",
                "task_complete",
                "task_delete",
            },
        )


if __name__ == "__main__":
    unittest.main()
