# -*- coding: utf-8 -*-
"""Safe supervisor entrypoint for Runflare.

- Never replaces itself with the web process (stays PID parent)
- Writes rotating logs + status JSON on persistent disk
- Starts Gunicorn as a child, restarts with backoff on crash
- If the app cannot start, keeps the container alive and serves a 503 status page
- Graceful shutdown on SIGTERM/SIGINT

Panel start command:  python safe_start.py
(or keep: python manage.py  — manage.py delegates here)
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _data_root() -> Path:
    env = os.environ.get("DATA_ROOT")
    if env:
        return Path(env)
    for c in ("/data", "/app/data"):
        if Path(c).is_dir():
            return Path(c)
    return Path("/app/data")


DATA = _data_root()
LOG_DIR = DATA / "logs"
STATUS_FILE = LOG_DIR / "status.json"
STARTED_AT = datetime.now(timezone.utc)
_log_fp = None
_stop = threading.Event()
_child = None
_lock = threading.Lock()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def log(msg: str, level: str = "INFO") -> None:
    global _log_fp
    line = f"{_ts()} [{level}] {msg}"
    print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if _log_fp is None:
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            path = LOG_DIR / f"supervisor-{day}.log"
            _log_fp = open(path, "a", encoding="utf-8")
        _log_fp.write(line + "\n")
        _log_fp.flush()
    except Exception as e:
        print(f"{_ts()} [WARN] log write failed: {e}", flush=True)


def write_status(payload: dict) -> None:
    payload = dict(payload)
    payload["updated_at"] = _ts()
    payload["supervisor_started_at"] = STARTED_AT.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    payload["data_root"] = str(DATA)
    payload["pid"] = os.getpid()
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATUS_FILE)
    except Exception as e:
        log(f"status write failed: {e}", "WARN")


def preflight() -> tuple:
    """Return (ok, detail). Never raises."""
    notes = []
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        test = LOG_DIR / ".write_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        notes.append(f"disk_ok={DATA}")
    except Exception as e:
        return False, f"disk not writable: {e}"

    try:
        import gunicorn  # noqa: F401
        notes.append("gunicorn=ok")
    except Exception as e:
        notes.append(f"gunicorn_missing={e}")

    try:
        import main as app_module  # noqa: F401
        if not hasattr(app_module, "app"):
            return False, "main.app not found"
        notes.append("import_main=ok")
    except Exception as e:
        return False, f"import main failed: {e}\n{traceback.format_exc()}"

    return True, "; ".join(notes)


def gunicorn_cmd() -> list:
    conf = ROOT / "gunicorn.conf.py"
    port = os.environ.get("PORT", "8000")
    if conf.is_file():
        return ["gunicorn", "--config", str(conf), "main:app"]
    return [
        "gunicorn",
        "-b", f"0.0.0.0:{port}",
        "-w", "1",
        "-k", "gthread",
        "--threads", os.environ.get("GUNICORN_THREADS", "4"),
        "--timeout", os.environ.get("GUNICORN_TIMEOUT", "60"),
        "main:app",
    ]


def start_child():
    cmd = gunicorn_cmd()
    log("starting child: " + " ".join(cmd))
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=os.environ.copy(),
        stdout=None,
        stderr=None,
    )


class _StatusHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log("fallback-http: " + (fmt % args), "DEBUG")

    def do_GET(self):
        body = {
            "ok": False,
            "mode": "supervisor_fallback",
            "message": "وب‌سایت موقتاً در دسترس نیست؛ سوپروایزر در حال تلاش مجدد است.",
            "status_file": str(STATUS_FILE),
        }
        try:
            if STATUS_FILE.is_file():
                body["last_status"] = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(503)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_fallback_until(port: int, stop_event: threading.Event, max_seconds: float) -> None:
    server = None
    try:
        server = HTTPServer(("0.0.0.0", port), _StatusHandler)
        server.timeout = 1.0
        log(f"fallback HTTP on :{port} for up to {max_seconds:.0f}s", "WARN")
        end = time.time() + max_seconds
        while not stop_event.is_set() and time.time() < end:
            server.handle_request()
    except OSError as e:
        log(f"fallback bind failed: {e}", "WARN")
    finally:
        if server is not None:
            try:
                server.server_close()
            except Exception:
                pass


def _handle_signal(signum, frame):
    log(f"signal {signum} received — shutting down")
    _stop.set()
    with _lock:
        p = _child
    if p and p.poll() is None:
        try:
            p.send_signal(signal.SIGTERM)
        except Exception:
            pass


def main() -> int:
    global _child
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log("==== safe_start supervisor boot ====")
    log(f"cwd={ROOT} data={DATA} port={os.environ.get('PORT', '8000')}")
    write_status({"state": "booting", "ok": False})

    ok, detail = preflight()
    log(f"preflight: ok={ok} ({detail})", "INFO" if ok else "ERROR")
    write_status({"state": "preflight", "ok": ok, "detail": detail[:2000]})

    if not ok:
        delay = 5
        while not _stop.is_set():
            write_status({"state": "preflight_failed", "ok": False, "detail": detail[:2000], "retry_in": delay})
            port = int(os.environ.get("PORT", "8000"))
            run_fallback_until(port, _stop, max_seconds=min(delay, 30))
            time.sleep(max(0, delay - 30) if delay > 30 else 0)
            ok, detail = preflight()
            log(f"preflight retry: ok={ok} ({detail})", "INFO" if ok else "ERROR")
            if ok:
                break
            delay = min(delay * 2, 120)

    failures = 0
    while not _stop.is_set():
        try:
            with _lock:
                _child = start_child()
                child = _child
            write_status({
                "state": "running",
                "ok": True,
                "child_pid": child.pid,
                "failures": failures,
            })
            log(f"child pid={child.pid}")

            while not _stop.is_set():
                rc = child.poll()
                if rc is not None:
                    log(f"child exited code={rc}", "ERROR")
                    break
                write_status({
                    "state": "running",
                    "ok": True,
                    "child_pid": child.pid,
                    "failures": failures,
                })
                _stop.wait(30)

            if _stop.is_set():
                if child.poll() is None:
                    log("terminating child…")
                    child.send_signal(signal.SIGTERM)
                    try:
                        child.wait(timeout=25)
                    except subprocess.TimeoutExpired:
                        log("child kill", "WARN")
                        child.kill()
                break

            failures += 1
            delay = min(2 ** min(failures, 6), 60)
            write_status({
                "state": "restarting",
                "ok": False,
                "failures": failures,
                "exit_code": child.returncode,
                "backoff_sec": delay,
            })
            log(f"restart in {delay}s (failure #{failures})")
            port = int(os.environ.get("PORT", "8000"))
            run_fallback_until(port, _stop, max_seconds=min(delay, 15))
            _stop.wait(max(0, delay - 15) if delay > 15 else 0)

        except Exception as e:
            failures += 1
            log(f"supervisor loop error: {e}\n{traceback.format_exc()}", "ERROR")
            write_status({"state": "supervisor_error", "ok": False, "error": str(e), "failures": failures})
            _stop.wait(5)

    write_status({"state": "stopped", "ok": False})
    log("supervisor exit")
    if _log_fp:
        try:
            _log_fp.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
