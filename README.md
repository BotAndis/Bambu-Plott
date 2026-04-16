# Plotter Lab

A local web app that converts JavaScript generative art, vector PDFs, and raster images into SVG and G-code for the **Bambu Lab A1** pen plotter.

---

## Setup (Windows 11)

### 1. Install Python dependencies

```
pip install -r requirements.txt
```

### 2. Install Poppler (for PDF conversion)

PDF → SVG conversion requires the `pdftocairo` tool from Poppler.

1. Download the latest Windows build from: https://github.com/oschwartz10612/poppler-windows/releases
2. Extract the archive (e.g. to `C:\poppler`)
3. Add `C:\poppler\Library\bin` to your system `PATH`
4. Verify: open a new terminal and run `pdftocairo -v`

### 3. Start the app

```
python app.py
```

Open **http://localhost:5000** in your browser.

---

## Modes

| Mode | Input | Notes |
|------|-------|-------|
| **JavaScript** | Generative JS code | Uses `draw.*` API — see below |
| **PDF** | Vector PDF file | Requires Poppler / pdftocairo |
| **Image** | PNG or JPEG | Auto-traced to vectors using imagetracerjs |

### JavaScript draw API

Paste code that calls these functions — no imports needed:

```js
draw.moveTo(x, y)          // lift pen and move
draw.lineTo(x, y)          // draw line to point
draw.stroke()              // commit current path
draw.arc(cx, cy, r, startAngle, endAngle)  // arc (angles in radians)
draw.closePath()           // close current subpath
draw.beginPath()           // start a new path explicitly
```

Example — a simple spiral:

```js
const cx = 100, cy = 100;
for (let i = 0; i < 500; i++) {
  const angle = 0.1 * i;
  const r = 0.3 * i;
  const x = cx + r * Math.cos(angle);
  const y = cy + r * Math.sin(angle);
  if (i === 0) draw.moveTo(x, y);
  else draw.lineTo(x, y);
}
draw.stroke();
```

---

## Pen Profiles

Four built-in profiles control Z-height and feed rates:

| ID | Name | Pen-down Z | Pen-up Z | Draw feedrate | Travel feedrate |
|----|------|-----------|----------|---------------|-----------------|
| `fine_liner`    | Fine Liner (0.1mm) | 0.2 mm | 3.0 mm | 3000 mm/min | 4800 mm/min |
| `ballpoint`     | Ballpoint Pen      | 0.3 mm | 3.0 mm | 2500 mm/min | 4800 mm/min |
| `marker`        | Marker (broad)     | 0.5 mm | 4.0 mm | 2000 mm/min | 4800 mm/min |
| `technical_pen` | Technical Pen      | 0.1 mm | 3.0 mm | 1500 mm/min | 4800 mm/min |

### Adding a custom pen

Edit `PEN_PROFILES` at the top of `app.py`:

```python
PEN_PROFILES["my_pen"] = {
    "name": "My Custom Pen",
    "pen_down_z": 0.25,
    "pen_up_z": 3.5,
    "draw_feedrate": 2200,
    "travel_feedrate": 4800,
}
```

Restart `app.py` and your pen will appear in the dropdown.

---

## Sending G-code to the Bambu A1

### Option A — SD Card

1. Click **⬇ Download G-code** to save the `.gcode` file
2. Copy it to a microSD card
3. Insert the SD card into the A1 and print from the touchscreen

### Option B — Bambu Studio (LAN mode)

1. Open **Bambu Studio** and connect to your A1 over LAN
2. Go to **Device** → **Send G-code**
3. Select the downloaded `.gcode` file
4. Confirm the pen is loaded before printing

> **Safety note**: The generated G-code homes the machine (`G28`) and sets hot-end and bed temperatures to 0 (`M104 S0` / `M140 S0`) so the plotter runs cold. Always confirm the pen is correctly mounted and the bed is clear before starting a print.

---

## File Structure

```
.
├── app.py           # Flask backend
├── index.html       # Single-page frontend (served by Flask)
├── requirements.txt # Python dependencies
└── README.md        # This file
```
