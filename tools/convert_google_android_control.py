import sys
import os
import json
import tensorflow as tf
from pathlib import Path
from android_env.proto.a11y import android_accessibility_forest_pb2

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# System prompt
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

_CONTAINER_CLASSES = {
    "android.widget.FrameLayout",
    "android.widget.LinearLayout",
    "android.widget.RelativeLayout",
    "android.view.View",
    "android.view.ViewGroup",
    "androidx.coordinatorlayout.widget.CoordinatorLayout",
    "androidx.constraintlayout.widget.ConstraintLayout",
}

def parse_proto_tree(serialized_forest):
    """
    Parses accessibility forest proto and returns list of elements.
    """
    forest = android_accessibility_forest_pb2.AndroidAccessibilityForest()
    forest.ParseFromString(serialized_forest)
    
    raw_nodes = []
    
    # We gather nodes from all windows
    for window in forest.windows:
        if not window.HasField("tree"):
            continue
        for node in window.tree.nodes:
            # Get bounds
            rect = node.bounds_in_screen
            left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
            width = right - left
            height = bottom - top
            cx = (left + right) // 2
            cy = (top + bottom) // 2
            
            # Avoid negative or empty bounds
            if width <= 0 or height <= 0 or left < 0 or top < 0:
                continue
                
            raw_nodes.append({
                "unique_id": node.unique_id,
                "resource_id": node.view_id_resource_name,
                "class_name": node.class_name,
                "text": node.text,
                "content_desc": node.content_description,
                "clickable": node.is_clickable,
                "bounds": f"[{left},{top}][{right},{bottom}]",
                "center_x": cx,
                "center_y": cy,
                "width": width,
                "height": height,
                "child_ids": list(node.child_ids)
            })
            
    # Perform child label bubbling (same logic as in ui_parser)
    nodes_by_id = {n["unique_id"]: n for n in raw_nodes}
    
    def get_child_text(node):
        texts = []
        for cid in node.get("child_ids", []):
            if cid in nodes_by_id:
                child = nodes_by_id[cid]
                if child["text"]:
                    texts.append(child["text"])
                if child["content_desc"]:
                    texts.append(child["content_desc"])
                texts.extend(get_child_text(child))
        return texts

    for node in raw_nodes:
        if node["class_name"] in _CONTAINER_CLASSES and node["clickable"]:
            if not node["text"] and not node["content_desc"]:
                # Bubble up child labels
                child_labels = get_child_text(node)
                if child_labels:
                    node["text"] = " | ".join(dict.fromkeys(child_labels))

    # Merge nodes with identical center coordinates
    merged_nodes = {}
    for node in raw_nodes:
        key = (node["center_x"], node["center_y"])
        if key not in merged_nodes:
            merged_nodes[key] = node
        else:
            existing = merged_nodes[key]
            # Merge fields
            if node["text"] and not existing["text"]:
                existing["text"] = node["text"]
            if node["content_desc"] and not existing["content_desc"]:
                existing["content_desc"] = node["content_desc"]
            if node["resource_id"] and not existing["resource_id"]:
                existing["resource_id"] = node["resource_id"]
            if node["clickable"]:
                existing["clickable"] = True
            if existing["class_name"] in _CONTAINER_CLASSES and node["class_name"] not in _CONTAINER_CLASSES:
                existing["class_name"] = node["class_name"]

    elements = list(merged_nodes.values())
    return elements

def format_elements(elements):
    """
    Formats parsed elements into the agent's expected prompt representation.
    """
    # Sort: clickable first, then by center_y
    sorted_els = sorted(elements, key=lambda e: (not e["clickable"], e["center_y"]))
    
    # Filter container views without labels
    filtered = []
    for el in sorted_els:
        is_container = el["class_name"] in _CONTAINER_CLASSES
        if bool(el["text"] or el["content_desc"]) or not is_container:
            filtered.append(el)
            
    capped = filtered[:60]
    
    formatted_lines = []
    for i, el in enumerate(capped):
        parts = [f"[{i}]"]
        if el["text"]:
            parts.append(f"text={repr(el['text'])}")
        if el["content_desc"]:
            parts.append(f"desc={repr(el['content_desc'])}")
        if el["resource_id"]:
            parts.append(f"id={repr(el['resource_id'])}")
        if el["clickable"]:
            parts.append("clickable=True")
        parts.append(f"center=({el['center_x']},{el['center_y']})")
        formatted_lines.append(" ".join(parts))
        
    return "\n".join(formatted_lines), capped

def main():
    print("Loading Google AndroidControl dataset TFRecord...")
    # Stream one shard directly from GCS bucket
    dataset_url = "gs://gresearch/android_control/android_control-00000-of-00020"
    raw_dataset = tf.data.TFRecordDataset([dataset_url], compression_type="GZIP")
    
    converted_records = []
    
    # Process first 50 episodes
    print("Processing episodes...")
    for idx, raw_record in enumerate(raw_dataset.take(50)):
        ex = tf.train.Example.FromString(raw_record.numpy())
        
        goal = ex.features.feature["goal"].bytes_list.value[0].decode("utf-8")
        raw_actions = ex.features.feature["actions"].bytes_list.value
        accessibility_trees = ex.features.feature["accessibility_trees"].bytes_list.value
        width = ex.features.feature["screenshot_widths"].int64_list.value[0]
        height = ex.features.feature["screenshot_heights"].int64_list.value[0]
        
        # Actions are between screenshots. If N accessibility trees, there are N-1 actions.
        num_steps = len(raw_actions)
        
        history = []
        
        for step in range(num_steps):
            action_data = json.loads(raw_actions[step].decode("utf-8"))
            action_type = action_data.get("action_type", "").lower()
            
            # Parse accessibility tree for current step
            tree_bytes = accessibility_trees[step]
            elements = parse_proto_tree(tree_bytes)
            
            # Format UI elements for model input
            ui_str, capped_els = format_elements(elements)
            
            # Format history block
            history_str = "\n".join(f"  {h}" for h in history[-5:]) or "  (none)"
            
            # Parse assistant completion
            skill = ""
            args_str = ""
            
            if action_type == "open_app":
                app_name = action_data.get("app_name", "unknown")
                skill = "open_app"
                args_str = f"package_name={app_name}"
            elif action_type in ["click", "long_press"]:
                # Map coordinates
                x_val = action_data.get("x", 0.0)
                y_val = action_data.get("y", 0.0)
                
                # Check if absolute or normalized
                x_pixel = int(x_val * width) if isinstance(x_val, float) and x_val <= 1.0 else int(x_val)
                y_pixel = int(y_val * height) if isinstance(y_val, float) and y_val <= 1.0 else int(y_val)
                
                # Find matching UI element
                target_idx = -1
                for i, el in enumerate(capped_els):
                    # Check if pixel falls inside element bounds
                    bounds_str = el["bounds"].replace("][", ",").replace("[", "").replace("]", "")
                    left, top, right, bottom = map(int, bounds_str.split(","))
                    if left <= x_pixel <= right and top <= y_pixel <= bottom:
                        target_idx = i
                        break
                        
                skill = "tap"
                if target_idx != -1:
                    args_str = f"id={target_idx}"
                else:
                    args_str = f"x={x_pixel} y={y_pixel}"
            elif action_type == "input_text":
                text = action_data.get("text", "")
                skill = "type_text"
                args_str = f"text={repr(text)}"
            elif action_type == "navigate_home":
                skill = "press_key"
                args_str = "key=HOME"
            elif action_type == "navigate_back":
                skill = "press_key"
                args_str = "key=BACK"
            elif action_type == "key_enter":
                skill = "press_key"
                args_str = "key=ENTER"
            elif action_type == "scroll":
                dir_val = action_data.get("direction", "down")
                if isinstance(dir_val, int):
                    dir_map = {1: "up", 2: "down", 3: "left", 4: "right"}
                    dir_val = dir_map.get(dir_val, "down")
                
                skill = "scroll"
                if dir_val == "up":
                    args_str = "x1=500 y1=500 x2=500 y2=1500"
                elif dir_val == "down":
                    args_str = "x1=500 y1=1500 x2=500 y2=500"
                elif dir_val == "left":
                    args_str = "x1=200 y1=1000 x2=800 y2=1000"
                else:
                    args_str = "x1=800 y1=1000 x2=200 y2=1000"
            else:
                # Default fallback or skip
                continue
                
            user_content = f"Task: {goal}\n\nAction History:\n{history_str}\n\nUI Elements:\n{ui_str}"
            assistant_content = f"SKILL: {skill}\nARGS: {args_str}"
            
            example = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": assistant_content}
                ]
            }
            converted_records.append(example)
            
            # Record successfully converted step to history
            history.append(f"{skill}({args_str}) → SUCCESS")
            
        if (idx + 1) % 10 == 0:
            print(f"Processed {idx + 1} episodes, collected {len(converted_records)} training steps.")
            
    print(f"Total Google steps converted: {len(converted_records)}")
    
    # Save the output
    out_dir = PROJECT_ROOT / "storage"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "google_converted_data.jsonl"
    
    with open(out_file, "w", encoding="utf-8") as f:
        for record in converted_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
    print(f"Successfully converted and saved Google data to: {out_file}")

if __name__ == "__main__":
    main()
