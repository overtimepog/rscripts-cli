"""Script hunting: fingerprint obfuscators and follow loadstring/HttpGet loader chains.

Used by `rs hunt`. Fetches go through the same rscripts/scriptblox API clients
as the rest of the CLI; remote loader payloads are fetched with a plain session.
"""
import hashlib
import os
import re

import requests

UA = {"User-Agent": "rscripts-cli/0.3.0"}
MAX_PAYLOAD_BYTES = 5_000_000
MAX_DEPTH = 3
MAX_URLS_PER_FILE = 5

# --- obfuscator fingerprints -------------------------------------------------
# Luraph header validated against known v14.7/v14.8 samples; structural markers
# (power2 table + Luau proto bytes 0x1B4C7561 0x50) validated against same.
LURAPH_HEADER = re.compile(
    r'This file was (?:protected|obfuscated) using Luraph Obfuscator (v[\d.]+)')
LURAPH_STRUCT = [
    re.compile(r'\[0\]\s*=\s*1,2,4,8,16,32'),
    re.compile(r'0x1B,0x4C,0x75,0x61,0x50'),
]
SIMPLE_MARKERS = [
    ("MoonSec", re.compile(r'Moon ?Sec', re.I)),
    ("IronBrew", re.compile(r'Iron ?Brew', re.I)),
    ("Synapse Xen", re.compile(r'Synapse Xen', re.I)),
    ("WeAreDevs", re.compile(r'wearedevs\.net/obfuscator', re.I)),
    ("LuaObfuscator.com", re.compile(r'luaobfuscator\.com', re.I)),
]
ESCAPE_DENSE = re.compile(r'\\x[0-9a-f]{2}|\\[0-7]{3}')

LOADER_URL = re.compile(
    r'''(?:HttpGet|HttpGetAsync)\s*\(?\s*['"]([^'"]+)['"]''')


def fingerprint(code: str) -> tuple[str | None, str | None]:
    """Return (obfuscator_name, version_or_None). Name None = not obfuscated."""
    m = LURAPH_HEADER.search(code)
    if m:
        return "Luraph", m.group(1)
    if all(rx.search(code) for rx in LURAPH_STRUCT):
        # structural match only (header stripped) — honest tentativeness
        return "Luraph?", None
    for name, rx in SIMPLE_MARKERS:
        if rx.search(code):
            return name, None
    # generic: dense one-liner full of hex/octal escapes = obfuscated, unknown by
    # ponytail: crude heuristic; swap in overhub-deobfuscator detector if needed
    head = code[:4000]
    if len(code) > 4000 and code.count("\n") < 40 and len(ESCAPE_DENSE.findall(head)) > 20:
        return "obfuscated(unknown)", None
    return None, None


def is_obfuscated(name: str | None) -> bool:
    return name is not None


def extract_urls(code: str) -> list[str]:
    return list(dict.fromkeys(LOADER_URL.findall(code)))[:MAX_URLS_PER_FILE]


def http_get(url: str) -> str:
    resp = requests.get(url, headers=UA, timeout=20)
    resp.raise_for_status()
    return resp.text


def _slug(text: str, cap: int = 40) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', text)[:cap].strip('_') or "script"


class HuntReport:
    """Accumulates results; one row per saved file."""

    def __init__(self):
        self.rows: list[dict] = []
        self.fetched = 0
        self.errors = 0
        self._seen_sha: set[str] = set()

    def save(self, out_dir: str, code: str, obf: str | None, ver: str | None,
             provenance: str, title: str = "") -> str | None:
        sha = hashlib.sha1(code.encode("utf-8", errors="replace")).hexdigest()[:10]
        if sha in self._seen_sha:
            return None
        self._seen_sha.add(sha)
        tag = f"{_slug(obf or 'plain')}" + (f"_{_slug(ver, 12)}" if ver else "")
        path = os.path.join(out_dir, f"{tag}_{sha}.lua")
        header = (f"-- [rs hunt] {obf or 'plain'}{(' ' + ver) if ver else ''}"
                  f" | {title[:70]} | {provenance}\n")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(header + code)
        self.rows.append({
            "obf": obf, "ver": ver, "title": title,
            "provenance": provenance, "path": path,
            "size": len(code),
        })
        return path


def _iter_scripts(source: str, queries: list[str], pages: int, order_by: str):
    """Yield (sid, title) for each listed script, browsing or searching."""
    if source == "scriptblox":
        from . import scriptblox
        for page in range(1, pages + 1):
            for q in (queries or [None]):
                try:
                    data = scriptblox.search_scripts(q=q, page=page)
                except Exception:
                    continue
                for s in data.get("result", {}).get("scripts", []):
                    yield s.get("_id", ""), s.get("title", "")
    else:
        from . import api
        for page in range(1, pages + 1):
            for q in (queries or [None]):
                try:
                    data = api.get_scripts(page=page, q=q, order_by=order_by, sort="desc")
                except Exception:
                    continue
                for s in data.get("scripts", []):
                    yield s.get("_id", ""), s.get("title", "")


def _get_raw_code(source: str, sid: str) -> str | None:
    """Entry script's raw Lua (inline for scriptblox, raw URL for rscripts)."""
    try:
        if source == "scriptblox":
            from . import scriptblox
            data = scriptblox.get_script(sid)
            script = data.get("script")
            if isinstance(script, list):
                script = script[0] if script else None
            return (script or {}).get("script") or None
        from . import api
        data = api.get_script(sid)
        script = data.get("script")
        if isinstance(script, list):
            script = script[0] if script else None
        raw_url = (script or {}).get("rawScript")
        return api.fetch_raw_script(raw_url) if raw_url else None
    except Exception:
        return None


def _process_code(code: str, source: str, sid: str, title: str, out_dir: str,
                  report: HuntReport, obf_filter: str | None,
                  provenance: str, depth: int, log) -> None:
    obf, ver = fingerprint(code)
    label = f"{obf} {ver}" if obf and ver else (obf or "plain")
    matched = obf is not None and (obf_filter is None or obf_filter.lower() in obf.lower())
    if matched:
        path = report.save(out_dir, code, obf, ver, provenance, title)
        if path:
            log(f"  [{label}] {title[:50] or sid} ({len(code):,}b) -> {os.path.basename(path)}")
    elif obf is not None:
        log(f"  ({label}) {title[:50] or sid} — not matching filter, following loaders")
    for url in extract_urls(code) if depth < MAX_DEPTH else []:
        try:
            payload = http_get(url)
        except Exception as e:
            log(f"  url fail {url}: {e}")
            report.errors += 1
            continue
        if len(payload) > MAX_PAYLOAD_BYTES:
            continue
        report.fetched += 1
        _process_code(payload, source, sid, title, out_dir, report, obf_filter,
                      f"url={url} via {source} id={sid}", depth + 1, log)


def hunt(sources: list[str], queries: list[str], pages: int, out_dir: str,
         obf_filter: str | None = None, order_by: str = "views", log=print) -> HuntReport:
    """Hunt scripts across sources; save obfuscated hits (+ loader payloads)."""
    os.makedirs(out_dir, exist_ok=True)
    report = HuntReport()
    seen_ids: set[tuple[str, str]] = set()
    for source in sources:
        for sid, title in _iter_scripts(source, queries, pages, order_by):
            if not sid or (source, sid) in seen_ids:
                continue
            seen_ids.add((source, sid))
            code = _get_raw_code(source, sid)
            if not code:
                continue
            _process_code(code, source, sid, title, out_dir, report, obf_filter,
                          f"{source} id={sid}", 0, log)
    return report


if __name__ == "__main__":
    # self-check: fingerprint + URL extraction on synthetic samples
    luraph = ("-- This file was protected using Luraph Obfuscator v14.8 "
              "[https://lura.ph/]\nreturn(function()local t={[0]=1,2,4,8,16,32}")
    name, ver = fingerprint(luraph)
    assert (name, ver) == ("Luraph", "v14.8"), (name, ver)
    structural = "local t={[0]=1,2,4,8,16,32} local p={0x1B,0x4C,0x75,0x61,0x50}"
    assert fingerprint(structural) == ("Luraph?", None)
    assert fingerprint("print('hello')") == (None, None)
    urls = extract_urls('loadstring(game:HttpGet("https://x.test/a.lua"))()')
    assert urls == ["https://x.test/a.lua"], urls
    print("hunter self-check OK")
