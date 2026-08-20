"""Local browser interface for the code review agent."""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import shlex
import tempfile
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from bug_fix_agent import AnalysisReport, analyze


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Code Debug Review Desk</title>
<style>
:root { --ink:#18232b; --muted:#64727a; --paper:#f5f1e8; --panel:#fffdf8; --line:#d9d2c5; --green:#1f7a59; --red:#a63d40; --amber:#a96b18; --blue:#255c7a; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:radial-gradient(circle at 90% 0%, #dce9df 0 18%, transparent 42%), linear-gradient(135deg,#f5f1e8,#e9eee8); font:15px/1.5 Georgia, 'Times New Roman', serif; }
.shell { width:min(1180px, calc(100% - 32px)); margin:0 auto; padding:38px 0 56px; }
.eyebrow { color:var(--green); font:700 12px/1.2 'Trebuchet MS', sans-serif; letter-spacing:2px; text-transform:uppercase; }
h1 { max-width:760px; margin:10px 0 8px; font-size:clamp(38px, 6vw, 72px); line-height:.96; font-weight:700; }
.intro { max-width:640px; margin:0 0 30px; color:var(--muted); font-size:18px; }
.workspace { display:grid; grid-template-columns:minmax(0,1.05fr) minmax(320px,.95fr); gap:20px; align-items:start; }
.panel { background:rgba(255,253,248,.9); border:1px solid var(--line); box-shadow:0 12px 30px rgba(24,35,43,.08); border-radius:6px; padding:22px; }
label, legend { display:block; margin-bottom:7px; font:700 12px/1.2 'Trebuchet MS', sans-serif; letter-spacing:.7px; text-transform:uppercase; }
textarea, input, select { width:100%; border:1px solid #bdb7ac; border-radius:4px; background:#fffefa; color:var(--ink); font:14px/1.5 'Cascadia Code', Consolas, monospace; }
textarea { min-height:430px; padding:15px; resize:vertical; }
input, select { padding:11px 12px; }
.controls { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:15px 0; }
.file-row { display:flex; align-items:center; gap:12px; margin:12px 0 0; color:var(--muted); font:13px 'Trebuchet MS', sans-serif; }
.file-row input { padding:7px; font:13px 'Trebuchet MS', sans-serif; }
.actions { display:flex; align-items:center; gap:14px; margin-top:16px; }
button { border:0; border-radius:4px; padding:12px 18px; color:#fff; background:var(--green); cursor:pointer; font:700 14px 'Trebuchet MS', sans-serif; }
button:hover { background:#175e43; }
.hint { color:var(--muted); font:12px 'Trebuchet MS', sans-serif; }
.results { min-height:530px; }
.empty { display:grid; place-items:center; min-height:480px; color:var(--muted); text-align:center; }
.empty strong { display:block; margin-bottom:6px; color:var(--ink); font-size:22px; }
.result-head { display:flex; justify-content:space-between; align-items:start; gap:12px; border-bottom:1px solid var(--line); padding-bottom:18px; margin-bottom:18px; }
.result-head h2 { margin:0; font-size:30px; line-height:1; }
.badge { border-radius:99px; padding:6px 10px; color:#fff; background:var(--red); font:700 11px 'Trebuchet MS', sans-serif; text-transform:uppercase; }
.badge.ready { background:var(--green); }
.badge.neutral { background:var(--blue); }
.stats { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:20px; }
.stat { border-top:3px solid var(--line); padding-top:8px; }
.stat b { display:block; font-size:26px; line-height:1; }
.stat span { color:var(--muted); font:11px 'Trebuchet MS', sans-serif; text-transform:uppercase; }
section { margin-top:20px; } section h3 { margin:0 0 9px; font-size:19px; }
.item { border-left:4px solid var(--amber); background:#fbf5e8; margin:8px 0; padding:10px 12px; }
.item.error { border-color:var(--red); background:#fbeeed; } .item.good { border-color:var(--green); background:#eaf5ee; }
.item b { display:block; font:700 12px 'Trebuchet MS', sans-serif; text-transform:uppercase; }
.item p { margin:3px 0 0; } .location { color:var(--muted); font:12px 'Cascadia Code', Consolas, monospace; }
pre { max-height:180px; overflow:auto; padding:12px; color:#eef4ef; background:#182b2b; border-radius:4px; white-space:pre-wrap; font:12px/1.45 'Cascadia Code', Consolas, monospace; }
@media (max-width:780px) { .shell { width:min(100% - 20px, 620px); padding-top:24px; } .workspace { grid-template-columns:1fr; } textarea { min-height:300px; } .results { min-height:0; } .empty { min-height:180px; } }
</style>
</head>
<body>
<main class="shell">
<div class="eyebrow">Local static analysis desk</div>
<h1>Make the code easier to trust.</h1>
<p class="intro">Drop in a source file and get a focused review: potential errors, refactor opportunities, and the parts that are already working well.</p>
<div class="workspace">
<form class="panel" method="post" action="/review">
<label for="code">Source code</label>
<textarea id="code" name="code" placeholder="Paste code here...">{code}</textarea>
<div class="file-row"><span>or load a file</span><input id="file" type="file" accept=".py,.sql,.java,text/*"></div>
<div class="controls">
<div><label for="filename">Filename</label><input id="filename" name="filename" value="{filename}" required></div>
<div><label for="language">Language</label><select id="language" name="language"><option value="python" {python_selected}>Python</option><option value="sql" {sql_selected}>SQL</option><option value="java" {java_selected}>Java</option></select></div>
</div>
<label for="test_command">Optional test command</label>
<input id="test_command" name="test_command" value="{test_command}" placeholder="pytest -q">
<div class="actions"><button type="submit">Run review</button><span class="hint">Analysis runs locally on this machine.</span></div>
</form>
<div class="panel results">{results}</div>
</div>
</main>
<script>
const file = document.querySelector('#file');
file.addEventListener('change', async () => {
  const chosen = file.files[0]; if (!chosen) return;
  document.querySelector('#code').value = await chosen.text();
  document.querySelector('#filename').value = chosen.name;
  const suffix = chosen.name.split('.').pop().toLowerCase();
  if (['py','sql','java'].includes(suffix)) document.querySelector('#language').value = suffix === 'py' ? 'python' : suffix;
});
</script>
</body>
</html>"""


def field(value: str) -> str:
    return html.escape(value, quote=True)


def result_items(report: AnalysisReport) -> str:
    errors = [item for item in report.findings if item.severity == "error" and not item.fixed]
    refactors = [item for item in report.findings if item.severity != "error" or item.fixed]
    strengths: list[str] = []
    if report.language == "python" and not report.import_errors:
        strengths.append("Python files import successfully.")
    if report.tests and all(item.passed for item in report.tests):
        strengths.append("The configured test command passed.")
    if report.applied_fixes:
        strengths.append(f"Applied {report.applied_fixes} explicitly safe fix(s).")
    if not report.findings:
        strengths.append("No rules were triggered by the current analyzer.")
    if not strengths:
        strengths.append("The review is complete; use the findings above as the next actions.")

    def item_markup(item, css=""):
        location = f"{item.file}:{item.line}" if item.line else item.file
        return f'<div class="item {css}"><b>{field(item.rule)} <span class="location">{field(location)}</span></b><p>{field(item.message)}</p></div>'

    blocks = [f'<div class="result-head"><div><div class="eyebrow">Review complete</div><h2>{len(report.files)} file(s)</h2></div><span class="badge {"ready" if report.production_ready else ""}">{"Ready" if report.production_ready else "Needs attention"}</span></div>']
    blocks.append(f'<div class="stats"><div class="stat"><b>{len(errors)}</b><span>Potential errors</span></div><div class="stat"><b>{len(refactors)}</b><span>Refactor ideas</span></div><div class="stat"><b>{len(strengths)}</b><span>Strengths</span></div></div>')
    blocks.append('<section><h3>Potential errors</h3>' + (''.join(item_markup(item, "error") for item in errors) or '<div class="item good"><p>No unresolved errors found.</p></div>') + '</section>')
    blocks.append('<section><h3>Refactor opportunities</h3>' + (''.join(item_markup(item) for item in refactors) or '<div class="item good"><p>No refactor suggestions from the current rules.</p></div>') + '</section>')
    blocks.append('<section><h3>What went well</h3>' + ''.join(f'<div class="item good"><p>{field(strength)}</p></div>' for strength in strengths) + '</section>')
    if report.import_errors:
        blocks.append('<section><h3>Import checks</h3><pre>' + field('\n'.join(report.import_errors)) + '</pre></section>')
    for test in report.tests:
        blocks.append(f'<section><h3>Test output: {"passed" if test.passed else "failed"}</h3><pre>{field(test.output or "No output")}</pre></section>')
    return ''.join(blocks)


def render(code: str = "", filename: str = "review.py", language: str = "python", test_command: str = "", results: str | None = None) -> bytes:
    if results is None:
        results = '<div class="empty"><div><strong>Your review will appear here.</strong>Submit a file to see the signal behind the code.</div></div>'
    values = {"code": field(code), "filename": field(filename), "test_command": field(test_command), "results": results}
    for option in ("python", "sql", "java"):
        values[f"{option}_selected"] = "selected" if language == option else ""
    page = PAGE
    for key, value in values.items():
        page = page.replace("{" + key + "}", value)
    return page.encode("utf-8")


def open_in_chrome(url: str) -> None:
    candidates = [
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    chrome = next((path for path in candidates if path and Path(path).is_file()), None)
    if chrome:
        subprocess.Popen([chrome, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open_new(url)


class ReviewHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(render())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        code = values.get("code", [""])[0]
        filename = Path(values.get("filename", ["review.py"])[0]).name or "review.py"
        language = values.get("language", ["python"])[0]
        command_text = values.get("test_command", [""])[0].strip()
        if not code.strip():
            results = '<div class="item error"><b>Missing source</b><p>Paste code or choose a file before running the review.</p></div>'
        else:
            try:
                with tempfile.TemporaryDirectory(prefix="code-review-") as directory:
                    target = Path(directory) / filename
                    target.write_text(code, encoding="utf-8")
                    command = shlex.split(command_text, posix=False) if command_text else []
                    report = analyze(str(target), language=language, test_command=command)
                    results = result_items(report)
            except (ValueError, OSError) as exc:
                results = f'<div class="item error"><b>Review could not run</b><p>{field(str(exc))}</p></div>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(render(code, filename, language, command_text, results))

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local Code Debug review web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="Do not open Chrome automatically")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ReviewHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Code Debug Review Desk: {url}")
    if not args.no_browser:
        open_in_chrome(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping review server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
