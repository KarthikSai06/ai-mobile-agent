import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from device.adb_controller import AdbController
from skills import open_app

class TestOpenAppRobustness(unittest.TestCase):
    def setUp(self):
        self.adb = AdbController(adb_path="mock_adb")
        self.adb.run_cmd = MagicMock(return_value="")
        self.adb.get_current_focus = MagicMock(return_value="")
        self.adb.list_packages = MagicMock(return_value=[])

    def test_open_app_already_focused(self):
        self.adb.get_current_focus.return_value = "com.android.settings"
        result = open_app.execute(self.adb, "com.android.settings")
        self.assertTrue(result)
        self.adb.run_cmd.assert_not_called()

    def test_open_app_success_on_first_try(self):
        self.adb.get_current_focus.side_effect = ["", "com.android.settings"]
        result = open_app.execute(self.adb, "com.android.settings")
        self.assertTrue(result)
        self.assertEqual(self.adb.run_cmd.call_count, 1)

    def test_open_app_fallback_success(self):
        # Initial launch fails to change focus
        # 1. Initial check: ""
        # 2. Launch verification: "old.package"
        # 3. Fallback verification: "com.android.settings"
        self.adb.get_current_focus.side_effect = ["", "old.package", "com.android.settings"]
        self.adb.list_packages.return_value = ["com.android.settings"]
        
        result = open_app.execute(self.adb, "settings")
        self.assertTrue(result)
        # Should call run_cmd twice (initial + fallback)
        self.assertEqual(self.adb.run_cmd.call_count, 2)
        self.adb.list_packages.assert_called_with("settings", None)

    def test_open_app_failure(self):
        self.adb.get_current_focus.return_value = "old.package"
        self.adb.list_packages.return_value = []
        
        result = open_app.execute(self.adb, "non.existent.app")
        self.assertFalse(result)

if __name__ == "__main__":
    unittest.main()
