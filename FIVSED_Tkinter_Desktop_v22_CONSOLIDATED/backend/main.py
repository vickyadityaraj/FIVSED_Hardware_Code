from __future__ import annotations

from flask import Flask, jsonify, request, render_template

# Allow both `python -m backend.main` (recommended) and direct execution
# of this file during development/testing.
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from backend.components import get_component_status
    from backend.config import config
    from backend.hardware_reader import hardware_reader
    from backend.pi_status import get_hardware_status, get_pi_status
    from backend.stm32_engine import stm32_engine
    from backend.storage import storage
else:
    from .components import get_component_status
    from .config import config
    from .hardware_reader import hardware_reader
    from .pi_status import get_hardware_status, get_pi_status
    from .stm32_engine import stm32_engine
    from .storage import storage

app = Flask(__name__, template_folder="templates")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "FIVSED Backend",
        "version": "2.0.0",
        "security_authority": "STM32",
    })


@app.get("/api/status")
def status():
    targets = hardware_reader.detect_connected_targets()
    return jsonify({
        "pi": get_pi_status(),
        "hardware": get_hardware_status(),
        "components": get_component_status(),
        "targets": targets,
        "registered_targets": sum(1 for t in targets if t.get("registered")),
        "poll_interval_seconds": config.serial.poll_interval_seconds,
    })


@app.get("/api/targets")
def get_targets():
    return jsonify(hardware_reader.detect_connected_targets())


@app.get("/api/targets/<target_id>")
def get_target(target_id: str):
    target = next((t for t in hardware_reader.detect_connected_targets() if t.get("id") == target_id), None)
    if target is None:
        return jsonify({"ok": False, "error": "Target is not currently connected."}), 404
    return jsonify(target)


@app.post("/api/scan/start")
def start_scan():
    data = request.get_json(silent=True) or {}
    target_id = str(data.get("target_id", "")).strip()
    if not target_id:
        return jsonify({"ok": False, "error": "target_id is required"}), 400
    if len(target_id) > 256:
        return jsonify({"ok": False, "error": "target_id is too long"}), 400

    target = next((t for t in hardware_reader.detect_connected_targets() if t.get("id") == target_id), None)
    if target is None:
        return jsonify({"ok": False, "error": "Target is not currently connected."}), 409
    try:
        scan = stm32_engine.start(target)
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    return jsonify({"ok": True, "scan_id": scan["scan_id"], "scan": scan}), 202


@app.get("/api/scan/<scan_id>")
def get_scan(scan_id: str):
    scan = stm32_engine.get(scan_id)
    if scan is None:
        return jsonify({"ok": False, "error": "Scan not found"}), 404
    return jsonify({"ok": True, "scan": scan})


@app.get("/api/history")
def get_history():
    try:
        limit = int(request.args.get("limit", 20))
    except ValueError:
        limit = 20
    return jsonify(storage.get_history(limit))


@app.get("/api/logs")
def get_logs():
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50
    return jsonify(storage.get_logs(limit))


if __name__ == "__main__":
    app.run(host=config.server.host, port=config.server.port, debug=False)
