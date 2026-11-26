import unittest

import server


class SDKServerTests(unittest.TestCase):
    def test_server_uses_official_sdk(self):
        self.assertTrue(
            hasattr(server, "mcp"), "server must expose an MCPServer instance"
        )

    def test_hand_written_protocol_is_removed(self):
        self.assertFalse(hasattr(server, "TOOLS"))
        self.assertFalse(hasattr(server, "dispatch"))

    def test_all_sixteen_tools_keep_their_names(self):
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
