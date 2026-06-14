
from device.adb_controller import AdbController
from config.settings import ADB_PATH
from ui.dump_ui import dump_ui_hierarchy
import os

adb = AdbController(adb_path=ADB_PATH)
print(f"Using ADB at: {ADB_PATH}")
xml_path = dump_ui_hierarchy(adb)
print(f"XML Path: {xml_path}")
if xml_path and os.path.exists(xml_path):
    print("UI dump successful")
else:
    print("UI dump failed")
