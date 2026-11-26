import unittest
from unittest import mock

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


class CalendarToolTests(unittest.TestCase):
    def call_with_api(self, tool, *args, result=None, **kwargs):
        api = RecordingCalendar(result if result is not None else {})
        with mock.patch.object(server, "service", return_value=api):
            value = tool(*args, **kwargs)
        return api, value

    def test_calendar_list_queries_requested_calendar(self):
        api, _ = self.call_with_api(
            server.calendar_list, calendarId="family@example.com"
        )
        self.assertEqual(api.calls[-1]["calendarId"], "family@example.com")

    def test_calendar_list_defaults_to_primary(self):
        api, _ = self.call_with_api(server.calendar_list)
        self.assertEqual(api.calls[-1]["calendarId"], "primary")

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


class SDKServerTests(unittest.TestCase):
    def test_server_uses_official_sdk(self):
        self.assertTrue(
            hasattr(server, "mcp"), "server must expose an MCPServer instance"
        )

    def test_hand_written_protocol_is_removed(self):
        self.assertFalse(hasattr(server, "TOOLS"))
        self.assertFalse(hasattr(server, "dispatch"))

    def test_all_seventeen_tools_keep_their_names(self):
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
