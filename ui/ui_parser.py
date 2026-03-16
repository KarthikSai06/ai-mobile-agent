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

def parse_ui_xml(xml_path: str) -> list:
    """
    Parses the UI automation XML file.
    Returns a list of dictionaries containing properties of elements.
    """
    elements = []
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"Failed to parse XML: {e}")
        return elements

    # Traverse all node elements
    for node in root.iter("node"):
        bounds_str = node.attrib.get("bounds", "")
        if not bounds_str or bounds_str == "[0,0][0,0]":
             continue

        c_x, c_y, w, h, x1, y1, x2, y2 = parse_bounds(bounds_str)
        text = node.attrib.get("text", "")
        content_desc = node.attrib.get("content-desc", "")
        resource_id = node.attrib.get("resource-id", "")
        clickable = node.attrib.get("clickable", "false").lower() == "true"
        class_name = node.attrib.get("class", "")

        # Typically, we only care about interactable elements or elements with text
        if clickable or text or content_desc:
            element_info = {
                "text": text,
                "content_desc": content_desc,
                "resource_id": resource_id,
                "class_name": class_name,
                "clickable": clickable,
                "bounds": bounds_str,
                "center_x": c_x,
                "center_y": c_y,
                "width": w,
                "height": h
            }
            elements.append(element_info)

    return elements

def format_ui_elements_for_llm(elements: list) -> str:
    """
    Formats the parsed UI elements into a compact string prompt for the LLM.
    """
    lines = []
    for idx, el in enumerate(elements):
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
