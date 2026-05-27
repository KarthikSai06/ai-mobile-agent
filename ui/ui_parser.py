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
    # When two elements share the same (x, y), keep the richest one.
    seen: dict = {}   # coord -> index in deduped list
    deduped = []
    for el in elements:
        coord = (el["center_x"], el["center_y"])
        if coord in seen:
            existing_idx = seen[coord]
            if _richness(el) > _richness(deduped[existing_idx]):
                deduped[existing_idx] = el   # replace ghost with richer entry
        else:
            seen[coord] = len(deduped)
            deduped.append(el)

    return deduped


def format_ui_elements_for_llm(elements: list, max_elements: int = 80) -> str:
    """
    Formats parsed UI elements into a compact string for the LLM.

    Improvements over original:
    - Sorts clickable elements first (most actionable for the agent)
    - Caps at max_elements (default 80) to avoid overwhelming context window
    """
    # Sort: clickable first, then top-to-bottom reading order
    sorted_els = sorted(elements, key=lambda e: (not e["clickable"], e["center_y"]))
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
