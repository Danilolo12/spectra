#!/usr/bin/env python3
"""Crea la GitHub App spectra-reviewer por el flujo de manifiesto.

Abre el navegador, captura el código de GitHub y guarda las credenciales
en ~/.config/spectra/github-app/ (nunca en el repo).
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = 8765
APP_NAME = "spectra-reviewer"
HOMEPAGE = "https://github.com/Danilolo12/spectra"
CRED_DIR = Path.home() / ".config" / "spectra" / "github-app"
STATE = secrets.token_urlsafe(16)

MANIFEST = {
    "name": APP_NAME,
    "url": HOMEPAGE,
    "description": (
        "Revisor de pull requests de SPECTRA. Comenta hallazgos y aprueba "
        "cuando el CI está en verde. Identidad propia, distinta a la del autor."
    ),
    "public": False,
    "redirect_url": f"http://127.0.0.1:{PORT}/callback",
    "hook_attributes": {"url": "https://example.com/github/events", "active": False},
    "default_permissions": {
        "contents": "write",
        "metadata": "read",
        "pull_requests": "write",
        "checks": "read",
        "issues": "read",
        "statuses": "read",
    },
    "default_events": [
        "pull_request",
        "pull_request_review",
        "check_run",
        "check_suite",
    ],
}

FORM_HTML = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Crear {APP_NAME}</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui; max-width: 40rem; margin: 4rem auto; color: #111; }}
    button {{ font-size: 1.1rem; padding: .7rem 1.2rem; background: #1f6feb; color: #fff; border: 0; border-radius: 8px; cursor: pointer; }}
    p {{ line-height: 1.5; color: #333; }}
  </style>
</head>
<body>
  <h1>Crear el compañero {APP_NAME}</h1>
  <p>GitHub va a pedir que confirmes la app. Permisos: leer código, comentar y aprobar PRs. Webhook apagado. La app queda privada, solo se instala en tus repos.</p>
  <form action="https://github.com/settings/apps/new" method="post">
    <input type="hidden" name="manifest" value='{json.dumps(MANIFEST)}'>
    <input type="hidden" name="state" value="{STATE}">
    <button type="submit">Crear GitHub App</button>
  </form>
  <script>document.forms[0].submit()</script>
</body>
</html>
"""

DONE_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Listo</title></head>
<body style="font-family:ui-sans-serif,system-ui;max-width:40rem;margin:4rem auto">
  <h1>App creada</h1>
  <p>Vuelve a la terminal. El siguiente paso es instalarla en el repo spectra; se abre sola en el navegador.</p>
</body></html>
"""

ERROR_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Error</title></head>
<body style="font-family:ui-sans-serif,system-ui;max-width:40rem;margin:4rem auto">
  <h1>No se pudo crear</h1>
  <p>{msg}</p>
</body></html>
"""

result: dict = {"status": "waiting"}


def convert_code(code: str) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/app-manifests/{code}/conversions",
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "spectra-setup",
        },
        data=b"",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def save_credentials(payload: dict) -> None:
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CRED_DIR, 0o700)
    (CRED_DIR / "app-id").write_text(str(payload["id"]) + "\n")
    (CRED_DIR / "slug").write_text(payload["slug"] + "\n")
    (CRED_DIR / "client-id").write_text(payload["client_id"] + "\n")
    (CRED_DIR / "private-key.pem").write_text(payload["pem"])
    os.chmod(CRED_DIR / "private-key.pem", 0o600)
    if payload.get("webhook_secret"):
        (CRED_DIR / "webhook-secret").write_text(payload["webhook_secret"] + "\n")
        os.chmod(CRED_DIR / "webhook-secret", 0o600)
    meta = {
        "id": payload["id"],
        "slug": payload["slug"],
        "html_url": payload.get("html_url"),
        "owner": payload.get("owner", {}).get("login"),
    }
    (CRED_DIR / "app.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Credenciales guardadas en {CRED_DIR}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _html(self, code: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/create"):
            self._html(200, FORM_HTML)
            return
        if parsed.path != "/callback":
            self._html(404, ERROR_HTML.format(msg="Ruta desconocida."))
            return
        qs = parse_qs(parsed.query)
        if qs.get("error"):
            msg = qs.get("error_description", qs["error"])[0]
            result["status"] = "error"
            result["error"] = msg
            self._html(400, ERROR_HTML.format(msg=msg))
            return
        code = (qs.get("code") or [None])[0]
        if not code:
            result["status"] = "error"
            result["error"] = "GitHub no devolvió un código."
            self._html(400, ERROR_HTML.format(msg=result["error"]))
            return
        try:
            payload = convert_code(code)
            save_credentials(payload)
            result["status"] = "ok"
            result["payload"] = {
                "id": payload["id"],
                "slug": payload["slug"],
                "html_url": payload.get("html_url"),
            }
            self._html(200, DONE_HTML)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            result["status"] = "error"
            result["error"] = f"GitHub {exc.code}: {body}"
            self._html(500, ERROR_HTML.format(msg=result["error"]))
        except Exception as exc:  # noqa: BLE001
            result["status"] = "error"
            result["error"] = str(exc)
            self._html(500, ERROR_HTML.format(msg=result["error"]))


def main() -> int:
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/create"
    print(f"Abre {url} si el navegador no arranca solo.", flush=True)
    print("En GitHub: revisa el nombre y dale a Create GitHub App.", flush=True)
    webbrowser.open(url)
    while result["status"] == "waiting":
        server.handle_request()
    if result["status"] != "ok":
        print("ERROR:", result.get("error"), file=sys.stderr)
        return 1
    slug = result["payload"]["slug"]
    install = f"https://github.com/apps/{slug}/installations/new"
    print(f"App id: {result['payload']['id']}", flush=True)
    print(f"Slug: {slug}", flush=True)
    print("Instálala solo en el repo spectra:", install, flush=True)
    webbrowser.open(install)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
