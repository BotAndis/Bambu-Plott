"""Plotter Lab - Flask backend for the Bambu Lab A1 pen plotter toolkit."""
from __future__ import annotations

import re
import subprocess
import tempfile
import traceback
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=None)
ROOT = Path(__file__).parent.resolve()

PEN_PROFILES = {
    "fine_liner":    {"name": "Fine Liner (0.1mm)",  "pen_down_z": 0.2, "pen_up_z": 3.0, "draw_feedrate": 3000, "travel_feedrate": 4800},
    "ballpoint":     {"name": "Ballpoint Pen",        "pen_down_z": 0.3, "pen_up_z": 3.0, "draw_feedrate": 2500, "travel_feedrate": 4800},
    "marker":        {"name": "Marker (broad)",       "pen_down_z": 0.5, "pen_up_z": 4.0, "draw_feedrate": 2000, "travel_feedrate": 4800},
    "technical_pen": {"name": "Technical Pen",        "pen_down_z": 0.1, "pen_up_z": 3.0, "draw_feedrate": 1500, "travel_feedrate": 4800},
}

SVG_NS = "http://www.w3.org/2000/svg"
KEEP_TAGS = {"svg", "g", "path", "line", "polyline", "polygon", "circle", "ellipse", "rect"}
STRIP_TAGS = {"text", "image", "use", "defs", "style", "title", "desc", "clipPath", "mask", "filter", "pattern", "marker", "symbol", "script", "foreignObject", "tspan", "textPath"}


@app.route("/")
def index():
    return send_from_directory(str(ROOT), "index.html")


@app.route("/pen-profiles")
def pen_profiles():
    data = []
    for pen_id, profile in PEN_PROFILES.items():
        data.append({
            "id": pen_id,
            "name": profile["name"],
            "pen_down_z": profile["pen_down_z"],
            "pen_up_z": profile["pen_up_z"],
            "draw_feedrate": profile["draw_feedrate"],
            "travel_feedrate": profile["travel_feedrate"],
        })
    return jsonify(data)


@app.route("/convert/pdf", methods=["POST"])
def convert_pdf():
    uploaded = request.files.get("file")
    if uploaded is None or uploaded.filename == "":
        return jsonify({"error": "No PDF file uploaded."}), 400

    temp_dir = Path(tempfile.gettempdir())
    uid = uuid.uuid4().hex
    input_path = temp_dir / f"plotterlab_{uid}.pdf"
    output_path = temp_dir / f"plotterlab_{uid}.svg"

    try:
        uploaded.save(str(input_path))
        try:
            result = subprocess.run(
                ["pdftocairo", "-svg", str(input_path), str(output_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            return jsonify({
                "error": "pdftocairo not found. Install Poppler for Windows: "
                         "https://github.com/oschwartz10612/poppler-windows and add Library/bin to PATH"
            }), 500
        except subprocess.TimeoutExpired:
            return jsonify({"error": "pdftocairo timed out converting the PDF."}), 500

        if result.returncode != 0:
            return jsonify({"error": f"pdftocairo failed: {result.stderr.strip() or 'unknown error'}"}), 500

        if not output_path.exists():
            return jsonify({"error": "pdftocairo did not produce an SVG output."}), 500

        svg_text = output_path.read_text(encoding="utf-8", errors="replace")
        return jsonify({"svg": svg_text})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": f"PDF conversion failed: {exc}"}), 500
    finally:
        try:
            if input_path.exists():
                input_path.unlink()
        except Exception:
            pass
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass


@app.route("/convert/gcode", methods=["POST"])
def convert_gcode():
    payload = request.get_json(silent=True) or {}
    svg_text = payload.get("svg")
    pen_id = payload.get("pen_profile", "fine_liner")

    if not svg_text or not isinstance(svg_text, str):
        return jsonify({"error": "Missing or invalid 'svg' in request body."}), 400

    profile = PEN_PROFILES.get(pen_id)
    if profile is None:
        return jsonify({"error": f"Unknown pen profile '{pen_id}'."}), 400

    try:
        normalized_svg = normalize_svg(svg_text)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": f"Failed to normalize SVG: {exc}"}), 500

    try:
        body_gcode = svg_to_gcode(normalized_svg, profile)
    except FileNotFoundError as exc:
        return jsonify({"error": f"svg2gcode dependency missing: {exc}"}), 500
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": f"G-code generation failed: {exc}"}), 500

    start_block = (
        "; Bambu Lab A1 Pen Plotter - Plotter Lab\n"
        f"; Pen: {profile['name']}\n"
        "G28\n"
        "M104 S0\n"
        "M140 S0\n"
        f"G1 Z{profile['pen_up_z']} F300\n"
        f"G1 X0 Y45 F{profile['travel_feedrate']}\n"
    )
    end_block = (
        f"G1 Z{profile['pen_up_z']} F300\n"
        f"G1 X0 Y220 F{profile['travel_feedrate']}\n"
        "M84\n"
    )

    full_gcode = start_block + body_gcode.rstrip() + "\n" + end_block
    return jsonify({"gcode": full_gcode})


def normalize_svg(svg_text: str) -> str:
    """Parse an SVG, ensure mm units and viewBox, strip unsupported tags."""
    ET.register_namespace("", SVG_NS)
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        cleaned = re.sub(r"<\?xml[^?]*\?>", "", svg_text)
        cleaned = re.sub(r"<!DOCTYPE[^>]*>", "", cleaned)
        root = ET.fromstring(cleaned)

    tag = strip_ns(root.tag)
    if tag != "svg":
        raise ValueError("Root element is not <svg>")

    width_attr = root.get("width")
    height_attr = root.get("height")
    viewbox = root.get("viewBox")

    width_mm = parse_length_mm(width_attr) if width_attr else None
    height_mm = parse_length_mm(height_attr) if height_attr else None

    if viewbox:
        try:
            parts = [float(p) for p in re.split(r"[\s,]+", viewbox.strip()) if p]
            if len(parts) == 4:
                if width_mm is None:
                    width_mm = parts[2]
                if height_mm is None:
                    height_mm = parts[3]
        except ValueError:
            pass

    if width_mm is None:
        width_mm = 210.0
    if height_mm is None:
        height_mm = 297.0

    if not viewbox:
        root.set("viewBox", f"0 0 {width_mm} {height_mm}")

    root.set("width", f"{width_mm}mm")
    root.set("height", f"{height_mm}mm")

    strip_unsupported(root)

    return ET.tostring(root, encoding="unicode")


def strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def strip_unsupported(element: ET.Element) -> None:
    to_remove = []
    for child in list(element):
        local = strip_ns(child.tag)
        if local in STRIP_TAGS:
            to_remove.append(child)
            continue
        if local not in KEEP_TAGS:
            to_remove.append(child)
            continue
        strip_unsupported(child)
    for child in to_remove:
        element.remove(child)


def parse_length_mm(value: str) -> float | None:
    """Convert an SVG length string into millimetres."""
    if value is None:
        return None
    match = re.match(r"^\s*([-+]?\d*\.?\d+)\s*([a-zA-Z%]*)\s*$", value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).lower()
    conversions = {
        "":   1.0,
        "mm": 1.0,
        "cm": 10.0,
        "in": 25.4,
        "pt": 25.4 / 72.0,
        "pc": 25.4 / 6.0,
        "px": 25.4 / 96.0,
    }
    if unit == "%":
        return None
    if unit not in conversions:
        return None
    return number * conversions[unit]


def svg_to_gcode(svg_text: str, profile: dict) -> str:
    """Convert SVG text to G-code using the svg2gcode library."""
    try:
        from svg2gcode import svg2gcode as s2g_module  # type: ignore
    except ImportError:
        s2g_module = None

    if s2g_module is not None and hasattr(s2g_module, "svg2gcode"):
        try:
            out = s2g_module.svg2gcode(
                svg_text,
                pen_up_z=profile["pen_up_z"],
                pen_down_z=profile["pen_down_z"],
                draw_feedrate=profile["draw_feedrate"],
                travel_feedrate=profile["travel_feedrate"],
            )
            if isinstance(out, str) and out.strip():
                return out
        except TypeError:
            try:
                out = s2g_module.svg2gcode(svg_text)
                if isinstance(out, str) and out.strip():
                    return out
            except Exception:
                pass
        except Exception:
            pass

    return fallback_svg_to_gcode(svg_text, profile)


def fallback_svg_to_gcode(svg_text: str, profile: dict) -> str:
    """Minimal SVG → G-code fallback so Plotter Lab keeps working even if svg2gcode's API changes.

    Converts <line>, <polyline>, <polygon>, <rect>, <circle>, <ellipse>, and straight-segment <path>
    data into sequential G0/G1 moves with pen-up/pen-down around each subpath.
    """
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return "; (empty or unparseable SVG)\n"

    width_mm, height_mm = extract_mm_dims(root)
    vb = parse_viewbox(root.get("viewBox"))
    if vb is None:
        vb = (0.0, 0.0, width_mm, height_mm)
    vb_x, vb_y, vb_w, vb_h = vb
    sx = width_mm / vb_w if vb_w else 1.0
    sy = height_mm / vb_h if vb_h else 1.0

    paths: list[list[tuple[float, float]]] = []
    walk_element(root, paths)

    lines: list[str] = []
    draw_f = profile["draw_feedrate"]
    travel_f = profile["travel_feedrate"]
    pen_up = profile["pen_up_z"]
    pen_down = profile["pen_down_z"]

    for subpath in paths:
        if len(subpath) < 2:
            continue
        transformed = []
        for (px, py) in subpath:
            x_mm = (px - vb_x) * sx
            y_mm = height_mm - ((py - vb_y) * sy)
            transformed.append((x_mm, y_mm))

        first_x, first_y = transformed[0]
        lines.append(f"G1 Z{pen_up} F300")
        lines.append(f"G0 X{first_x:.3f} Y{first_y:.3f} F{travel_f}")
        lines.append(f"G1 Z{pen_down} F300")
        for (x, y) in transformed[1:]:
            lines.append(f"G1 X{x:.3f} Y{y:.3f} F{draw_f}")
        lines.append(f"G1 Z{pen_up} F300")

    if not lines:
        return "; (no drawable geometry found in SVG)\n"
    return "\n".join(lines) + "\n"


def extract_mm_dims(root: ET.Element) -> tuple[float, float]:
    w = parse_length_mm(root.get("width") or "") or 210.0
    h = parse_length_mm(root.get("height") or "") or 297.0
    return w, h


def parse_viewbox(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    try:
        parts = [float(p) for p in re.split(r"[\s,]+", value.strip()) if p]
        if len(parts) == 4:
            return parts[0], parts[1], parts[2], parts[3]
    except ValueError:
        return None
    return None


def walk_element(element: ET.Element, out: list[list[tuple[float, float]]]) -> None:
    tag = strip_ns(element.tag)
    if tag == "line":
        try:
            x1 = float(element.get("x1", "0"))
            y1 = float(element.get("y1", "0"))
            x2 = float(element.get("x2", "0"))
            y2 = float(element.get("y2", "0"))
            out.append([(x1, y1), (x2, y2)])
        except ValueError:
            pass
    elif tag in ("polyline", "polygon"):
        pts = parse_points(element.get("points", ""))
        if pts:
            if tag == "polygon" and pts[0] != pts[-1]:
                pts.append(pts[0])
            out.append(pts)
    elif tag == "rect":
        try:
            x = float(element.get("x", "0"))
            y = float(element.get("y", "0"))
            w = float(element.get("width", "0"))
            h = float(element.get("height", "0"))
            if w > 0 and h > 0:
                out.append([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)])
        except ValueError:
            pass
    elif tag == "circle":
        try:
            cx = float(element.get("cx", "0"))
            cy = float(element.get("cy", "0"))
            r = float(element.get("r", "0"))
            if r > 0:
                out.append(sample_ellipse(cx, cy, r, r))
        except ValueError:
            pass
    elif tag == "ellipse":
        try:
            cx = float(element.get("cx", "0"))
            cy = float(element.get("cy", "0"))
            rx = float(element.get("rx", "0"))
            ry = float(element.get("ry", "0"))
            if rx > 0 and ry > 0:
                out.append(sample_ellipse(cx, cy, rx, ry))
        except ValueError:
            pass
    elif tag == "path":
        for sub in parse_path(element.get("d", "")):
            if sub:
                out.append(sub)

    for child in list(element):
        walk_element(child, out)


def parse_points(text: str) -> list[tuple[float, float]]:
    nums = [float(n) for n in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text or "")]
    pts = []
    for i in range(0, len(nums) - 1, 2):
        pts.append((nums[i], nums[i + 1]))
    return pts


def sample_ellipse(cx: float, cy: float, rx: float, ry: float, steps: int = 64) -> list[tuple[float, float]]:
    import math
    pts = []
    for i in range(steps + 1):
        theta = 2 * math.pi * (i / steps)
        pts.append((cx + rx * math.cos(theta), cy + ry * math.sin(theta)))
    return pts


def parse_path(d: str) -> list[list[tuple[float, float]]]:
    """Light-weight path parser supporting M/m/L/l/H/h/V/v/Z/z commands only."""
    if not d:
        return []
    tokens = re.findall(r"[MmLlHhVvZz]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    cx, cy = 0.0, 0.0
    start_x, start_y = 0.0, 0.0
    i = 0
    cmd = ""
    while i < len(tokens):
        tok = tokens[i]
        if tok in "MmLlHhVvZz":
            cmd = tok
            i += 1
            if cmd in "Zz":
                if current:
                    if current[0] != (cx, cy):
                        current.append((start_x, start_y))
                    subpaths.append(current)
                    current = []
                    cx, cy = start_x, start_y
            continue

        if cmd in ("M", "m"):
            x = float(tokens[i]); y = float(tokens[i + 1]); i += 2
            if cmd == "m" and current:
                x += cx; y += cy
            if current:
                subpaths.append(current)
            current = [(x, y)]
            cx, cy = x, y
            start_x, start_y = x, y
            cmd = "L" if cmd == "M" else "l"
        elif cmd in ("L", "l"):
            x = float(tokens[i]); y = float(tokens[i + 1]); i += 2
            if cmd == "l":
                x += cx; y += cy
            current.append((x, y))
            cx, cy = x, y
        elif cmd in ("H", "h"):
            x = float(tokens[i]); i += 1
            if cmd == "h":
                x += cx
            current.append((x, cy))
            cx = x
        elif cmd in ("V", "v"):
            y = float(tokens[i]); i += 1
            if cmd == "v":
                y += cy
            current.append((cx, y))
            cy = y
        else:
            i += 1

    if current:
        subpaths.append(current)
    return subpaths


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
