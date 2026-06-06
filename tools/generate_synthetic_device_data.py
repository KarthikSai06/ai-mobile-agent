"""
generate_synthetic_device_data.py
==================================
Runs programmatic scenarios on the connected Android device to collect real-device
UI dumps and correct actions, then performs data augmentation to produce a diverse,
high-quality fine-tuning dataset for local model training (Qwen 2.5).

Zero API key costs. Prevents overfitting by introducing task variety and UI shuffling.
"""

import sys
import os
import re
import json
import time
import random
import argparse
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from device.adb_controller import AdbController
from ui.dump_ui import dump_ui_hierarchy
from ui.ui_parser import parse_ui_xml, format_ui_elements_for_llm

# ── System prompt (same as the live agent) ────────────────────────────────────
SYSTEM_PROMPT = """You are an Android agent. Output ONE action per turn.

Skills:
  tap            ARGS: id=<n>   OR   x=<n> y=<n>
  type_text      ARGS: text=<string>
  open_app       ARGS: package_name=<pkg>
  press_key      ARGS: key=HOME|BACK|ENTER
  scroll         ARGS: x1=500 y1=1500 x2=500 y2=500
  save_memory    ARGS: key=<name> value=<x,y or description>
  delete_memory  ARGS: key=<name>
  done           ARGS: (none)

Rules:
  1. open_app only needs package_name. Never add id/x/y/text to it.
  2. Prefer id over coordinates when available.
  3. If you just tapped a text field/search bar and it succeeded, DO NOT tap it again — proceed to type_text.
  4. After typing a search term do NOT tap the search bar again — tap the result below it.
  5. If you see Message/Mute/Call buttons at y≈738 with NO Emoji/Bot-menu → Profile page. Tap Message to enter chat.
  6. If you see Emoji/Bot-menu at the bottom → Chat window. Tap the Message input box (y>2000) and type. Do NOT tap the header.

Format (copy exactly):
SKILL: <name>
ARGS: <key=val ...>"""


class SyntheticDataGenerator:
    def __init__(self, output_path: Path):
        self.adb = AdbController(settings.ADB_PATH)
        devices = self.adb.get_devices()
        if not devices:
            raise RuntimeError("No connected Android devices found via ADB!")
        self.device_id = devices[0]
        self.output_path = output_path
        self.raw_examples = []
        print(f"Initialized SyntheticDataGenerator using device: {self.device_id}")

    # ── Match UI Elements Programmatically ──────────────────────────────────
    def _find_element(self, elements, target_desc):
        """
        Robust element matcher. Matches digits, arithmetic operators, or texts.
        """
        # If looking for a digit
        if isinstance(target_desc, str) and target_desc.isdigit():
            for el in elements:
                if el["text"] == target_desc:
                    return el
                if el["resource_id"].endswith(f"digit_{target_desc}"):
                    return el

        # If looking for operator
        op_map = {
            "+": ["+", "op_add", "add"],
            "-": ["−", "op_sub", "op_minus", "subtract", "minus"],
            "*": ["×", "op_mul", "op_multiply", "multiply", "times"],
            "/": ["÷", "op_div", "op_divide", "divide"],
            "=": ["=", "eq", "equals"]
        }
        
        target_key = str(target_desc)
        if target_key in op_map:
            for el in elements:
                if el["text"] in op_map[target_key] or el["content_desc"].lower() in op_map[target_key]:
                    return el
                for suffix in op_map[target_key]:
                    if el["resource_id"].endswith(suffix):
                        return el

        # General string match (case-insensitive)
        for el in elements:
            txt = el["text"].lower()
            desc = el["content_desc"].lower()
            rid = el["resource_id"].lower()
            target_lower = target_key.lower()
            
            if target_lower == txt or target_lower == desc:
                return el
            if target_lower in txt or target_lower in desc or target_lower in rid:
                return el

        return None

    def _record_step(self, task: str, history: list, elements: list, target_el: dict, skill: str, args_dict: dict):
        """
        Formats and saves a single step record.
        """
        # Build UI list formatted for the LLM
        ui_str = format_ui_elements_for_llm(elements)
        
        # Build history string
        history_str = "\n".join(f"  {h}" for h in history[-5:]) or "  (none)"
        
        # If target element is provided, map its formatted ID in the UI Elements list
        if target_el and skill == "tap":
            # Reformat UI elements and find the index in the capped list
            capped_elements = sorted(elements, key=lambda e: (not e["clickable"], e["center_y"]))[:60]
            
            # Drop container views and match elements similarly to formatting pipeline
            filtered = []
            for el in capped_elements:
                is_container = el["class_name"] in _CONTAINER_CLASSES
                if bool(el["text"] or el["content_desc"]) or not is_container:
                    filtered.append(el)
            
            # Match coordinate
            idx = -1
            for i, el in enumerate(filtered[:60]):
                if el["center_x"] == target_el["center_x"] and el["center_y"] == target_el["center_y"]:
                    idx = i
                    break
            
            if idx != -1:
                args_str = f"id={idx}"
            else:
                args_str = f"x={target_el['center_x']} y={target_el['center_y']}"
        else:
            args_str = " ".join(f"{k}={v}" for k, v in args_dict.items()) if args_dict else "(none)"

        user_content = f"Task: {task}\n\nAction History:\n{history_str}\n\nUI Elements:\n{ui_str}"
        assistant_content = f"SKILL: {skill}\nARGS: {args_str}"
        
        example = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_content}
            ],
            "meta": {
                "task_type": "", 
                "target_index": idx if (target_el and skill == "tap" and idx != -1) else None,
                "skill": skill,
                "args_dict": args_dict
            }
        }
        
        self.raw_examples.append(example)
        print(f"Recorded step -> {skill}({args_str})")

    # ── App Launcher Helper ─────────────────────────────────────────────────
    def _launch_app(self, package_name: str):
        print(f"Launching package: {package_name}...")
        self.adb.run_cmd("-s", self.device_id, "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(2.0)

    def _go_home(self):
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "keyevent", "3")
        time.sleep(1.0)

    # ── Programmatic Scenarios ──────────────────────────────────────────────
    def run_calculator_scenario(self, val1: int, op: str, val2: int):
        task = f"Calculate {val1} {op} {val2} in the calculator"
        history = []
        
        self._launch_app("com.vivo.calculator")
        equation = f"{val1}{op}{val2}="
        
        for char in equation:
            xml_path = dump_ui_hierarchy(self.adb, self.device_id)
            if not xml_path: continue
            elements = parse_ui_xml(xml_path)
            el = self._find_element(elements, char)
            if not el: continue
            
            self._record_step(task, history, elements, el, "tap", {})
            self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(el["center_x"]), str(el["center_y"]))
            history.append(f"tap(id={char}) → SUCCESS")
            time.sleep(0.6)
            
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if xml_path:
            elements = parse_ui_xml(xml_path)
            el = self._find_element(elements, "AC") or self._find_element(elements, "C")
            if el:
                self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(el["center_x"]), str(el["center_y"]))
                
        self._go_home()

    def run_settings_search_scenario(self, query: str):
        task = f"Search for '{query}' in settings"
        history = []
        
        self._launch_app("com.android.settings")
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        search_bar = None
        for hint in ["search settings", "search", "vigour_search_edit", "vsearchview"]:
            search_bar = self._find_element(elements, hint)
            if search_bar: break
            
        if not search_bar:
            self._go_home()
            return
            
        self._record_step(task, history, elements, search_bar, "tap", {})
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(search_bar["center_x"]), str(search_bar["center_y"]))
        history.append(f"tap(id={search_bar.get('resource_id', 'search_edit')}) → SUCCESS")
        time.sleep(1.2)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        edit_field = None
        for el in elements:
            if "edit" in el["resource_id"].lower() or el["class_name"].endswith("EditText"):
                edit_field = el
                break
        if not edit_field:
            edit_field = search_bar
            
        self._record_step(task, history, elements, None, "type_text", {"text": query})
        adb_query = query.replace(" ", "%s")
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "text", adb_query)
        history.append(f"type_text(text={query}) → SUCCESS")
        time.sleep(1.5)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        result_item = None
        for el in elements:
            if el["clickable"] and el["center_y"] > 250:
                rid = el["resource_id"].lower()
                txt = el["text"].lower()
                if "search" not in rid and "cancel" not in rid and "clear" not in rid and txt != "cancel" and txt != "clear":
                    result_item = el
                    break
        
        if result_item:
            self._record_step(task, history, elements, result_item, "tap", {})
            self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(result_item["center_x"]), str(result_item["center_y"]))
            history.append(f"tap(id={result_item.get('resource_id', 'result')}) → SUCCESS")
            time.sleep(1.5)
            
        self._go_home()

    def run_contacts_scenario(self, name: str, phone: str):
        task = f"Add a new contact named {name} with phone number {phone}"
        history = []
        
        self.adb.run_cmd("-s", self.device_id, "shell", "am", "start", "-a", "android.intent.action.INSERT", "-t", "vnd.android.cursor.dir/contact")
        time.sleep(2.0)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        name_field = self._find_element(elements, "Name") or self._find_element(elements, "First name")
        if not name_field:
            self._go_home()
            return
            
        self._record_step(task, history, elements, name_field, "tap", {})
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(name_field["center_x"]), str(name_field["center_y"]))
        history.append(f"tap(id=Name) → SUCCESS")
        time.sleep(1.0)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        self._record_step(task, history, elements, None, "type_text", {"text": name})
        adb_name = name.replace(" ", "%s")
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "text", adb_name)
        history.append(f"type_text(text={name}) → SUCCESS")
        time.sleep(1.0)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        phone_field = self._find_element(elements, "Phone")
        if not phone_field:
            self._go_home()
            return
            
        self._record_step(task, history, elements, phone_field, "tap", {})
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(phone_field["center_x"]), str(phone_field["center_y"]))
        history.append(f"tap(id=Phone) → SUCCESS")
        time.sleep(1.0)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        self._record_step(task, history, elements, None, "type_text", {"text": phone})
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "text", phone)
        history.append(f"type_text(text={phone}) → SUCCESS")
        time.sleep(1.0)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        save_btn = None
        for el in elements:
            rid = el["resource_id"]
            if "edit_right_button" in rid or "save" in rid or "done" in rid:
                save_btn = el
                break
        
        if not save_btn:
            save_btn = {"center_x": 980, "center_y": 180, "clickable": True, "class_name": "android.widget.Button", "resource_id": "com.android.contacts:id/originui_vtoolbar_edit_right_button_rom14_0", "text": "", "content_desc": ""}
            
        self._record_step(task, history, elements, save_btn, "tap", {})
        
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "keyevent", "4")
        time.sleep(0.8)
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "keyevent", "4")
        time.sleep(1.0)
        self._go_home()

    def run_youtube_scenario(self, query: str):
        task = f"Search for '{query}' on YouTube and play it"
        history = []
        
        self._launch_app("com.google.android.youtube")
        
        # Step 1: Search button
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        search_icon = self._find_element(elements, "Search")
        if not search_icon:
            search_icon = {"center_x": 1017, "center_y": 163, "clickable": True, "resource_id": "com.google.android.youtube:id/menu_item_view", "class_name": "android.widget.ImageView"}
            
        self._record_step(task, history, elements, search_icon, "tap", {})
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(search_icon["center_x"]), str(search_icon["center_y"]))
        history.append("tap(id=Search) → SUCCESS")
        time.sleep(2.0)
        
        # Step 2: Search input field
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        search_box = self._find_element(elements, "Search YouTube") or self._find_element(elements, "search_edit_text")
        if not search_box:
            search_box = {"center_x": 550, "center_y": 163, "clickable": True, "resource_id": "com.google.android.youtube:id/search_edit_text", "class_name": "android.widget.EditText"}
            
        self._record_step(task, history, elements, search_box, "tap", {})
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(search_box["center_x"]), str(search_box["center_y"]))
        history.append("tap(id=search_edit_text) → SUCCESS")
        time.sleep(1.0)
        
        # Step 3: Type and enter
        self._record_step(task, history, elements, None, "type_text", {"text": query})
        adb_query = query.replace(" ", "%s")
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "text", adb_query)
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "keyevent", "66")
        history.append(f"type_text(text={query}) → SUCCESS")
        time.sleep(3.5)
        
        # Step 4: Tap first result
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        first_video = None
        for el in elements:
            desc = el["content_desc"].lower()
            rid = el["resource_id"].lower()
            if el["clickable"] and el["center_y"] > 250:
                if "play video" in desc or "play short" in desc or "views" in desc or "subscriber" in desc or "video" in rid or "thumbnail" in rid:
                    first_video = el
                    break
        if not first_video:
            for el in elements:
                if el["clickable"] and 400 < el["center_y"] < 1200:
                    first_video = el
                    break
                    
        if first_video:
            self._record_step(task, history, elements, first_video, "tap", {})
            self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(first_video["center_x"]), str(first_video["center_y"]))
            history.append("tap(id=video_result) → SUCCESS")
            time.sleep(4.0)
            
        self._go_home()

    def run_spotify_scenario(self, query: str):
        task = f"Play song '{query}' on Spotify"
        history = []
        
        print(f"Launching Spotify with Media Play intent for: {query}...")
        adb_query = query.replace(" ", "%s")
        self.adb.run_cmd("-s", self.device_id, "shell", "am", "start", "-a", "android.media.action.MEDIA_PLAY_FROM_SEARCH", "-e", "query", adb_query, "com.spotify.music")
        time.sleep(4.0)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        song_item = None
        for el in elements:
            txt = el["text"].lower()
            rid = el["resource_id"].lower()
            if el["clickable"] and query.lower() in txt and ("row_root" in rid or "title" in rid):
                song_item = el
                break
                
        if not song_item:
            song_item = self._find_element(elements, query)
            
        if not song_item:
            song_item = {"center_x": 540, "center_y": 457, "clickable": True, "resource_id": "com.spotify.music:id/row_root", "class_name": "android.view.ViewGroup"}
            
        self._record_step(task, history, elements, song_item, "tap", {})
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(song_item["center_x"]), str(song_item["center_y"]))
        history.append("tap(id=song_item) → SUCCESS")
        time.sleep(3.0)
        
        self._go_home()

    def run_chrome_scenario(self, query: str):
        task = f"Search for '{query}' on Chrome"
        history = []
        
        self._launch_app("com.android.chrome")
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        search_bar = self._find_element(elements, "Search or type URL") or self._find_element(elements, "search_box_text") or self._find_element(elements, "url_bar")
        if not search_bar:
            search_bar = {"center_x": 540, "center_y": 320, "clickable": True, "resource_id": "com.android.chrome:id/search_box_text", "class_name": "android.widget.TextView"}
            
        self._record_step(task, history, elements, search_bar, "tap", {})
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(search_bar["center_x"]), str(search_bar["center_y"]))
        history.append("tap(id=search_box) → SUCCESS")
        time.sleep(1.5)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        self._record_step(task, history, elements, None, "type_text", {"text": query})
        adb_query = query.replace(" ", "%s")
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "text", adb_query)
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "keyevent", "66")
        history.append(f"type_text(text={query}) → SUCCESS")
        time.sleep(3.5)
        
        xml_path = dump_ui_hierarchy(self.adb, self.device_id)
        if not xml_path: return
        elements = parse_ui_xml(xml_path)
        
        first_result = None
        for el in elements:
            if el["clickable"] and el["center_y"] > 250:
                txt = el["text"].lower()
                desc = el["content_desc"].lower()
                if "search" not in txt and "url" not in txt and "tab" not in desc and "cancel" not in txt:
                    first_result = el
                    break
        if not first_result:
            first_result = {"center_x": 540, "center_y": 600, "clickable": True, "class_name": "android.view.View"}
            
        self._record_step(task, history, elements, first_result, "tap", {})
        self.adb.run_cmd("-s", self.device_id, "shell", "input", "tap", str(first_result["center_x"]), str(first_result["center_y"]))
        history.append("tap(id=web_result) → SUCCESS")
        time.sleep(3.0)
        
        self._go_home()

    # ── Data Augmentation & Multiplication ──────────────────────────────────
    def augment_dataset(self, multiplicity: int = 10):
        """
        Multiplies the collected raw examples programmatically by:
        1. Shuffling UI elements list (updating tap targets).
        2. Paraphrasing the task prompts.
        3. Query swapping for complex app searches (YouTube, Spotify, Chrome).
        """
        augmented = []
        print(f"Starting programmatic data augmentation (Multiplicity={multiplicity}x)...")
        
        for ex in self.raw_examples:
            user_msg = ex["messages"][1]["content"]
            assistant_msg = ex["messages"][2]["content"]
            
            task_match = re.match(r"Task: (.+)", user_msg)
            if not task_match:
                augmented.append(ex)
                continue
            
            raw_task = task_match.group(1).strip()
            
            # 1. Base task paraphrasing
            if "Calculate" in raw_task:
                parts = raw_task.replace("Calculate ", "").replace(" in the calculator", "").split(" ")
                val1, op, val2 = parts[0], parts[1], parts[2]
                paraphrases = [
                    f"Calculate {val1} {op} {val2}",
                    f"What is {val1} {op} {val2}?",
                    f"Compute {val1} {op} {val2} using the calculator",
                    f"Perform {val1} {op} {val2}",
                    f"Add {val1} and {val2}" if op == "+" else f"Subtract {val2} from {val1}" if op == "-" else f"Multiply {val1} by {val2}" if op == "*" else f"Divide {val1} by {val2}"
                ]
            elif "Search for" in raw_task and "in settings" in raw_task:
                query = raw_task.replace("Search for '", "").replace("' in settings", "")
                paraphrases = [
                    f"Search settings for {query}",
                    f"Open {query} in settings",
                    f"Go to {query} settings",
                    f"Find the {query} menu in settings",
                    f"Search {query} on the phone settings"
                ]
            elif "Add a new contact" in raw_task:
                match = re.match(r"Add a new contact named (.+) with phone number (.+)", raw_task)
                if match:
                    name, phone = match.group(1), match.group(2)
                    paraphrases = [
                        f"Create a new contact named {name} with number {phone}",
                        f"Save {name}'s phone number {phone} to contacts",
                        f"Add {name} ({phone}) to address book",
                        f"Save contact {name} {phone}",
                        f"Store {name} {phone} in my phone contacts"
                    ]
                else:
                    paraphrases = [raw_task]
            elif "Search for" in raw_task and "on YouTube" in raw_task:
                query = raw_task.replace("Search for '", "").replace("' on YouTube and play it", "")
                paraphrases = [
                    f"Play {query} on YouTube",
                    f"YouTube search for {query} and play",
                    f"Find {query} on YouTube and start it",
                    f"Open YouTube and play {query}",
                    f"Search and play {query} on YouTube"
                ]
            elif "Play song" in raw_task:
                query = raw_task.replace("Play song '", "").replace("' on Spotify", "")
                paraphrases = [
                    f"Play {query} on Spotify",
                    f"Spotify play song {query}",
                    f"Listen to {query} on Spotify",
                    f"Play {query} using Spotify",
                    f"Open Spotify and play {query}"
                ]
            elif "Search for" in raw_task and "on Chrome" in raw_task:
                query = raw_task.replace("Search for '", "").replace("' on Chrome", "")
                paraphrases = [
                    f"Search Chrome for {query}",
                    f"Look up {query} on Google Chrome",
                    f"Open Chrome and search {query}",
                    f"Find information about {query} on Chrome",
                    f"Google search {query} in Chrome"
                ]
            else:
                paraphrases = [raw_task]

            for m in range(multiplicity):
                task_variation = paraphrases[m % len(paraphrases)] if m > 0 else raw_task
                
                # 2. Shuffling UI elements
                ui_block_match = re.search(r"UI Elements:\n(.*)", user_msg, re.DOTALL)
                if not ui_block_match:
                    new_ex = {
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg.replace(raw_task, task_variation)},
                            {"role": "assistant", "content": assistant_msg}
                        ]
                    }
                    augmented.append(new_ex)
                    continue
                
                ui_rows = ui_block_match.group(1).strip().split("\n")
                if not ui_rows or ui_rows == [""]:
                    new_ex = {
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg.replace(raw_task, task_variation)},
                            {"role": "assistant", "content": assistant_msg}
                        ]
                    }
                    augmented.append(new_ex)
                    continue
                
                target_idx = -1
                idx_match = re.search(r"ARGS: id=(\d+)", assistant_msg)
                if idx_match:
                    target_idx = int(idx_match.group(1))

                target_row = None
                parsed_rows = []
                for row in ui_rows:
                    r_match = re.match(r"^\[(\d+)\] (.*)", row)
                    if r_match:
                        r_idx = int(r_match.group(1))
                        content = r_match.group(2)
                        parsed_rows.append((r_idx, content))
                        if r_idx == target_idx:
                            target_row = content
                
                shuffled_rows = list(parsed_rows)
                random.shuffle(shuffled_rows)
                
                new_target_idx = -1
                formatted_rows = []
                for new_i, (orig_idx, content) in enumerate(shuffled_rows):
                    formatted_rows.append(f"[{new_i}] {content}")
                    if orig_idx == target_idx:
                        new_target_idx = new_i
                
                hist_match = re.search(r"Action History:\n(.*?)\n\nUI Elements:", user_msg, re.DOTALL)
                history_section = hist_match.group(1) if hist_match else "  (none)"
                
                new_ui_str = "\n".join(formatted_rows)
                new_user_content = f"Task: {task_variation}\n\nAction History:\n{history_section}\n\nUI Elements:\n{new_ui_str}"
                
                if target_idx != -1 and new_target_idx != -1:
                    new_assistant_content = f"SKILL: tap\nARGS: id={new_target_idx}"
                else:
                    new_assistant_content = assistant_msg
                
                # 3. Query swapping for complex searches (YouTube, Spotify, Chrome)
                new_query = None
                orig_query = None
                
                if "on YouTube" in raw_task:
                    orig_query = raw_task.replace("Search for '", "").replace("' on YouTube and play it", "")
                    yt_queries = ["lofi hip hop", "classical music", "jazz radio", "funny cats", "world news", "Minecraft gameplay", "tech review", "TED talk", "standup comedy", "music video", "football highlights", "Python tutorial", "SpaceX launch", "cooking guide", "yoga class"]
                    new_query = yt_queries[m % len(yt_queries)]
                elif "on Spotify" in raw_task:
                    orig_query = raw_task.replace("Play song '", "").replace("' on Spotify", "")
                    spot_queries = ["Blinding Lights", "Shape of You", "Bohemian Rhapsody", "Bad Guy", "Imagine", "Hello", "Stay", "Perfect", "Believer", "Dynamite", "Flowers", "Starboy", "Anti-Hero", "Cruel Summer", "As It Was"]
                    new_query = spot_queries[m % len(spot_queries)]
                elif "on Chrome" in raw_task:
                    orig_query = raw_task.replace("Search for '", "").replace("' on Chrome", "")
                    chrome_queries = ["weather in Delhi", "recipe for lasagna", "best movies 2025", "stock market today", "how to learn coding", "world cup scores", "closest grocery store", "meaning of life", "ChatGPT", "how to bake cake", "buy laptop online", "space exploration", "history of Rome"]
                    new_query = chrome_queries[m % len(chrome_queries)]

                if orig_query and new_query:
                    # Replace search query in task, history, UI elements, and completions
                    task_variation = task_variation.replace(orig_query, new_query)
                    new_user_content = new_user_content.replace(orig_query, new_query)
                    
                    # Handle encoded versions
                    orig_encoded = orig_query.replace(" ", "%s")
                    new_encoded = new_query.replace(" ", "%s")
                    new_user_content = new_user_content.replace(orig_encoded, new_encoded)
                    
                    new_assistant_content = new_assistant_content.replace(orig_query, new_query)

                new_ex = {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": new_user_content.replace(raw_task, task_variation)},
                        {"role": "assistant", "content": new_assistant_content}
                    ]
                }
                augmented.append(new_ex)
                
        return augmented

    def save(self, examples: list):
        existing = []
        if self.output_path.exists():
            with open(self.output_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        existing.append(json.loads(line))
            print(f"Read {len(existing)} existing training examples from {self.output_path}")

        all_records = existing + examples
        
        seen_hashes = set()
        deduped_records = []
        for r in all_records:
            h = json.dumps(r["messages"], sort_keys=True)
            if h not in seen_hashes:
                seen_hashes.add(h)
                deduped_records.append(r)
                
        with open(self.output_path, "w", encoding="utf-8") as f:
            for ex in deduped_records:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                
        print(f"Saved {len(deduped_records)} total examples (added {len(examples)} new ones) to {self.output_path}")


_CONTAINER_CLASSES = {
    "android.widget.FrameLayout",
    "android.widget.LinearLayout",
    "android.widget.RelativeLayout",
    "android.view.View",
    "android.view.ViewGroup",
    "androidx.coordinatorlayout.widget.CoordinatorLayout",
    "androidx.constraintlayout.widget.ConstraintLayout",
}


def main():
    parser = argparse.ArgumentParser(description="Synthetic training data generator utilizing physical device.")
    parser.add_argument("--tasks", type=int, default=15, help="Number of distinct tasks to run on-device.")
    parser.add_argument("--app", type=str, default="all", choices=["all", "calculator", "settings", "contacts", "youtube", "spotify", "chrome"], help="App to run.")
    parser.add_argument("--multiplicity", type=int, default=10, help="Multiplication factor for data augmentation.")
    parser.add_argument("--output", type=str, default="storage/synthetic_training_data.jsonl", help="Output file path.")
    
    args = parser.parse_args()
    
    out_path = PROJECT_ROOT / args.output
    gen = SyntheticDataGenerator(out_path)
    
    # Scenarios
    calculator_runs = [
        (12, "+", 84), (305, "-", 90), (45, "*", 3), (88, "/", 4), (105, "+", 6),
        (99, "-", 45), (12, "*", 12), (100, "/", 5), (7, "+", 9), (50, "-", 25)
    ]
    
    settings_runs = [
        "Display", "Wi-Fi", "Bluetooth", "Apps", "Battery"
    ]
    
    contacts_runs = [
        ("John Doe", "5551234"), ("Alice Smith", "5555678"), ("Bob Johnson", "5559012")
    ]
    
    youtube_runs = [
        "lofi hip hop", "classical music", "jazz radio", "funny cats", "world news"
    ]
    
    spotify_runs = [
        "Shape of You", "Blinding Lights", "Bohemian Rhapsody", "Bad Guy", "Imagine"
    ]
    
    chrome_runs = [
        "weather in Delhi", "recipe for lasagna", "best movies 2025", "stock market today", "how to learn coding"
    ]
    
    runs_to_execute = args.tasks
    executed_count = 0
    
    try:
        # ── Calculator Runs ──────────────────────────────────────────────────
        if args.app in ["all", "calculator"]:
            num_runs = min(runs_to_execute, len(calculator_runs))
            print(f"\n--- Running {num_runs} Calculator Scenarios ---")
            for i in range(num_runs):
                val1, op, val2 = calculator_runs[i]
                print(f"\nScenario {executed_count+1}/{args.tasks}: {val1} {op} {val2}")
                gen.run_calculator_scenario(val1, op, val2)
                executed_count += 1
                if executed_count >= args.tasks: break
                
        # ── Settings Runs ────────────────────────────────────────────────────
        if args.app in ["all", "settings"] and executed_count < args.tasks:
            remaining = args.tasks - executed_count
            num_runs = min(remaining, len(settings_runs))
            print(f"\n--- Running {num_runs} Settings Scenarios ---")
            for i in range(num_runs):
                query = settings_runs[i]
                print(f"\nScenario {executed_count+1}/{args.tasks}: Search Settings for {query}")
                gen.run_settings_search_scenario(query)
                executed_count += 1
                if executed_count >= args.tasks: break
                
        # ── Contacts Runs ────────────────────────────────────────────────────
        if args.app in ["all", "contacts"] and executed_count < args.tasks:
            remaining = args.tasks - executed_count
            num_runs = min(remaining, len(contacts_runs))
            print(f"\n--- Running {num_runs} Contacts Scenarios ---")
            for i in range(num_runs):
                name, phone = contacts_runs[i]
                print(f"\nScenario {executed_count+1}/{args.tasks}: Add Contact {name} ({phone})")
                gen.run_contacts_scenario(name, phone)
                executed_count += 1
                if executed_count >= args.tasks: break

        # ── YouTube Runs ─────────────────────────────────────────────────────
        if args.app in ["all", "youtube"] and executed_count < args.tasks:
            remaining = args.tasks - executed_count
            num_runs = min(remaining, len(youtube_runs))
            print(f"\n--- Running {num_runs} YouTube Scenarios ---")
            for i in range(num_runs):
                query = youtube_runs[i]
                print(f"\nScenario {executed_count+1}/{args.tasks}: YouTube search for {query}")
                gen.run_youtube_scenario(query)
                executed_count += 1
                if executed_count >= args.tasks: break

        # ── Spotify Runs ─────────────────────────────────────────────────────
        if args.app in ["all", "spotify"] and executed_count < args.tasks:
            remaining = args.tasks - executed_count
            num_runs = min(remaining, len(spotify_runs))
            print(f"\n--- Running {num_runs} Spotify Scenarios ---")
            for i in range(num_runs):
                query = spotify_runs[i]
                print(f"\nScenario {executed_count+1}/{args.tasks}: Spotify play {query}")
                gen.run_spotify_scenario(query)
                executed_count += 1
                if executed_count >= args.tasks: break

        # ── Chrome Runs ──────────────────────────────────────────────────────
        if args.app in ["all", "chrome"] and executed_count < args.tasks:
            remaining = args.tasks - executed_count
            num_runs = min(remaining, len(chrome_runs))
            print(f"\n--- Running {num_runs} Chrome Scenarios ---")
            for i in range(num_runs):
                query = chrome_runs[i]
                print(f"\nScenario {executed_count+1}/{args.tasks}: Chrome search for {query}")
                gen.run_chrome_scenario(query)
                executed_count += 1
                if executed_count >= args.tasks: break
                
    except KeyboardInterrupt:
        print("\nGeneration interrupted by user. Augmenting what was collected...")
        
    if gen.raw_examples:
        print(f"\nCollected {len(gen.raw_examples)} raw training steps.")
        augmented_examples = gen.augment_dataset(multiplicity=args.multiplicity)
        print(f"Generated {len(augmented_examples)} augmented training examples.")
        gen.save(augmented_examples)
    else:
        print("\nNo examples collected.")


if __name__ == "__main__":
    main()
