#!/usr/bin/env python3
import argparse
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, unquote


import requests
from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
CRO_HOST_RE = re.compile(r"(^|\.)croaod\.cz$", re.I)
MPD_RE = re.compile(r"\.mpd(\?|$)", re.I)
MP3_RE = re.compile(r"\.mp3(\?|$)", re.I)

HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "cs,en-US;q=0.7,en;q=0.3",
    "Origin": "https://www.mujrozhlas.cz",
    "Referer": "https://www.mujrozhlas.cz/",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

def filename_from_url(url: str) -> str:
    path = urlparse(url).path or ""
    seg = next((s for s in reversed(path.split("/")) if s), "mujrozhlas")
    seg = unquote(seg)

    if not seg:
        seg = "mujrozhlas"

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
                    speed = bytes_done / elapsed  # B/s
                    if total > 0:
                        pct = bytes_done / total * 100
                        remaining = max(total - bytes_done, 0)
                        eta = remaining / max(speed, 1e-6)
                        print(f"\r    {pct:6.2f}%  ({human(bytes_done)}/{human(total)})  "
                              f"{speed/1024/1024:.2f} MB/s  ETA {int(eta)}s", end="", flush=True)
                    else:
                        print(f"\r    {human(bytes_done)} downloaded  "
                              f"{speed/1024/1024:.2f} MB/s", end="", flush=True)
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

PLAY_SELECTORS = [
    "button[aria-label*='Přehrát']",
    "button[aria-label*='Přehrat']",
    "button[title*='Přehrát']",
    ".b-player__control--play",
    ".player__play",
    ".js-player-play",
    "button.play",
    "button[aria-label='Přehrát']",
]

def collect_streams_with_playwright(page_url: str, dwell_seconds: int = 6) -> list[str]:
    streams = []
    seen = set()

    def maybe_add(url: str):
        if not url or url in seen:
            return
        h = host_of(url) or ""
        if CRO_HOST_RE.search(h) and (MPD_RE.search(url) or MP3_RE.search(url)):
            seen.add(url)
            streams.append(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--lang=cs"])
        ctx = browser.new_context(
            user_agent=UA,
            locale="cs-CZ",
            extra_http_headers={"Accept-Language": "cs,en-US;q=0.7,en;q=0.3"},
        )
        page = ctx.new_page()

        # Observe requests
        page.on("request", lambda req: maybe_add(req.url))
        page.on("response", lambda resp: maybe_add(resp.url))

        
        page.goto("https://www.mujrozhlas.cz/", wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        page.goto(page_url, wait_until="domcontentloaded")

        # Try clicking visible play buttons
        for sel in PLAY_SELECTORS:
            try:
                for e in page.locator(sel).all():
                    try:
                        e.scroll_into_view_if_needed(timeout=1000)
                        e.click(timeout=800)
                        page.wait_for_timeout(800)
                    except Exception:
                        continue
            except Exception:
                continue

        # Give the player time to fetch manifests
        page.wait_for_timeout(dwell_seconds * 1000)

        # Scroll to bottom to trigger lazy players, click again
        last_h = page.evaluate("document.body.scrollHeight")
        while True:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            for sel in PLAY_SELECTORS:
                try:
                    for e in page.locator(sel).all():
                        try:
                            e.scroll_into_view_if_needed(timeout=1000)
                            e.click(timeout=800)
                            page.wait_for_timeout(600)
                        except Exception:
                            continue
                except Exception:
                    continue
            page.wait_for_timeout(800)
            new_h = page.evaluate("document.body.scrollHeight")
            if new_h == last_h:
                break
            last_h = new_h

        
        page.wait_for_timeout(1200)

        ctx.close()
        browser.close()

    
    return streams

def main():
    ap = argparse.ArgumentParser(
        description="Headless (Playwright) mujrozhlas stream sniffer → download/record → merge to single MP3."
    )
    ap.add_argument("url", help="mujrozhlas.cz page URL (episode or series)")
    ap.add_argument("-o", "--output", help="Final merged MP3 filename (default: mujrozhlas_merged.mp3)")
    ap.add_argument("--keep-parts", action="store_true", help="Keep per-part MP3 files")
    args = ap.parse_args()

    if not have_ffmpeg():
        die("ffmpeg not found in PATH. Please install ffmpeg.")

    print(f"Opening headless Chromium and sniffing streams: {args.url}")
    stream_urls = collect_streams_with_playwright(args.url)
    if not stream_urls:
        die("No croaod.cz .mpd/.mp3 streams detected. Try increasing dwell time, or I can tighten selectors.")

    print(f"Detected {len(stream_urls)} stream URL(s).")
    for i, u in enumerate(stream_urls[:6], start=1):
        print(f"  [{i}] {u}")

    tempdir = Path(tempfile.mkdtemp(prefix="mujrozhlas_parts_"))
    parts = []
    print(f"\nProcessing {len(stream_urls)} stream(s)…")
    for idx, u in enumerate(stream_urls, start=1):
        print(f"\n[{idx}/{len(stream_urls)}] {'MP3' if MP3_RE.search(u) else 'DASH'}")
        out_path = tempdir / f"{idx:02d} part.mp3"
        try:
            if MP3_RE.search(u):
                print(f"[{idx}] Downloading MP3…")
                download_mp3(u, out_path, referer=args.url)
            else:
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
