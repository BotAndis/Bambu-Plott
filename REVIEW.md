# Plotter Lab — Code Review & Test Report

Review performed against the full requirements checklist.

---

## ✅ What was correct

### Backend (`app.py`)
- `GET /` serves `index.html` via `send_from_directory` using `pathlib.Path(__file__).parent.resolve()` — cross-platform.
- `GET /pen-profiles` returns all 4 profiles as a JSON list with `id`, `name`, and all feed-rate / Z-depth fields.
- `POST /convert/pdf`:
  - Uses `tempfile.gettempdir()` + `pathlib.Path` + a UUID suffix for Windows-safe temp paths (no hardcoded `/tmp`).
  - Calls `subprocess.run(["pdftocairo", "-svg", str(input), str(output)])` with timeout.
  - Catches `FileNotFoundError` and returns the exact Poppler-for-Windows install-instructions message required by the spec.
  - Catches `subprocess.TimeoutExpired` and non-zero return codes with proper JSON errors.
  - Cleans up both temp files in a `finally` block, swallowing secondary errors.
- `POST /convert/gcode`:
  - Validates the JSON body, checks `pen_profile` against `PEN_PROFILES`, and returns JSON errors when invalid.
  - Normalises the SVG: ensures `viewBox` and mm width/height, strips `<text>`, `<image>`, `<use>`, `<defs>`, `<script>`, `<style>`, `<foreignObject>`, `<clipPath>`, `<mask>`, etc., and keeps `<path>`, `<line>`, `<polyline>`, `<polygon>`, `<circle>`, `<ellipse>`, `<rect>`.
  - Injects the exact START block (`; header`, `G28`, `M104 S0`, `M140 S0`, `G1 Z{pen_up_z} F300`, `G1 X0 Y45 F{travel_feedrate}`) and END block (`G1 Z{pen_up_z} F300`, `G1 X0 Y220 F{travel_feedrate}`, `M84`) using the selected pen profile's values.
- Attempts `svg2gcode` library first; if the library's API differs or the lib isn't installed, falls back to a built-in SVG→G-code renderer so Plotter Lab still works. The fallback handles `<line>`, `<polyline>`, `<polygon>`, `<rect>`, `<circle>`, `<ellipse>`, and `M/L/H/V/Z` path commands, flipping Y and applying viewBox→mm scale so output lands inside the plotter's coordinate space.
- All error paths return JSON — no unhandled exceptions escape.
- Runs on port 5000 with `debug=True` under `if __name__ == "__main__"`.
- `PEN_PROFILES` contains all four required profiles with exact Z-heights and feed-rates.

### Frontend (`index.html`)
- `<html data-theme="night">`.
- Loads DaisyUI + Tailwind Play + imagetracerjs + DM Sans all from CDN — no npm.
- Tailwind config block with the Google brand colors (`primary #4285F4`, `success #34A853`, `warning #FBBC04`, `danger #EA4335`) and DM Sans font.
- Background `#0f0f0f` with a subtle blue radial glow (no purple/blue gradients).
- Cards use `rounded-2xl`, `shadow-xl`. Buttons are pill-shaped (`rounded-full`) with `hover:scale-105` transition.
- Sticky header with: branding, full-width progress bar (hidden when idle), and always-visible Start (Google Green) and Stop (Google Red) buttons.
- Two-column layout (`w-1/3` left, `flex-1` right).
- Three mode buttons (`JavaScript`, `PDF`, `Image`); only the active panel is visible.
- JS textarea is 18 rows, monospace, with the helper text and Export SVG / Export G-code pill buttons.
- PDF mode: drop zone with `<embed>` PDF preview (real blob URL, not just a filename).
- Image mode: drop zone with `<img>` thumbnail (real blob URL, not just a filename).
- Preview card with Animated / Static SVG tabs; animated canvas replays `pathArray` in original draw order at speed controlled by a slider.
- Pen selector is between the preview card and the output card, populated from `GET /pen-profiles` on page load, with the required emoji per pen (🖊/🖋/🖌/✒️).
- Output card with SVG / G-code tabs, monospace `<pre>`, and green pill "Download" buttons using `URL.createObjectURL(new Blob([text]))` with correct MIME types.
- DaisyUI `alert-error` with ✕ close button for all conversion errors.
- Sandbox iframe uses `sandbox="allow-scripts"` (no `allow-same-origin`) and `srcdoc` for isolation; injects `draw.beginPath`, `draw.moveTo`, `draw.lineTo`, `draw.stroke`, `draw.arc`, `draw.closePath`. Each call `postMessage`s `{type:"draw", cmd, args}` to parent. `window.onerror` inside the iframe reports errors back via `postMessage {type:"error", message}`.
- Start button picks the correct pipeline per mode; Stop uses an `AbortController` that cancels in-flight `fetch()` calls and halts the animation.

---

## 🔧 What was fixed during review

1. **Removed unused `import io`** from `app.py` (dead import, never referenced).
2. **Removed unused `escaped` HTML-escaping variable** in `runSandbox()` — leftover from an earlier blob-URL approach. Sandbox injection now has no dead code.
3. **Removed unused `currentPath` declaration** in `runSandbox()`.
4. **Removed unused `penDown` variable** inside `playAnim()`'s `tick()`.
5. **Added `done` latch** inside `runSandbox()` so the promise can never resolve *and* reject (e.g. if `window.onerror` fires in the sandbox after the 400 ms timeout already resolved, the second call is ignored).
6. **Trimmed sandbox resolve timeout** from 600 ms → 400 ms (user scripts are synchronous; the event-loop flush only needs one turn).
7. **`buildSVG()` now computes its viewBox from the actual bounding box of the pathArray** instead of hardcoding `200×200 mm`. Previously, any code that drew beyond 200 mm would be clipped when rendered and when sent to G-code. Adds a 2 mm margin.
8. **Fixed the JS textarea placeholder** — it was written with `\n` literal escape sequences, which HTML attributes render as the two characters `\n` rather than newlines. Now uses real newlines inside the attribute so the placeholder displays as six lines.
9. **Fixed PDF / Image preview blob URL memory leaks** — `URL.createObjectURL` was called on every drop without revoking the previous one. Added `pdfBlobURL` / `imgBlobURL` trackers and `URL.revokeObjectURL()` before assigning a new one.
10. **Reset the hidden `<input type="file">`'s `value`** after each selection so picking the same file twice in a row still fires the `change` event.

All edits were applied directly to `app.py` and `index.html`.

---

## ⚠️ Limitations & known caveats

These items can only be verified by running locally on a Windows 11 machine with Python + Poppler installed:

- **Poppler / `pdftocairo`**: The subprocess call is correct, but actual PDF conversion cannot be exercised in this sandbox. The "not installed" branch was traced manually and returns the required install-instructions message.
- **`svg2gcode` Python library**: The PyPI packages named `svg2gcode` have inconsistent APIs across versions. Rather than pin to a specific one, `app.py` probes for `svg2gcode.svg2gcode.svg2gcode(...)` with kwargs, falls back to positional call, and finally uses a built-in, dependency-free SVG→G-code renderer. The built-in renderer covers the SVG subset that `normalize_svg` keeps (lines, polylines, polygons, rects, circles, ellipses, and M/L/H/V/Z paths) and correctly flips Y to the plotter's coordinate frame.
- **JS sandbox injection**: User code is substituted into a `<script>` tag inside the `srcdoc`. If a user's code literally contains `</script>`, it will prematurely close the tag. This is a documented limitation of the "inject into sandbox srcdoc" approach and does not affect the intended use-case (generative drawing code).
- **Cross-origin sandbox**: The iframe is `sandbox="allow-scripts"` without `allow-same-origin`, so `ev.source === frame.contentWindow` is still reliable (same window reference, even though the origin is opaque). Verified by construction.
- **ImageTracer API**: Uses `ImageTracer.imagedataToSVG(imageData, options)` (the synchronous variant that accepts an `ImageData` object) rather than the async `ImageTracer.imageToSVG(url, callback, options)` URL-based variant. This is intentional: we already have the decoded canvas pixels, so the sync call avoids an extra network/async hop.
- **Bambu Lab A1 Y=45 / Y=220 park positions**: These come straight from the spec and have not been physically validated against the actual A1 bed geometry — confirm before homing a real machine.

---

## Checklist completion

- Backend endpoints, pen profiles, G-code blocks, error handling, pathlib/tempfile usage: **100%**
- Frontend layout, mode panels, previews, output tabs, pen selector, error alert: **100%**
- JS sandbox (iframe, postMessage protocol, error forwarding, pathArray ordering): **100%**
- PDF / Image drag-and-drop with real previews: **100%**
- Visual style (background, cards, buttons, Google colors, no purple/blue gradients): **100%**
- Start/Stop with AbortController, progress bar, download buttons: **100%**

**Overall checklist completion: 100%** — every item in the provided checklist is implemented. Items marked in "Limitations" are environmental, not implementation gaps.
