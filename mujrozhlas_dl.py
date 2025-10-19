#!/usr/bin/env python3
import argparse
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, urlsplit, urlunsplit, unquote

import requests
from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
CRO_HOST_RE = re.compile(r"(^|\.)croaod\.cz$", re.I)
MPD_RE = re.compile(r"\.mpd(\?|$)", re.I)
MP3_RE = re.compile(r"\.mp3(\?|$)", re.I)
M4S_RE = re.compile(r"\.m4s(\?|$)", re.I)

HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "cs,en-US;q=0.7,en;q=0.3",
    "Origin": "https://www.mujrozhlas.cz",
    "Referer": "https://www.mujrozhlas.cz/",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

COOKIE_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    "button[aria-label*='Přijmout']",
    "button:has-text('Přijmout vše')",
    "button:has-text('Souhlasím')",
    "button:has-text('Rozumím')",
    "button:has-text('Accept all')",
    "button:has-text('I agree')",
]

PLAY_SELECTORS = [
    "button[aria-label*='Přehrát']",
    "button[aria-label*='Přehrat']",
    "button[title*='Přehrát']",
    ".b-player__control--play",
    ".player__play",
    ".js-player-play",
    "button.play",
    "button[aria-label='Přehrát']",
    ".mr-player__play",
    "button[aria-label*='Play']",
    "button[title*='Play']",
]

def segment_to_manifest_url(seg_url: str) -> str | None:
    """
    Convert croaod.cz segment ..._mpd.m4s URL to its manifest.mpd.
    Example:
      https://.../segment_ctaudio_..._mpd.m4s -> https://.../manifest.mpd
    """
    sp = urlsplit(seg_url)
    parts = (sp.path or "").rsplit("/", 1)
    if len(parts) == 2 and parts[1].endswith("_mpd.m4s"):
        manifest_path = parts[0] + "/manifest.mpd"
        return urlunsplit((sp.scheme, sp.netloc, manifest_path, sp.query, sp.fragment))
    return None

def filename_from_url(url: str) -> str:
    path = urlparse(url).path or ""
    seg = next((s for s in reversed(path.split("/")) if s), "mujrozhlas")
    seg = unquote(seg) or "mujrozhlas"
    return f"{seg}.mp3"

def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None

def die(msg: str, code: int = 2):
    print(f"Error: {msg}")
    raise SystemExit(code)

def record_dash_to_mp3(mpd_url: str, out_path: Path, referer: str):
    ffmpeg_headers = (
        "Origin: https://www.mujrozhlas.cz\r\n"
        f"Referer: {referer}\r\n"
        "Accept: */*\r\n"
        "Accept-Language: cs,en-US;q=0.7,en;q=0.3\r\n"
        "Pragma: no-cache\r\n"
        "Cache-Control: no-cache\r\n"
    )
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-user_agent", UA,
        "-headers", ffmpeg_headers,
        "-i", mpd_url,
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        "-y",
        str(out_path),
    ]
    spinner = "|/-\\"
    i = 0
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while True:
            ret = proc.poll()
            elapsed = int(time.time() - start)
            print(f"\r    Recording… {spinner[i % len(spinner)]}  Elapsed: {elapsed}s", end="", flush=True)
            if ret is not None:
                break
            time.sleep(0.15)
            i += 1
    finally:
        print()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)

def download_mp3(url: str, out_path: Path, referer: str):
    headers = dict(HEADERS)
    headers["Referer"] = referer
    start = time.time()
    last_print = 0.0
    bytes_done = 0
    human = lambda b: f"{b/1024/1024:.2f} MB"
    with requests.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                bytes_done += len(chunk)
                now = time.time()
                if now - last_print >= 0.1:
                    elapsed = max(now - start, 1e-6)
                    speed = bytes_done / elapsed
                    if total > 0:
                        pct = bytes_done / total * 100
                        remaining = max(total - bytes_done, 0)
                        eta = remaining / max(speed, 1e-6)
                        print(
                            f"\r    {pct:6.2f}%  ({human(bytes_done)}/{human(total)})  "
                            f"{speed/1024/1024:.2f} MB/s  ETA {int(eta)}s",
                            end="", flush=True
                        )
                    else:
                        print(
                            f"\r    {human(bytes_done)} downloaded  "
                            f"{speed/1024/1024:.2f} MB/s",
                            end="", flush=True
                        )
                    last_print = now
    print()

def concat_mp3(parts, output_file: Path):
    with tempfile.TemporaryDirectory() as td:
        list_file = Path(td) / "list.txt"
        with open(list_file, "w", encoding="utf-8") as lf:
            for p in parts:
                lf.write(f"file '{Path(p).as_posix()}'\n")
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-nostdin",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            "-y",
            str(output_file),
        ]
        subprocess.run(cmd, check=True)

def host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""

def collect_streams_with_playwright(page_url: str, dwell_seconds: int = 10) -> list[str]:
    """
    Attempts to auto-discover croaod.cz .mpd/.mp3 (or .m4s -> infer .mpd) from a mujrozhlas.cz page.
    May fail if anti-bot protection is triggered.
    """
    streams = []
    seen = set()
    manifest_candidates = set()

    def maybe_add(url: str):
        if not url or url in seen:
            return
        h = host_of(url) or ""
        if CRO_HOST_RE.search(h) and (MPD_RE.search(url) or MP3_RE.search(url) or M4S_RE.search(url)):
            if M4S_RE.search(url):
                mpd_guess = segment_to_manifest_url(url)
                if mpd_guess:
                    manifest_candidates.add(mpd_guess)
            seen.add(url)
            streams.append(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--lang=cs", "--autoplay-policy=no-user-gesture-required"]
        )
        ctx = browser.new_context(
            user_agent=UA,
            locale="cs-CZ",
            extra_http_headers={"Accept-Language": "cs,en-US;q=0.7,en;q=0.3"},
        )

        # Listen on CONTEXT to also catch service worker traffic
        ctx.on("request", lambda req: maybe_add(req.url))
        ctx.on("response", lambda resp: maybe_add(resp.url))

        page = ctx.new_page()
        page.goto("https://www.mujrozhlas.cz/", wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        page.goto(page_url, wait_until="domcontentloaded")

        # Try cookie/consent
        try:
            for sel in COOKIE_SELECTORS:
                try:
                    btns = page.locator(sel)
                    if btns.count() > 0:
                        btns.first.scroll_into_view_if_needed(timeout=1000)
                        btns.first.click(timeout=1500)
                        page.wait_for_timeout(600)
                except Exception:
                    continue
        except Exception:
            pass

        # Try clicking play buttons
        for sel in PLAY_SELECTORS:
            try:
                for e in page.locator(sel).all():
                    try:
                        e.scroll_into_view_if_needed(timeout=1000)
                        e.click(timeout=1200)
                        page.wait_for_timeout(900)
                    except Exception:
                        continue
            except Exception:
                continue

        # Wait & lazy players
        page.wait_for_timeout(dwell_seconds * 1000)
        last_h = page.evaluate("document.body.scrollHeight")
        while True:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)
            for sel in PLAY_SELECTORS:
                try:
                    for e in page.locator(sel).all():
                        try:
                            e.scroll_into_view_if_needed(timeout=1000)
                            e.click(timeout=1200)
                            page.wait_for_timeout(700)
                        except Exception:
                            continue
                except Exception:
                    continue
            new_h = page.evaluate("document.body.scrollHeight")
            if new_h == last_h:
                break
            last_h = new_h

        page.wait_for_timeout(1500)
        ctx.close()
        browser.close()

    # Prefer MPD/MP3; if missing and we saw segments, return inferred MPDs
    mpd_or_mp3 = [u for u in streams if MPD_RE.search(u) or MP3_RE.search(u)]
    if not mpd_or_mp3 and manifest_candidates:
        mpd_or_mp3 = list(manifest_candidates)
    return mpd_or_mp3

def resolve_input_url(user_url: str) -> list[str]:
    """
    Accepts either:
      - mujrozhlas.cz page URL -> try to sniff
      - croaod.cz .mpd URL -> use directly
      - croaod.cz .m4s segment URL -> infer .mpd
      - croaod.cz .mp3 URL -> use directly
    Returns a list of URLs to process.
    """
    host = host_of(user_url)
    if CRO_HOST_RE.search(host or ""):
        if M4S_RE.search(user_url):
            mpd = segment_to_manifest_url(user_url)
            return [mpd] if mpd else []
        return [user_url]  # .mpd or .mp3
    # Assume mujrozhlas.cz page; attempt to sniff
    return collect_streams_with_playwright(user_url)

def main():
    ap = argparse.ArgumentParser(
        description=(
            "mujrozhlas downloader:\n"
            " - Option 1: Provide a mujrozhlas.cz page URL (auto-detect streams; may fail if Cloudflare blocks).\n"
            " - Option 2: Provide a croaod.cz .mpd URL copied from your browser (after you pass any checks).\n"
            " - Option 3: Provide a croaod.cz .m4s segment URL; the script will infer manifest.mpd.\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument("url", help="mujrozhlas.cz page URL OR croaod.cz .mpd/.mp3/.m4s URL")
    ap.add_argument("-o", "--output", help="Final merged MP3 filename (default derived from URL)")
    ap.add_argument("--keep-parts", action="store_true", help="Keep per-part MP3 files")
    args = ap.parse_args()

    if not have_ffmpeg():
        die("ffmpeg not found in PATH. Please install ffmpeg from official sources and keep it next to this script or in PATH.")

    # Resolve what to process based on the URL kind
    print(f"Resolving input: {args.url}")
    stream_urls = resolve_input_url(args.url)

    if not stream_urls:
        die(
            "No croaod.cz .mpd/.mp3 (or inferable .m4s) detected.\n"
            "Tips:\n"
            "  - Open the page in your browser, pass any Cloudflare/cookie checks, start playback,\n"
            "    then copy the .mpd (or a .m4s segment URL) from DevTools → Network and use that as input.\n"
            "  - Or try another page URL.\n"
        )

    print(f"Detected {len(stream_urls)} stream URL(s).")
    for i, u in enumerate(stream_urls[:6], start=1):
        print(f"  [{i}] {u}")

    tempdir = Path(tempfile.mkdtemp(prefix="mujrozhlas_parts_"))
    parts = []
    print(f"\nProcessing {len(stream_urls)} stream(s)…")
    for idx, u in enumerate(stream_urls, start=1):
        kind = "MP3" if MP3_RE.search(u) else ("DASH" if MPD_RE.search(u) else ("SEGMENT" if M4S_RE.search(u) else "UNKNOWN"))
        print(f"\n[{idx}/{len(stream_urls)}] {kind}")
        out_path = tempdir / f"{idx:02d} part.mp3"
        try:
            if MP3_RE.search(u):
                print(f"[{idx}] Downloading MP3…")
                download_mp3(u, out_path, referer=args.url)
            else:
                # For .mpd or inferred from .m4s
                print(f"[{idx}] Recording DASH via ffmpeg…")
                record_dash_to_mp3(u, out_path, referer=args.url)
        except subprocess.CalledProcessError as e:
            print(f"  ffmpeg failed: {e}; skipping this URL.")
            continue
        except requests.HTTPError as e:
            print(f"  HTTP error: {e}; skipping this URL.")
            continue

        if out_path.exists() and out_path.stat().st_size > 1024:
            parts.append(out_path)
            print(f"  Saved: {out_path.name}")
        else:
            print("  Output missing/too small; skipping.")

    if not parts:
        die("No parts downloaded/recorded successfully.")

    final_name = args.output or filename_from_url(args.url)
    final_path = Path.cwd() / final_name

    print(f"\nMerging {len(parts)} part(s) into: {final_path.name}")
    concat_mp3(parts, final_path)
    print("Merge complete.")

    if not args.keep_parts:
        for p in parts:
            try:
                p.unlink()
            except Exception:
                pass
        try:
            tempdir.rmdir()
        except Exception:
            pass

    print(f"\nDone.\nOutput: {final_path.resolve()}")

if __name__ == "__main__":
    main()
