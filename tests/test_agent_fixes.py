"""
Unit tests for the 5 Android agent bug fixes.
Objects are constructed directly (no real config/device needed).
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers — build objects without touching config or device
# ---------------------------------------------------------------------------

def _make_planner(first_response="SKILL: tap\nARGS: id=1", second_response=None):
    """
    Build an LLMPlanner instance with a mocked OpenAI client.
    Bypasses __init__ entirely to avoid the config import.
    """
    from planner.llm_planner import LLMPlanner
    planner = LLMPlanner.__new__(LLMPlanner)
    planner.api_key = "fake"
    planner.base_url = None
    planner.model = "gpt-test"
    planner.vision_model = "moondream:latest"
    planner.system_prompt = (
        "You are an Android agent. Output ONE action per turn.\n\n"
        "Format (copy exactly):\nSKILL: <name>\nARGS: <key=val ...>"
    )

    mock_client = MagicMock()
    all_responses = [first_response] + ([second_response] if second_response is not None else [])
    response_mocks = [
        MagicMock(choices=[MagicMock(message=MagicMock(content=txt))])
        for txt in all_responses
    ]
    if len(response_mocks) == 1:
        mock_client.chat.completions.create.return_value = response_mocks[0]
    else:
        mock_client.chat.completions.create.side_effect = response_mocks

    planner.client = mock_client
    return planner


def _make_loop():
    """
    Build an AgentLoop shell without hitting __init__ (no adb, no config).
    Executor and planner are swapped for mocks.
    stuck_counter is set to -999 so the vision-fallback block never fires,
    which avoids needing to patch `config.settings` in tests.
    """
    from agent.agent_loop import AgentLoop
    loop = AgentLoop.__new__(AgentLoop)
    loop.device_id = "emulator-5554"
    loop.history = []
    loop.last_ui_str = ""
    # Keep stuck_counter negative so it never reaches the vision-fallback block
    loop.stuck_counter = -999

    loop.executor = MagicMock()
    loop.executor.execute_skill.return_value = True
    loop.executor.set_last_elements = MagicMock()

    loop.planner = MagicMock()
    loop.planner.plan_next_action.return_value = {"skill": "tap", "args": {"id": 1}}
    # refine_task was added to agent_loop.run(); mock it to return the task unchanged
    loop.planner.refine_task.side_effect = lambda task: task

    loop.adb = MagicMock()
    return loop


# ---------------------------------------------------------------------------
# Fix 1 – Soft vision hint (full UI always visible)
# ---------------------------------------------------------------------------

class TestSoftVisionHint(unittest.TestCase):
    def _get_user_msg(self, planner, ui, vision_insight):
        planner.plan_next_action("open search", ui, [], vision_insight=vision_insight)
        call_args = planner.client.chat.completions.create.call_args
        messages = (
            call_args.kwargs.get("messages")
            or call_args[1].get("messages")
        )
        return next(m["content"] for m in messages if m["role"] == "user")

    def test_full_ui_passed_with_vision_insight(self):
        """All UI elements must be forwarded to the LLM regardless of quadrant."""
        planner = _make_planner()
        ui = (
            "[0] Button 'Home'    center=(100,200)\n"
            "[1] Button 'Search'  center=(800,200)\n"
            "[2] Button 'Menu'    center=(100,1800)\n"
        )
        user_msg = self._get_user_msg(planner, ui, "top-right")

        self.assertIn("[0] Button 'Home'", user_msg)
        self.assertIn("[1] Button 'Search'", user_msg)
        self.assertIn("[2] Button 'Menu'", user_msg)
        self.assertIn("top-right", user_msg)
        self.assertIn("Vision hint", user_msg)

    def test_no_hint_without_vision_insight(self):
        """Without a vision insight no hint line is added."""
        planner = _make_planner()
        ui = "[0] Button center=(500,1000)\n[1] Text center=(500,500)\n"
        user_msg = self._get_user_msg(planner, ui, None)
        self.assertIn("[0] Button", user_msg)
        self.assertNotIn("Vision hint", user_msg)


# ---------------------------------------------------------------------------
# Fix 5 – Malformed output handling
# ---------------------------------------------------------------------------

class TestMalformedOutputHandling(unittest.TestCase):
    def test_parse_returns_none_on_garbage(self):
        """_parse_llm_output must return None (not scroll) for garbage input."""
        planner = _make_planner()
        self.assertIsNone(planner._parse_llm_output("I'm not sure what to do here."))

    def test_parse_returns_none_on_empty(self):
        planner = _make_planner()
        self.assertIsNone(planner._parse_llm_output(""))

    def test_retry_succeeds_on_second_attempt(self):
        """First call returns garbage; second (simplified) call succeeds."""
        planner = _make_planner(
            first_response="I am confused.",
            second_response="SKILL: press_key\nARGS: key=HOME",
        )
        result = planner.plan_next_action("go home", "[0] Home center=(540,100)", [])
        self.assertEqual(result["skill"], "press_key")
        self.assertEqual(result["args"]["key"], "HOME")
        self.assertEqual(planner.client.chat.completions.create.call_count, 2)

    def test_both_failures_return_done_not_scroll(self):
        """Two bad outputs must return done, never a scroll action."""
        planner = _make_planner(
            first_response="I don't know.",
            second_response="Still confused.",
        )
        result = planner.plan_next_action("find button", "[0] Btn center=(100,100)", [])
        self.assertEqual(result["skill"], "done")
        self.assertNotEqual(result["skill"], "scroll")


# ---------------------------------------------------------------------------
# Fix 2 – Outcome tracking in history
# ---------------------------------------------------------------------------

class TestOutcomeTracking(unittest.TestCase):
    def _run_one_step(self, ui_before, ui_after, exec_success):
        loop = _make_loop()
        loop.executor.execute_skill.return_value = exec_success
        loop.planner.plan_next_action.return_value = {"skill": "tap", "args": {"id": 0}}

        # Provide 2 dump paths (pre + post) and 2 format return values
        with patch("agent.agent_loop.dump_ui_hierarchy", side_effect=["/tmp/before.xml", "/tmp/after.xml"]), \
             patch("agent.agent_loop.parse_ui_xml", return_value=[]), \
             patch("agent.agent_loop.format_ui_elements_for_llm", side_effect=[ui_before, ui_after]), \
             patch("time.sleep"):
            loop.run(task="test task", max_steps=1)
        return loop.history

    def test_success_outcome(self):
        history = self._run_one_step("UIv1", "UIv2", exec_success=True)
        self.assertEqual(len(history), 1)
        self.assertIsInstance(history[0], dict)
        self.assertEqual(history[0]["outcome"], "SUCCESS")

    def test_failed_outcome(self):
        history = self._run_one_step("UIv1", "UIv1", exec_success=False)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["outcome"], "FAILED")

    def test_no_change_outcome(self):
        history = self._run_one_step("UIv1", "UIv1", exec_success=True)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["outcome"], "NO_CHANGE")


# ---------------------------------------------------------------------------
# Fix 3 – Loop detector
# ---------------------------------------------------------------------------

class TestLoopDetector(unittest.TestCase):
    def test_back_pressed_after_three_identical_actions(self):
        """After 3 identical actions the executor gets press_key(BACK)."""
        loop = _make_loop()
        loop.planner.plan_next_action.return_value = {
            "skill": "scroll",
            "args": {"x1": 500, "y1": 1500, "x2": 500, "y2": 500},
        }

        # Need enough dump/format pairs for 4 steps * 2 calls each = 8 calls
        # Use unlimited side_effect via a cycle
        ui_dumps = [f"/tmp/ui{i}.xml" for i in range(20)]
        ui_strs = ["same_ui"] * 20

        with patch("agent.agent_loop.dump_ui_hierarchy", side_effect=ui_dumps), \
             patch("agent.agent_loop.parse_ui_xml", return_value=[]), \
             patch("agent.agent_loop.format_ui_elements_for_llm", side_effect=ui_strs), \
             patch("time.sleep"):
            loop.run(task="scroll forever", max_steps=4)

        # Find any call to press_key with key=BACK (loop recovery)
        back_calls = [
            c for c in loop.executor.execute_skill.call_args_list
            if c.args[0] == "press_key" and c.args[1].get("key") == "BACK"
        ]
        self.assertGreaterEqual(len(back_calls), 1,
                                "Expected at least one BACK press for loop recovery")


if __name__ == "__main__":
    unittest.main()
