import xml.etree.ElementTree as ET
import re


def parse_bounds(bounds_str: str) -> tuple:
    """
    Parses a bounds string like '[0,152][1080,288]'
    into center coordinates (x, y) and bounding box.
    Returns (center_x, center_y, width, height, x1, y1, x2, y2)
    """
    match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
    if not match:
        return (0, 0, 0, 0, 0, 0, 0, 0)

    x1, y1, x2, y2 = map(int, match.groups())
    center_x = (x1 + x2) // 2
    center_y = (y1 + y2) // 2
    width = x2 - x1
    height = y2 - y1

    return (center_x, center_y, width, height, x1, y1, x2, y2)


def _richness(el: dict) -> int:
    """Score how much useful info an element has. Higher = keep it on dedup."""
    score = 0
    if el["text"]:          score += 4
    if el["content_desc"]:  score += 3
    if el["resource_id"]:   score += 2
    if el["clickable"]:     score += 1
    return score


# Pure container class names that carry no semantic value when they have no text/desc.
_CONTAINER_CLASSES = {
    "android.widget.FrameLayout",
    "android.widget.LinearLayout",
    "android.widget.RelativeLayout",
    "android.view.View",
    "android.view.ViewGroup",
    "androidx.coordinatorlayout.widget.CoordinatorLayout",
    "androidx.constraintlayout.widget.ConstraintLayout",
}


def _find_text_in_children(node) -> tuple:
    """Recursively search child nodes for text and content-desc."""
    text = ""
    desc = ""
    for child in node.iter("node"):
        if child == node:
            continue
        ctext = child.attrib.get("text", "")
        cdesc = child.attrib.get("content-desc", "")
        if ctext and not text:
            text = ctext
        if cdesc and not desc:
            desc = cdesc
        if text and desc:
            break
    return text, desc


def parse_ui_xml(xml_path: str) -> list:
    """
    Parses the UI automation XML file and returns a deduplicated element list.

    KEY FIX — Ghost element deduplication:
    Android's view hierarchy wraps every interactive element inside a parent
    container (clickable=True, no text/desc). Both the parent and child share
    IDENTICAL center coordinates. Without deduplication the LLM sees:

        [36] desc='Home, Tab 1 of 5' center=(108,2286)
        [37] clickable=True center=(324,2286)          ← ghost container
        [38] desc='Search, Tab 2 of 5' center=(324,2286)

    The ghost doubles the element list, corrupts indices, and causes the LLM
    to pick the wrong ID. We deduplicate by center coordinate, keeping the
    entry with the most useful information (text > desc > resource_id > clickable).
    """
    elements = []

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"Failed to parse XML: {e}")
        return elements

    for node in root.iter("node"):
        bounds_str = node.attrib.get("bounds", "")
        if not bounds_str or bounds_str == "[0,0][0,0]":
            continue

        c_x, c_y, w, h, x1, y1, x2, y2 = parse_bounds(bounds_str)

        # Skip invisible / zero-size containers
        if w < 5 or h < 5:
            continue

        text         = node.attrib.get("text", "")
        content_desc = node.attrib.get("content-desc", "")
        resource_id  = node.attrib.get("resource-id", "")
        clickable    = node.attrib.get("clickable", "false").lower() == "true"
        class_name   = node.attrib.get("class", "")

        # Bubble up child text/desc to clickable containers that lack labels
        if clickable and not text and not content_desc and class_name in _CONTAINER_CLASSES:
            text, content_desc = _find_text_in_children(node)

        if clickable or text or content_desc:
            elements.append({
                "text":         text,
                "content_desc": content_desc,
                "resource_id":  resource_id,
                "class_name":   class_name,
                "clickable":    clickable,
                "bounds":       bounds_str,
                "center_x":     c_x,
                "center_y":     c_y,
                "width":        w,
                "height":       h,
            })

    # ── Deduplicate by center coordinate ────────────────────────────────────
    # When two elements share the same (x, y), merge their attributes and keep the richest.
    seen: dict = {}   # coord -> index in deduped list
    deduped = []
    for el in elements:
        coord = (el["center_x"], el["center_y"])
        if coord in seen:
            existing_idx = seen[coord]
            existing = deduped[existing_idx]
            
            # Merge text, content_desc, resource_id, and clickable properties
            if not existing["text"] and el["text"]:
                existing["text"] = el["text"]
            if not existing["content_desc"] and el["content_desc"]:
                existing["content_desc"] = el["content_desc"]
            if not existing["resource_id"] and el["resource_id"]:
                existing["resource_id"] = el["resource_id"]
            if el["clickable"]:
                existing["clickable"] = True
                
            # If the existing one is a container and the new one is not,
            # adopt the non-container class_name to prevent format_ui_elements_for_llm filtering.
            if existing["class_name"] in _CONTAINER_CLASSES and el["class_name"] not in _CONTAINER_CLASSES:
                existing["class_name"] = el["class_name"]
            
            # If the new one is richer, update existing keys while preserving non-container class
            if _richness(el) > _richness(existing):
                old_class = existing["class_name"]
                for k, v in el.items():
                    if k != "class_name":
                        existing[k] = v
                if old_class not in _CONTAINER_CLASSES:
                    existing["class_name"] = old_class
        else:
            seen[coord] = len(deduped)
            deduped.append(el.copy())

    return deduped


def format_ui_elements_for_llm(elements: list, max_elements: int = 60) -> str:
    """
    Formats parsed UI elements into a compact string for the LLM.

    Pipeline:
    1. Drop pure container views (no text, no desc, class is a layout container)
    2. Deduplicate elements with identical text + center coordinates
    3. Sort clickable elements first, then top-to-bottom reading order
    4. Cap at max_elements (default 60) to stay within context window
    """
    # Step 1 — Filter pure non-interactive containers
    filtered = []
    for el in elements:
        is_container = el["class_name"] in _CONTAINER_CLASSES
        has_label = bool(el["text"] or el["content_desc"])
        # Keep if it has a visible label OR it's not a container
        if has_label or not is_container:
            filtered.append(el)

    # Step 2 — Deduplicate: same text + center_x + center_y → keep richest
    seen_label_coord: dict = {}  # (text, center_x, center_y) -> index in deduped
    deduped: list = []
    for el in filtered:
        key = (el["text"].strip(), el["center_x"], el["center_y"])
        if key in seen_label_coord:
            existing_idx = seen_label_coord[key]
            if _richness(el) > _richness(deduped[existing_idx]):
                deduped[existing_idx] = el
        else:
            seen_label_coord[key] = len(deduped)
            deduped.append(el)

    # Step 3 — Sort: clickable first, then top-to-bottom reading order
    sorted_els = sorted(deduped, key=lambda e: (not e["clickable"], e["center_y"]))

    # Step 4 — Cap
    capped = sorted_els[:max_elements]

    lines = []
    for idx, el in enumerate(capped):
        parts = [f"[{idx}]"]
        if el["text"]:
            parts.append(f"text='{el['text']}'")
        if el["content_desc"]:
            parts.append(f"desc='{el['content_desc']}'")
        if el["resource_id"]:
            parts.append(f"id='{el['resource_id']}'")
        if el["clickable"]:
            parts.append("clickable=True")
        parts.append(f"center=({el['center_x']},{el['center_y']})")
        lines.append(" ".join(parts))

    return "\n".join(lines)
