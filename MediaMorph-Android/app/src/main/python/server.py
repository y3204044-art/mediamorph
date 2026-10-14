#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MediaMorph Studio Pro – Flagship Backend Engine v3.0
מנוע סריקה רב-תהליכונית, טלמטריית FFmpeg שקופה בזמן אמת, מעבדת השוואה A/B (5 שניות),
האצת חומרה ב-GPU (VideoToolbox/NVENC), חיתוך שקט חכם, מאתר כפילויות (SHA-256) וממיר תמונות Lossless.
פותח על ידי | לפניות ושיפורים: y3204044@gmail.com
"""

import os
import sys
import json
import time
import shutil
import struct
import hashlib
import tempfile
import mimetypes
import platform
IS_ANDROID = "ANDROID_ROOT" in os.environ and "ANDROID_DATA" in os.environ
if IS_ANDROID:
    import android_shim
    subprocess = android_shim
else:
    import subprocess
import threading
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn


def find_binary(name):
    if IS_ANDROID:
        return name
    ext = ".exe" if platform.system() == "Windows" else ""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "bin", name + ext),
        os.path.join(base_dir, "..", "Resources", "bin", name + ext),
        shutil.which(name + ext),
        f"/usr/local/bin/{name}{ext}",
        f"/opt/homebrew/bin/{name}{ext}",
        f"/usr/bin/{name}{ext}",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.abspath(c)
    return name + ext


FFMPEG_BIN = find_binary("ffmpeg")
FFPROBE_BIN = find_binary("ffprobe")
CWEBP_BIN = find_binary("cwebp")
DWEBP_BIN = find_binary("dwebp")

AB_PREVIEW_DIR = os.path.join(tempfile.gettempdir(), "mediamorph_ab_lab")
os.makedirs(AB_PREVIEW_DIR, exist_ok=True)

AUDIO_EXTENSIONS = {
    '.mp3', '.wav', '.flac', '.aac', '.m4a', '.m4b', '.m4p', '.m4r',
    '.ogg', '.oga', '.opus', '.wma', '.aiff', '.aif', '.aifc', '.alac',
    '.ape', '.wv', '.tta', '.tak', '.ofr', '.ofs', '.ac3', '.eac3',
    '.dts', '.dtshd', '.thd', '.mlp', '.amr', '.awb', '.gsm', '.3ga',
    '.ra', '.ram', '.rm', '.mp2', '.mp1', '.spx', '.caf', '.au', '.snd',
    '.pcm', '.raw', '.w64', '.rf64', '.voc', '.vox', '.8svx', '.svx',
    '.paf', '.fap', '.iff', '.sf', '.sd2', '.pvf', '.xi', '.sds', '.avr',
    '.mka', '.weba', '.aa', '.aax', '.act', '.dss', '.dvf', '.mpc'
}

VIDEO_EXTENSIONS = {
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.f4v', '.f4p', '.f4a', '.f4b',
    '.webm', '.m4v', '.mpg', '.mpeg', '.mpe', '.mpv', '.m1v', '.m2v', '.mp2v',
    '.ts', '.mts', '.m2ts', '.m2t', '.tod', '.trp', '.tp', '.vob', '.evo',
    '.ogv', '.3gp', '.3g2', '.3gpp', '.3gp2', '.asf', '.rmvb',
    '.divx', '.xvid', '.dv', '.dif', '.mxf', '.gxf', '.roq', '.nsv', '.yuv',
    '.y4m', '.h264', '.264', '.h265', '.265', '.hevc', '.av1', '.ivf', '.vp8', '.vp9',
    '.prores', '.dnxhd', '.braw', '.r3d', '.crm', '.cin', '.dpx', '.exr',
    '.bik', '.smk', '.thp', '.wtv', '.dvr-ms', '.pva', '.nuv', '.fli', '.flc',
    '.flic', '.amv', '.svi', '.mjpeg', '.mjpg', '.gifv', '.swf'
}

IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.jpe', '.jfif', '.png', '.webp', '.avif', '.heic', '.heif',
    '.tiff', '.tif', '.bmp', '.dib', '.gif', '.ico', '.apng', '.tga', '.ppm', '.pgm', '.pbm'
}

ALL_MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS | IMAGE_EXTENSIONS

SYSTEM_SKIP_DIRS = {
    '$RECYCLE.BIN', 'System Volume Information', '.Trash', '.Trashes',
    '.Spotlight-V100', '.fseventsd', 'node_modules', '.git', '__pycache__',
    'proc', 'sys', 'dev', '.DocumentRevisions-V100', 'Library'
}

STATE = {
    "scan": {
        "running": False,
        "cancelled": False,
        "phase": "idle",
        "scanned_files": 0,
        "matched_files": 0,
        "total_to_probe": 0,
        "probed_count": 0,
        "current_file": "",
        "speed_files_sec": 0.0,
        "eta_sec": 0,
        "results": [],
    },
    "convert": {
        "running": False,
        "cancelled": False,
        "total_jobs": 0,
        "current_job_index": 0,
        "current_file": "",
        "current_file_progress": 0,
        "overall_progress": 0,
        "speed_mb_sec": 0.0,
        "eta_sec": 0,
        "started_at": 0,
        "processed_bytes": 0,
        "total_bytes": 0,
        "total_saved_bytes": 0,
        "total_saved_mb": 0.0,
        "telemetry": {
            "active": False,
            "command": "",
            "frame": 0,
            "fps": 0.0,
            "bitrate": "—",
            "writtenBytes": 0,
            "writtenMb": 0.0,
            "outTime": "00:00:00.00",
            "outTimeSec": 0.0,
            "totalDurationSec": 0.0,
            "totalDurationFormatted": "0:00",
            "speedFactor": "0.0x",
            "gpuActive": False,
            "encoderName": "—",
            "rawLines": []
        },
        "jobs": [],
        "history": [],
    },
    "analyze": {
        "running": False,
        "cancelled": False,
        "scanned_files": 0,
        "total_size_bytes": 0,
        "speed_files_sec": 0.0,
        "current_path": "",
        "result": None,
    },
    "duplicates": {
        "running": False,
        "cancelled": False,
        "scanned_files": 0,
        "hashed_files": 0,
        "wasted_mb": 0.0,
        "groups": [],
    }
}

CURRENT_PROC = None


def format_duration(seconds):
    if not seconds or seconds <= 0:
        return "0:00"
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def classify_resolution(width, height):
    if not width or not height:
        return "לא ידוע"
    max_dim = max(width, height)
    min_dim = min(width, height)
    if max_dim >= 15000:
        return "16K"
    if max_dim >= 11000:
        return "12K"
    if max_dim >= 7500:
        return "8K"
    if max_dim >= 5800:
        return "6K"
    if max_dim >= 5000:
        return "5K"
    if max_dim >= 3800 or min_dim >= 2100:
        return "4K (2160p)"
    if max_dim >= 2500 or min_dim >= 1400:
        return "2K / QHD (1440p)"
    if max_dim >= 1900 or min_dim >= 1000:
        return "Full HD (1080p)"
    if max_dim >= 1200 or min_dim >= 700:
        return "HD (720p)"
    if max_dim >= 800 or min_dim >= 460:
        return "SD (480p)"
    if max_dim >= 600 or min_dim >= 350:
        return "360p"
    if max_dim >= 400 or min_dim >= 230:
        return "240p"
    return "144p / נמוך"


def fast_image_dimensions(file_path):
    try:
        with open(file_path, "rb") as f:
            head = f.read(64)
            if len(head) < 24:
                return 0, 0
            if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
                w, h = struct.unpack(">LL", head[16:24])
                return int(w), int(h)
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return int(w), int(h)
            if head[:2] == b"BM":
                w, h = struct.unpack("<ii", head[18:26])
                return abs(int(w)), abs(int(h))
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        break
                    m = marker[1]
                    while m == 0xFF:
                        b = f.read(1)
                        if not b:
                            break
                        m = b[0]
                    if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.read(3)
                        h, w = struct.unpack(">HH", f.read(4))
                        return int(w), int(h)
                    elif m in (0xD8, 0xD9, 0x01) or (0xD0 <= m <= 0xD7):
                        continue
                    else:
                        seg_len = struct.unpack(">H", f.read(2))[0]
                        f.seek(seg_len - 2, 1)
    except Exception:
        pass
    return 0, 0


def probe_media_file(file_path):
    try:
        stat = os.stat(file_path)
    except OSError:
        return None

    size = stat.st_size
    ext = os.path.splitext(file_path)[1].lower()

    if ext in IMAGE_EXTENSIONS:
        w, h = fast_image_dimensions(file_path)
        if w == 0 or h == 0:
            try:
                proc = subprocess.run(
                    [FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_streams", file_path],
                    capture_output=True, text=True, timeout=6
                )
                data = json.loads(proc.stdout) if proc.stdout else {}
                st = (data.get("streams") or [{}])[0]
                w = int(st.get("width") or 0)
                h = int(st.get("height") or 0)
            except Exception:
                pass
        megapixels = round((w * h) / 1_000_000, 1) if (w and h) else 0
        res_label = f"{w}×{h}" + (f" ({megapixels}MP)" if megapixels >= 0.5 else "") if (w and h) else "תמונה"
        return {
            "path": file_path,
            "name": os.path.basename(file_path),
            "dir": os.path.dirname(file_path),
            "ext": ext,
            "type": "image",
            "size": size,
            "sizeMb": round(size / (1024 * 1024), 2),
            "sizeKb": round(size / 1024, 1),
            "duration": 0,
            "durationFormatted": "תמונה",
            "bitrate": 0,
            "bitrateKbps": 0,
            "codec": ext.replace(".", "").upper(),
            "audioCodec": "",
            "videoCodec": ext.replace(".", "").upper(),
            "sampleRate": 0,
            "channels": 0,
            "width": w,
            "height": h,
            "resolutionLabel": res_label,
            "fps": 0,
            "modifiedAt": int(stat.st_mtime * 1000),
        }

    is_video_ext = ext in VIDEO_EXTENSIONS
    cmd = [
        FFPROBE_BIN,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        data = json.loads(proc.stdout) if proc.stdout else {}
    except Exception:
        data = {}

    fmt = data.get("format", {})
    streams = data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    media_type = "video" if (video_stream and is_video_ext) else ("audio" if ext in AUDIO_EXTENSIONS else ("video" if video_stream else "audio"))

    duration = float(fmt.get("duration") or 0)
    if duration == 0 and audio_stream:
        duration = float(audio_stream.get("duration") or 0)
    if duration == 0 and video_stream:
        duration = float(video_stream.get("duration") or 0)

    total_bitrate = int(fmt.get("bit_rate") or 0)
    audio_bitrate = int(audio_stream.get("bit_rate") or 0) if audio_stream else 0

    if total_bitrate == 0 and duration > 0:
        total_bitrate = int((size * 8) / duration)

    effective_bitrate = audio_bitrate if (media_type == "audio" and audio_bitrate > 0) else total_bitrate
    bitrate_kbps = int(round(effective_bitrate / 1000)) if effective_bitrate else 0

    width = int(video_stream.get("width") or 0) if video_stream else 0
    height = int(video_stream.get("height") or 0) if video_stream else 0
    res_label = classify_resolution(width, height) if media_type == "video" else ""

    fps = 0.0
    if video_stream and video_stream.get("r_frame_rate"):
        parts = str(video_stream.get("r_frame_rate")).split("/")
        if len(parts) == 2 and float(parts[1]) != 0:
            fps = round(float(parts[0]) / float(parts[1]), 2)

    codec_name = (
        video_stream.get("codec_name") if media_type == "video" and video_stream
        else (audio_stream.get("codec_name") if audio_stream else ext.replace(".", ""))
    ) or ext.replace(".", "")

    sample_rate = int(audio_stream.get("sample_rate") or 0) if audio_stream else 0
    channels = int(audio_stream.get("channels") or 0) if audio_stream else 0

    return {
        "path": file_path,
        "name": os.path.basename(file_path),
        "dir": os.path.dirname(file_path),
        "ext": ext,
        "type": media_type,
        "size": size,
        "sizeMb": round(size / (1024 * 1024), 2),
        "sizeKb": round(size / 1024, 1),
        "duration": round(duration, 2),
        "durationFormatted": format_duration(duration),
        "bitrate": effective_bitrate,
        "bitrateKbps": bitrate_kbps,
        "codec": codec_name.upper(),
        "audioCodec": (audio_stream.get("codec_name") or "").upper() if audio_stream else "",
        "videoCodec": (video_stream.get("codec_name") or "").upper() if video_stream else "",
        "sampleRate": sample_rate,
        "channels": channels,
        "width": width,
        "height": height,
        "resolutionLabel": res_label,
        "fps": fps,
        "modifiedAt": int(stat.st_mtime * 1000),
    }


def list_mounted_volumes():
    if IS_ANDROID:
        return android_shim.volumes()
    volumes = []
    system = platform.system()
    if system == "Darwin":
        vol_root = "/Volumes"
        if os.path.isdir(vol_root):
            for name in os.listdir(vol_root):
                full = os.path.join(vol_root, name)
                if os.path.isdir(full):
                    try:
                        usage = shutil.disk_usage(full)
                        volumes.append({
                            "name": name,
                            "path": full,
                            "totalGb": round(usage.total / (1024**3), 1),
                            "usedGb": round(usage.used / (1024**3), 1),
                            "freeGb": round(usage.free / (1024**3), 1),
                            "usedPct": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
                        })
                    except Exception:
                        pass
        home = str(Path.home())
        volumes.append({
            "name": "תיקיית בית (Home)",
            "path": home,
            "totalGb": 0, "usedGb": 0, "freeGb": 0, "usedPct": 0
        })
    elif system == "Windows":
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                try:
                    usage = shutil.disk_usage(drive)
                    volumes.append({
                        "name": f"כונן ({letter}:)",
                        "path": drive,
                        "totalGb": round(usage.total / (1024**3), 1),
                        "usedGb": round(usage.used / (1024**3), 1),
                        "freeGb": round(usage.free / (1024**3), 1),
                        "usedPct": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
                    })
                except Exception:
                    pass
    else:
        usage = shutil.disk_usage("/")
        volumes.append({
            "name": "Root (/)",
            "path": "/",
            "totalGb": round(usage.total / (1024**3), 1),
            "usedGb": round(usage.used / (1024**3), 1),
            "freeGb": round(usage.free / (1024**3), 1),
            "usedPct": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
        })
    return volumes


def run_scan_worker(options):
    scan = STATE["scan"]
    scan["running"] = True
    scan["cancelled"] = False
    scan["phase"] = "walking"
    scan["scanned_files"] = 0
    scan["matched_files"] = 0
    scan["probed_count"] = 0
    scan["total_to_probe"] = 0
    scan["current_file"] = ""
    scan["speed_files_sec"] = 0.0
    scan["eta_sec"] = 0
    scan["results"] = []

    paths = options.get("paths") or []
    media_type = options.get("mediaType", "all")
    min_dur = options.get("minDurationSec")
    max_dur = options.get("maxDurationSec")
    min_br = options.get("minBitrateKbps")
    max_br = options.get("maxBitrateKbps")
    res_filter = options.get("resolutionFilter")

    if media_type == "audio":
        allowed_exts = AUDIO_EXTENSIONS
    elif media_type == "video":
        allowed_exts = VIDEO_EXTENSIONS
    elif media_type == "image":
        allowed_exts = IMAGE_EXTENSIONS
    else:
        allowed_exts = ALL_MEDIA_EXTENSIONS

    candidates = []
    for root_path in paths:
        if scan["cancelled"]:
            break
        if not os.path.exists(root_path):
            continue
        if os.path.isfile(root_path):
            candidates.append(root_path)
            continue
        for dirpath, dirnames, filenames in os.walk(root_path):
            if scan["cancelled"]:
                break
            dirnames[:] = [d for d in dirnames if d not in SYSTEM_SKIP_DIRS and not d.startswith("$") and not d.startswith(".")]
            for fname in filenames:
                if scan["cancelled"]:
                    break
                if fname.startswith("."):
                    continue
                scan["scanned_files"] += 1
                ext = os.path.splitext(fname)[1].lower()
                if ext in allowed_exts:
                    full_path = os.path.join(dirpath, fname)
                    candidates.append(full_path)
                    if len(candidates) % 25 == 0:
                        scan["current_file"] = full_path

    scan["phase"] = "probing"
    total_cands = len(candidates)
    scan["total_to_probe"] = total_cands
    results = []
    probe_start = time.time()
    lock = threading.Lock()

    def process_one(fpath):
        if scan["cancelled"]:
            return
        info = probe_media_file(fpath)
        with lock:
            scan["probed_count"] += 1
            scan["current_file"] = fpath
            elapsed = max(0.05, time.time() - probe_start)
            spd = scan["probed_count"] / elapsed
            scan["speed_files_sec"] = round(spd, 1)
            rem = max(0, total_cands - scan["probed_count"])
            scan["eta_sec"] = int(rem / spd) if spd > 0 else 0

            if not info:
                return
            if info["type"] != "image":
                if min_dur is not None and info["duration"] < float(min_dur):
                    return
                if max_dur is not None and info["duration"] > float(max_dur):
                    return
                if min_br is not None and info["bitrateKbps"] < int(min_br):
                    return
                if max_br is not None and info["bitrateKbps"] > int(max_br):
                    return
            if res_filter and info["type"] == "video":
                if info["resolutionLabel"] not in res_filter:
                    return
            results.append(info)
            scan["matched_files"] = len(results)

    with ThreadPoolExecutor(max_workers=8) as pool:
        pool.map(process_one, candidates)

    scan["results"] = results
    scan["phase"] = "done"
    scan["eta_sec"] = 0
    scan["running"] = False


def estimate_job_savings(file_info, settings):
    orig_bytes = file_info.get("size", 0)
    duration = file_info.get("duration", 0)
    mtype = file_info.get("type", "audio")

    if orig_bytes <= 0:
        return {"originalMb": 0.0, "estimatedMb": 0.0, "savedMb": 0.0, "savedPct": 0.0}

    if mtype == "image":
        img_format = settings.get("imageFormat", "webp")
        img_mode = settings.get("imageMode", "smart_near_lossless")
        img_scale = int(settings.get("imageScalePct") or 100)
        ext = file_info.get("ext", ".jpg").lower()

        scale_factor = (img_scale / 100.0) ** 2
        if img_format == "webp":
            base_ratio = 0.52 if img_mode == "lossless" else (0.28 if img_mode == "smart_near_lossless" else 0.18)
            if ext in (".jpg", ".jpeg") and img_mode == "lossless":
                base_ratio = 0.82
        elif img_format == "avif":
            base_ratio = 0.45 if img_mode == "lossless" else (0.22 if img_mode == "smart_near_lossless" else 0.14)
        elif img_format == "png":
            base_ratio = 0.72 if ext in (".bmp", ".tiff") else 0.85
        elif img_format == "jpg":
            base_ratio = 0.35 if ext in (".png", ".bmp", ".tiff") else (0.68 if img_mode == "smart_near_lossless" else 0.45)
        else:
            base_ratio = 0.65

        est_bytes = int(orig_bytes * base_ratio * scale_factor)

    elif mtype == "audio":
        target_codec = settings.get("audioCodec", "mp3")
        target_kbps = int(settings.get("audioBitrateKbps") or 192)
        orig_kbps = file_info.get("bitrateKbps") or 320
        silence_trim = settings.get("silenceTrim", False)

        if target_codec in ("flac", "alac"):
            est_kbps = 850
        elif target_codec in ("wav_16", "aiff"):
            est_kbps = 1411
        elif target_codec == "wav_24":
            est_kbps = 2116
        elif target_codec == "wav_32":
            est_kbps = 2822
        else:
            est_kbps = target_kbps

        eff_dur = duration * (0.88 if silence_trim else 1.0)
        if eff_dur > 0:
            est_bytes = int((est_kbps * 1000 / 8) * eff_dur * 1.02)
        else:
            ratio = est_kbps / max(orig_kbps, 1)
            est_bytes = int(orig_bytes * ratio * (0.88 if silence_trim else 1.0))
    else:
        orig_w = file_info.get("width") or 1920
        orig_h = file_info.get("height") or 1080
        target_w = int(settings.get("videoWidth") or orig_w)
        target_h = int(settings.get("videoHeight") or orig_h)
        vcodec = settings.get("videoCodec", "libx264")
        mode = settings.get("videoRateMode", "crf")
        crf = int(settings.get("videoCrf") if settings.get("videoCrf") is not None else 23)
        target_v_kbps = int(settings.get("videoBitrateKbps") or 2500)
        target_a_kbps = int(settings.get("videoAudioBitrateKbps") or 192)

        if mode in ("cbr", "vbr", "abr") and duration > 0:
            est_bytes = int(((target_v_kbps + target_a_kbps) * 1000 / 8) * duration)
        else:
            pixel_ratio = min(1.2, (target_w * target_h) / max(orig_w * orig_h, 1))
            codec_factor = 1.0
            if "265" in vcodec or "hevc" in vcodec:
                codec_factor = 0.55
            elif "av1" in vcodec or "svt" in vcodec:
                codec_factor = 0.45
            elif "vp9" in vcodec:
                codec_factor = 0.62
            elif "prores" in vcodec or "ffv1" in vcodec or "huffyuv" in vcodec:
                codec_factor = 3.2

            crf_factor = 2 ** ((23 - crf) / 6.0)
            est_bytes = int(orig_bytes * pixel_ratio * codec_factor * (1.0 / max(crf_factor, 0.15)))

    saved_bytes = orig_bytes - est_bytes
    saved_mb = round(saved_bytes / (1024 * 1024), 2)
    saved_pct = round((saved_bytes / orig_bytes) * 100, 1) if orig_bytes > 0 else 0
    return {
        "originalMb": round(orig_bytes / (1024 * 1024), 2),
        "estimatedMb": round(est_bytes / (1024 * 1024), 2),
        "savedMb": saved_mb,
        "savedPct": saved_pct,
    }


def resolve_gpu_encoder(vcodec, use_gpu):
    """מיפוי חכם להאצת חומרה ב-GPU (Apple VideoToolbox במק / NVENC בווינדוס)"""
    if not use_gpu or IS_ANDROID:
        return vcodec, False
    sys_name = platform.system()
    if sys_name == "Darwin":
        if vcodec in ("libx264", "h264"):
            return "h264_videotoolbox", True
        if vcodec in ("libx265", "hevc"):
            return "hevc_videotoolbox", True
        if vcodec == "prores":
            return "prores_videotoolbox", True
    elif sys_name == "Windows":
        if vcodec in ("libx264", "h264"):
            return "h264_nvenc", True
        if vcodec in ("libx265", "hevc"):
            return "hevc_nvenc", True
    return vcodec, False


def build_ffmpeg_command(file_info, settings, out_temp_path, sample_clip=None):
    """בניית פקודת FFmpeg חכמה לאודיו, וידאו ותמונות כולל GPU, חיתוך שקט ודגימת 5 שניות"""
    in_path = file_info["path"]
    mtype = file_info["type"]

    if mtype == "image":
        img_format = settings.get("imageFormat", "webp")
        if img_format == "keep":
            img_format = file_info.get("ext", ".webp").replace(".", "").lower()
        img_mode = settings.get("imageMode", "smart_near_lossless")
        img_quality = int(settings.get("imageQuality") or 92)
        img_scale = int(settings.get("imageScalePct") or 100)
        strip_exif = settings.get("imageStripMetadata", True)

        if img_format == "webp" and os.path.exists(CWEBP_BIN) and file_info.get("ext", "").lower() in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"):
            cmd = [CWEBP_BIN, "-quiet", "-mt"]
            if img_scale and img_scale != 100 and file_info.get("width") and file_info.get("height"):
                new_w = max(1, int(file_info["width"] * img_scale / 100))
                new_h = max(1, int(file_info["height"] * img_scale / 100))
                cmd += ["-resize", str(new_w), str(new_h)]
            if img_mode == "lossless":
                cmd += ["-lossless", "-z", "9"]
            elif img_mode == "smart_near_lossless":
                cmd += ["-near_lossless", "60", "-q", "92", "-m", "6", "-sharp_yuv"]
            else:
                cmd += ["-q", str(img_quality), "-m", "6", "-sharp_yuv"]
            if strip_exif:
                cmd += ["-metadata", "none"]
            else:
                cmd += ["-metadata", "all"]
            cmd += [in_path, "-o", out_temp_path]
            return cmd, "cwebp (Google WebP)", False

        cmd = [FFMPEG_BIN, "-y", "-hide_banner", "-i", in_path]
        vf = []
        if img_scale and img_scale != 100:
            vf.append(f"scale=trunc(iw*{img_scale}/200)*2:trunc(ih*{img_scale}/200)*2:flags=lanczos")
        if img_format == "avif":
            vf.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        if vf:
            cmd += ["-vf", ",".join(vf)]

        if img_format == "avif":
            cmd += ["-c:v", "libsvtav1", "-frames:v", "1"]
            crf_val = "12" if img_mode == "lossless" else ("20" if img_mode == "smart_near_lossless" else str(max(10, 63 - int(img_quality * 0.5))))
            cmd += ["-crf", crf_val]
        elif img_format == "webp" and IS_ANDROID:
            cmd += ["-c:v", "libwebp", "-lossless", "1" if img_mode == "lossless" else "0",
                    "-q:v", str(img_quality), "-compression_level", "6"]
        elif img_format in ("png", "webp"):
            cmd += ["-c:v", "png", "-compression_level", "9", "-pred", "mixed"]
        elif img_format in ("jpg", "jpeg"):
            qscale = "1" if img_mode == "lossless" else ("2" if img_mode == "smart_near_lossless" else str(max(2, int((100 - img_quality) / 3) + 2)))
            cmd += ["-c:v", "mjpeg", "-q:v", qscale, "-pix_fmt", "yuvj444p", "-strict", "-1"]

        if strip_exif:
            cmd += ["-map_metadata", "-1"]
        else:
            cmd += ["-map_metadata", "0"]

        cmd.append(out_temp_path)
        return cmd, f"ffmpeg ({img_format})", False

    cmd = [FFMPEG_BIN, "-y", "-hide_banner"]
    if sample_clip:
        start_sec, dur_sec = sample_clip
        cmd += ["-ss", str(start_sec), "-t", str(dur_sec)]
    cmd += ["-i", in_path, "-progress", "pipe:1", "-nostats"]

    if mtype == "audio":
        codec_id = settings.get("audioCodec", "mp3")
        kbps = int(settings.get("audioBitrateKbps") or 192)
        sr = settings.get("audioSampleRate")
        ch = settings.get("audioChannels")
        norm = settings.get("normalizeAudio", False)
        silence_trim = settings.get("silenceTrim", False)

        codec_map = {
            "mp3": ("libmp3lame", False),
            "aac": ("aac", False),
            "m4a": ("aac", False),
            "opus": ("libopus", False),
            "ogg": ("libvorbis", False),
            "wma": ("wmav2", False),
            "ac3": ("ac3", False),
            "eac3": ("eac3", False),
            "dts": ("dca", False),
            "mp2": ("mp2", False),
            "amr": ("libopencore_amrnb", False),
            "flac": ("flac", True),
            "alac": ("alac", True),
            "wav_16": ("pcm_s16le", True),
            "wav_24": ("pcm_s24le", True),
            "wav_32": ("pcm_f32le", True),
            "aiff": ("pcm_s16be", True),
        }
        ff_codec, is_lossless = codec_map.get(codec_id, ("libmp3lame", False))
        cmd += ["-vn", "-c:a", ff_codec]
        if ff_codec == "dca":
            cmd += ["-strict", "-2"]
        if not is_lossless:
            cmd += ["-b:a", f"{kbps}k"]
        if sr and str(sr) != "keep":
            cmd += ["-ar", str(sr)]
        if ch and str(ch) != "keep":
            cmd += ["-ac", str(ch)]

        af_filters = []
        if silence_trim:
            af_filters.append("silenceremove=start_periods=1:start_silence=0.4:start_threshold=-45dB:stop_periods=-1:stop_duration=0.9:stop_threshold=-45dB")
        if norm:
            af_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        if af_filters:
            cmd += ["-af", ",".join(af_filters)]

        cmd += ["-map_metadata", "0", out_temp_path]
        return cmd, ff_codec, False
    else:
        raw_vcodec = settings.get("videoCodec", "libx264")
        use_gpu = settings.get("hwAccel", True)
        vcodec, is_gpu = resolve_gpu_encoder(raw_vcodec, use_gpu)

        w = settings.get("videoWidth")
        h = settings.get("videoHeight")
        rate_mode = settings.get("videoRateMode", "crf")
        crf = int(settings.get("videoCrf") if settings.get("videoCrf") is not None else 23)
        v_kbps = int(settings.get("videoBitrateKbps") or 2500)
        preset = settings.get("videoPreset", "medium")
        fps = settings.get("videoFps")
        pix_fmt = settings.get("videoPixFmt", "yuv420p")
        acodec = settings.get("videoAudioCodec", "aac")
        a_kbps = settings.get("videoAudioBitrateKbps", 192)
        silence_trim = settings.get("silenceTrim", False)

        cmd += ["-c:v", vcodec]
        vf_filters = []
        if w and h and int(w) > 0 and int(h) > 0:
            vf_filters.append(f"scale={int(w)}:{int(h)}:force_original_aspect_ratio=decrease,pad={int(w)}:{int(h)}:(ow-iw)/2:(oh-ih)/2")
        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters)]

        if is_gpu and "videotoolbox" in vcodec:
            if rate_mode == "crf":
                # מיפוי CRF לאיכות VideoToolbox או ביטרייט חכם
                q_val = max(25, min(90, int(100 - crf * 1.6)))
                cmd += ["-q:v", str(q_val)]
            else:
                cmd += ["-b:v", f"{v_kbps}k"]
        elif rate_mode == "crf" and vcodec in ("libx264", "libx265", "libvpx-vp9", "libaom-av1", "libsvtav1"):
            cmd += ["-crf", str(crf)]
            if vcodec == "libvpx-vp9":
                cmd += ["-b:v", "0"]
        elif rate_mode in ("cbr", "vbr", "abr"):
            cmd += ["-b:v", f"{v_kbps}k"]
            if rate_mode == "cbr":
                cmd += ["-maxrate", f"{v_kbps}k", "-bufsize", f"{int(v_kbps)*2}k"]

        if vcodec in ("libx264", "libx265") and preset:
            cmd += ["-preset", preset]

        if fps and str(fps) != "keep":
            cmd += ["-r", str(fps)]

        if pix_fmt and str(pix_fmt) != "keep":
            cmd += ["-pix_fmt", str(pix_fmt)]

        if acodec == "copy" and not silence_trim:
            cmd += ["-c:a", "copy"]
        else:
            eff_acodec = "aac" if acodec == "copy" else acodec
            cmd += ["-c:a", eff_acodec, "-b:a", f"{a_kbps}k"]
            if silence_trim:
                cmd += ["-af", "silenceremove=start_periods=1:start_silence=0.4:start_threshold=-45dB:stop_periods=-1:stop_duration=0.9:stop_threshold=-45dB"]

        cmd += ["-map_metadata", "0", out_temp_path]
        return cmd, vcodec, is_gpu


def get_target_extension(file_info, settings):
    mtype = file_info["type"]
    if mtype == "image":
        img_fmt = settings.get("imageFormat", "webp")
        if img_fmt == "keep":
            return file_info["ext"]
        return f".{img_fmt.replace('.', '')}"
    if mtype == "audio":
        codec_id = settings.get("audioCodec", "mp3")
        ext_map = {
            "mp3": ".mp3", "aac": ".m4a", "m4a": ".m4a", "opus": ".opus",
            "ogg": ".ogg", "wma": ".wma", "ac3": ".ac3", "eac3": ".eac3",
            "dts": ".dts", "mp2": ".mp2", "amr": ".amr", "flac": ".flac",
            "alac": ".m4a", "wav_16": ".wav", "wav_24": ".wav",
            "wav_32": ".wav", "aiff": ".aiff"
        }
        return ext_map.get(codec_id, file_info["ext"])
    container = settings.get("videoContainer", "keep")
    if container and container != "keep":
        return container if container.startswith(".") else f".{container}"
    return file_info["ext"]


def generate_ab_preview(file_info, settings):
    """יצירת דגימת השוואה A/B אמיתית של 5 שניות (או תמונה מלאה) להשוואת לפני/אחרי"""
    in_path = file_info.get("path")
    if not in_path or not os.path.isfile(in_path):
        return {"error": "הקובץ המקורי לא נמצא"}

    mtype = file_info.get("type", "audio")
    target_ext = get_target_extension(file_info, settings)
    stamp = int(time.time() * 1000)

    if mtype == "image":
        out_b = os.path.join(AB_PREVIEW_DIR, f"ab_conv_{stamp}{target_ext}")
        cmd, enc_name, _ = build_ffmpeg_command(file_info, settings, out_b)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if proc.returncode != 0 or not os.path.exists(out_b):
            return {"error": "שגיאה ביצירת דגימת התמונה"}
        orig_sz = os.path.getsize(in_path)
        new_sz = os.path.getsize(out_b)
        saved_pct = round(((orig_sz - new_sz) / orig_sz) * 100, 1) if orig_sz > 0 else 0
        return {
            "ok": True,
            "type": "image",
            "origPath": in_path,
            "convPath": out_b,
            "origSizeKb": round(orig_sz / 1024, 1),
            "convSizeKb": round(new_sz / 1024, 1),
            "savedPct": saved_pct,
            "encoder": enc_name
        }

    dur = float(file_info.get("duration") or 0)
    start_sec = round(dur * 0.2, 1) if dur > 12 else 0.0
    clip_dur = min(5.0, max(1.5, dur - start_sec)) if dur > 0 else 5.0

    orig_ext = file_info.get("ext") or (".mp4" if mtype == "video" else ".mp3")
    out_a = os.path.join(AB_PREVIEW_DIR, f"ab_orig_{stamp}{orig_ext}")
    out_b = os.path.join(AB_PREVIEW_DIR, f"ab_conv_{stamp}{target_ext}")

    # גזירת 5 שניות מהמקור
    cmd_a = [
        FFMPEG_BIN, "-y", "-hide_banner",
        "-ss", str(start_sec), "-t", str(clip_dur),
        "-i", in_path, "-c", "copy", out_a
    ]
    subprocess.run(cmd_a, capture_output=True, timeout=25)
    if not os.path.exists(out_a) or os.path.getsize(out_a) == 0:
        cmd_a_fallback = [
            FFMPEG_BIN, "-y", "-hide_banner",
            "-ss", str(start_sec), "-t", str(clip_dur),
            "-i", in_path, out_a
        ]
        subprocess.run(cmd_a_fallback, capture_output=True, timeout=25)

    # המרת אותן 5 שניות בדיוק לפי ההגדרות שנבחרו
    cmd_b, enc_name, is_gpu = build_ffmpeg_command(file_info, settings, out_b, sample_clip=(start_sec, clip_dur))
    proc_b = subprocess.run(cmd_b, capture_output=True, text=True, timeout=45)
    if proc_b.returncode != 0 and is_gpu:
        # fallback אוטומטי לתוכנה אם GPU נכשל
        settings_nogpu = dict(settings, hwAccel=False)
        cmd_b, enc_name, is_gpu = build_ffmpeg_command(file_info, settings_nogpu, out_b, sample_clip=(start_sec, clip_dur))
        subprocess.run(cmd_b, capture_output=True, text=True, timeout=45)

    if not os.path.exists(out_b):
        return {"error": "שגיאה ביצירת דגימת ההשוואה"}

    orig_sz = os.path.getsize(out_a) if os.path.exists(out_a) else int((file_info.get("size", 0) * clip_dur) / max(dur, 1))
    new_sz = os.path.getsize(out_b)
    saved_pct = round(((orig_sz - new_sz) / orig_sz) * 100, 1) if orig_sz > 0 else 0

    return {
        "ok": True,
        "type": mtype,
        "startSec": start_sec,
        "clipDuration": clip_dur,
        "origPath": out_a if os.path.exists(out_a) else in_path,
        "convPath": out_b,
        "origSizeKb": round(orig_sz / 1024, 1),
        "convSizeKb": round(new_sz / 1024, 1),
        "savedPct": saved_pct,
        "encoder": enc_name
    }


def run_convert_worker(payload):
    global CURRENT_PROC
    conv = STATE["convert"]
    conv["running"] = True
    conv["cancelled"] = False
    files = payload.get("files") or []
    settings = payload.get("settings") or {}
    replace_mode = settings.get("fileReplaceMode", "replace")
    backup_suffix = settings.get("backupSuffix", "_original")
    backup_dir = settings.get("backupDir", "")
    skip_if_larger = settings.get("skipIfLarger", True)

    t_start = time.time()
    conv["started_at"] = int(t_start * 1000)
    conv["total_jobs"] = len(files)
    conv["current_job_index"] = 0
    conv["overall_progress"] = 0
    conv["speed_mb_sec"] = 0.0
    conv["eta_sec"] = 0
    conv["processed_bytes"] = 0
    conv["total_bytes"] = sum(int(f.get("size") or 0) for f in files)

    telem = conv["telemetry"]
    telem["active"] = True
    telem["rawLines"] = []

    conv["jobs"] = [
        {
            "path": f["path"],
            "name": f["name"],
            "type": f.get("type", "audio"),
            "originalMb": f["sizeMb"],
            "newMb": None,
            "savedMb": 0,
            "progress": 0,
            "status": "pending",
            "error": None
        }
        for f in files
    ]

    for idx, f in enumerate(files):
        if conv["cancelled"]:
            conv["jobs"][idx]["status"] = "cancelled"
            continue

        conv["current_job_index"] = idx
        conv["current_file"] = f["name"]
        conv["current_file_progress"] = 0
        conv["jobs"][idx]["status"] = "converting"

        in_path = f["path"]
        if not os.path.isfile(in_path):
            conv["jobs"][idx]["status"] = "error"
            conv["jobs"][idx]["error"] = "הקובץ לא נמצא"
            continue

        orig_size = os.path.getsize(in_path)
        target_ext = get_target_extension(f, settings)
        dir_name = os.path.dirname(in_path)
        base_name = os.path.splitext(os.path.basename(in_path))[0]
        temp_out = os.path.join(dir_name, f".mediamorph_tmp_{int(time.time())}_{idx}{target_ext}")
        final_out = os.path.join(dir_name, f"{base_name}{target_ext}")

        cmd, enc_name, is_gpu = build_ffmpeg_command(f, settings, temp_out)
        duration_sec = max(float(f.get("duration") or 0), 0.1)

        telem["command"] = " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd))
        telem["encoderName"] = enc_name
        telem["gpuActive"] = is_gpu
        telem["frame"] = 0
        telem["fps"] = 0.0
        telem["bitrate"] = "—"
        telem["writtenBytes"] = 0
        telem["writtenMb"] = 0.0
        telem["outTime"] = "00:00:00.00"
        telem["outTimeSec"] = 0.0
        telem["totalDurationSec"] = round(duration_sec, 2)
        telem["totalDurationFormatted"] = f.get("durationFormatted") or format_duration(duration_sec)
        telem["speedFactor"] = "1.0x"

        try:
            if f.get("type") == "image":
                conv["current_file_progress"] = 50
                conv["jobs"][idx]["progress"] = 50
                telem["rawLines"].append(f"[{f['name']}] Executing lossless/smart image engine: {enc_name}")
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                rc = proc.returncode
                if os.path.exists(temp_out):
                    wsz = os.path.getsize(temp_out)
                    telem["writtenBytes"] = wsz
                    telem["writtenMb"] = round(wsz / (1024 * 1024), 2)
            else:
                def run_stream_cmd(run_cmd):
                    global CURRENT_PROC
                    CURRENT_PROC = subprocess.Popen(
                        run_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1
                    )
                    for line in CURRENT_PROC.stdout:
                        if conv["cancelled"]:
                            CURRENT_PROC.terminate()
                            break
                        line = line.strip()
                        if not line or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip()

                        if k == "frame" and v.isdigit():
                            telem["frame"] = int(v)
                        elif k == "fps":
                            try:
                                telem["fps"] = float(v)
                            except ValueError:
                                pass
                        elif k == "bitrate":
                            telem["bitrate"] = v
                        elif k == "total_size" and v.isdigit():
                            wb = int(v)
                            telem["writtenBytes"] = wb
                            telem["writtenMb"] = round(wb / (1024 * 1024), 2)
                        elif k == "out_time":
                            telem["outTime"] = v[:11]
                        elif k in ("out_time_us", "out_time_ms") and v.isdigit():
                            sec_done = int(v) / 1_000_000.0
                            telem["outTimeSec"] = round(sec_done, 2)
                            pct = min(99, int((sec_done / duration_sec) * 100))
                            conv["current_file_progress"] = pct
                            conv["jobs"][idx]["progress"] = pct
                            conv["overall_progress"] = int(((idx + (pct / 100.0)) / len(files)) * 100)

                            elapsed = max(0.1, time.time() - t_start)
                            bytes_so_far = conv["processed_bytes"] + int(orig_size * (pct / 100.0))
                            mb_sec = (bytes_so_far / (1024 * 1024)) / elapsed
                            conv["speed_mb_sec"] = round(mb_sec, 2)
                            rem_bytes = max(0, conv["total_bytes"] - bytes_so_far)
                            conv["eta_sec"] = int((rem_bytes / (1024 * 1024)) / mb_sec) if mb_sec > 0 else 0
                        elif k == "speed":
                            telem["speedFactor"] = v
                            log_line = f"{f['name']} | time={telem['outTime']} | rate={telem['bitrate']} | written={telem['writtenMb']}MB | speed={v}"
                            if not telem["rawLines"] or telem["rawLines"][-1] != log_line:
                                telem["rawLines"].append(log_line)
                                if len(telem["rawLines"]) > 30:
                                    telem["rawLines"] = telem["rawLines"][-30:]

                    CURRENT_PROC.wait()
                    ret = CURRENT_PROC.returncode
                    CURRENT_PROC = None
                    return ret

                rc = run_stream_cmd(cmd)
                if rc != 0 and is_gpu and not conv["cancelled"]:
                    # fallback שקוף לתוכנה אם מקודד החומרה נכשל על פורמט מסוים
                    settings_nogpu = dict(settings, hwAccel=False)
                    cmd, enc_name, is_gpu = build_ffmpeg_command(f, settings_nogpu, temp_out)
                    telem["encoderName"] = enc_name + " (CPU Fallback)"
                    telem["gpuActive"] = False
                    rc = run_stream_cmd(cmd)

            if conv["cancelled"]:
                if os.path.exists(temp_out):
                    os.remove(temp_out)
                conv["jobs"][idx]["status"] = "cancelled"
                break

            if rc != 0 or not os.path.exists(temp_out):
                if os.path.exists(temp_out):
                    os.remove(temp_out)
                conv["jobs"][idx]["status"] = "error"
                conv["jobs"][idx]["error"] = f"שגיאת המרה ({rc})"
                continue

            new_size = os.path.getsize(temp_out)

            if skip_if_larger and new_size >= orig_size and target_ext.lower() == f["ext"].lower():
                os.remove(temp_out)
                new_size = orig_size
                saved_bytes = 0
                final_out = in_path
            else:
                saved_bytes = orig_size - new_size
                if replace_mode == "keep_suffix":
                    orig_ext = os.path.splitext(in_path)[1]
                    backup_path = os.path.join(dir_name, f"{base_name}{backup_suffix}{orig_ext}")
                    shutil.move(in_path, backup_path)
                    shutil.move(temp_out, final_out)
                elif replace_mode == "backup_dir" and backup_dir:
                    os.makedirs(backup_dir, exist_ok=True)
                    backup_path = os.path.join(backup_dir, os.path.basename(in_path))
                    shutil.move(in_path, backup_path)
                    shutil.move(temp_out, final_out)
                else:
                    os.remove(in_path)
                    shutil.move(temp_out, final_out)

            conv["processed_bytes"] += orig_size
            elapsed = max(0.1, time.time() - t_start)
            mb_sec = (conv["processed_bytes"] / (1024 * 1024)) / elapsed
            conv["speed_mb_sec"] = round(mb_sec, 2)
            rem_bytes = max(0, conv["total_bytes"] - conv["processed_bytes"])
            conv["eta_sec"] = int((rem_bytes / (1024 * 1024)) / mb_sec) if mb_sec > 0 else 0

            saved_mb = round(saved_bytes / (1024 * 1024), 2)
            conv["total_saved_bytes"] += max(0, saved_bytes)
            conv["total_saved_mb"] = round(conv["total_saved_bytes"] / (1024 * 1024), 2)

            conv["jobs"][idx]["status"] = "done"
            conv["jobs"][idx]["progress"] = 100
            conv["jobs"][idx]["newMb"] = round(new_size / (1024 * 1024), 2)
            conv["jobs"][idx]["savedMb"] = saved_mb
            conv["jobs"][idx]["outputPath"] = final_out
            conv["overall_progress"] = int(((idx + 1) / len(files)) * 100)

            conv["history"].insert(0, {
                "timestamp": int(time.time() * 1000),
                "name": f["name"],
                "type": f.get("type", "audio"),
                "path": final_out,
                "originalMb": round(orig_size / (1024 * 1024), 2),
                "newMb": round(new_size / (1024 * 1024), 2),
                "savedMb": saved_mb,
            })

        except Exception as e:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except Exception:
                    pass
            conv["jobs"][idx]["status"] = "error"
            conv["jobs"][idx]["error"] = str(e)

    conv["overall_progress"] = 100 if not conv["cancelled"] else conv["overall_progress"]
    conv["eta_sec"] = 0
    conv["running"] = False
    telem["active"] = False


def fast_file_hash(fpath, size):
    """חתימת SHA-256 חכמה ומהירה לאיתור קבצים כפולים בכונן"""
    h = hashlib.sha256()
    chunk = 65536
    with open(fpath, "rb") as f:
        if size <= chunk * 3:
            h.update(f.read())
        else:
            h.update(f.read(chunk))
            f.seek(size // 2)
            h.update(f.read(chunk))
            f.seek(max(0, size - chunk))
            h.update(f.read(chunk))
    return h.hexdigest()


def run_duplicates_worker(paths):
    dup = STATE["duplicates"]
    dup["running"] = True
    dup["cancelled"] = False
    dup["scanned_files"] = 0
    dup["hashed_files"] = 0
    dup["wasted_mb"] = 0.0
    dup["groups"] = []

    by_size = {}
    for root_path in paths:
        if dup["cancelled"] or not os.path.exists(root_path):
            continue
        for dirpath, dirnames, filenames in os.walk(root_path):
            if dup["cancelled"]:
                break
            dirnames[:] = [d for d in dirnames if d not in SYSTEM_SKIP_DIRS and not d.startswith("$") and not d.startswith(".")]
            for fname in filenames:
                if dup["cancelled"] or fname.startswith("."):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in ALL_MEDIA_EXTENSIONS:
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    sz = os.path.getsize(fpath)
                except OSError:
                    continue
                if sz < 4096:
                    continue
                dup["scanned_files"] += 1
                by_size.setdefault(sz, []).append(fpath)

    by_hash = {}
    for sz, flist in by_size.items():
        if dup["cancelled"]:
            break
        if len(flist) < 2:
            continue
        for fpath in flist:
            if dup["cancelled"]:
                break
            try:
                digest = fast_file_hash(fpath, sz)
                dup["hashed_files"] += 1
                by_hash.setdefault((sz, digest), []).append(fpath)
            except Exception:
                pass

    groups = []
    wasted_bytes = 0
    for (sz, digest), flist in by_hash.items():
        if len(flist) < 2:
            continue
        ext = os.path.splitext(flist[0])[1].lower()
        mtype = "video" if ext in VIDEO_EXTENSIONS else ("image" if ext in IMAGE_EXTENSIONS else "audio")
        wasted = sz * (len(flist) - 1)
        wasted_bytes += wasted
        groups.append({
            "hash": digest[:12],
            "sizeMb": round(sz / (1024 * 1024), 2),
            "wastedMb": round(wasted / (1024 * 1024), 2),
            "type": mtype,
            "count": len(flist),
            "files": [
                {"path": p, "name": os.path.basename(p), "dir": os.path.dirname(p)}
                for p in flist
            ]
        })

    groups.sort(key=lambda g: g["wastedMb"], reverse=True)
    dup["groups"] = groups
    dup["wasted_mb"] = round(wasted_bytes / (1024 * 1024), 2)
    dup["running"] = False


def run_analyze_worker(target_path):
    an = STATE["analyze"]
    an["running"] = True
    an["cancelled"] = False
    an["scanned_files"] = 0
    an["total_size_bytes"] = 0
    an["speed_files_sec"] = 0.0
    an["current_path"] = target_path
    an["result"] = None

    t0 = time.time()
    audio_bytes = 0
    video_bytes = 0
    image_bytes = 0
    other_bytes = 0
    ext_stats = {}
    dir_stats = {}
    top_files = []

    for dirpath, dirnames, filenames in os.walk(target_path):
        if an["cancelled"]:
            break
        dirnames[:] = [d for d in dirnames if d not in SYSTEM_SKIP_DIRS and not d.startswith("$")]
        for fname in filenames:
            if an["cancelled"]:
                break
            fpath = os.path.join(dirpath, fname)
            try:
                st = os.stat(fpath, follow_symlinks=False)
                sz = st.st_size
            except OSError:
                continue

            an["scanned_files"] += 1
            an["total_size_bytes"] += sz
            if an["scanned_files"] % 250 == 0:
                an["current_path"] = fpath
                elapsed = max(0.1, time.time() - t0)
                an["speed_files_sec"] = round(an["scanned_files"] / elapsed, 1)

            ext = os.path.splitext(fname)[1].lower() or "(ללא סיומת)"
            if ext in AUDIO_EXTENSIONS:
                audio_bytes += sz
                mtype = "audio"
            elif ext in VIDEO_EXTENSIONS:
                video_bytes += sz
                mtype = "video"
            elif ext in IMAGE_EXTENSIONS:
                image_bytes += sz
                mtype = "image"
            else:
                other_bytes += sz
                mtype = "other"

            if ext not in ext_stats:
                ext_stats[ext] = {"ext": ext, "count": 0, "size": 0}
            ext_stats[ext]["count"] += 1
            ext_stats[ext]["size"] += sz

            dir_stats[dirpath] = dir_stats.get(dirpath, 0) + sz

            top_files.append({
                "path": fpath,
                "name": fname,
                "dir": dirpath,
                "ext": ext,
                "type": mtype,
                "size": sz,
                "sizeMb": round(sz / (1024 * 1024), 2)
            })
            if len(top_files) > 350:
                top_files.sort(key=lambda x: x["size"], reverse=True)
                top_files = top_files[:120]

    top_files.sort(key=lambda x: x["size"], reverse=True)
    top_files = top_files[:100]

    top_dirs = [
        {"dir": k, "size": v, "sizeMb": round(v / (1024 * 1024), 2)}
        for k, v in sorted(dir_stats.items(), key=lambda item: item[1], reverse=True)[:50]
    ]
    categories = [
        {"ext": v["ext"], "count": v["count"], "size": v["size"], "sizeMb": round(v["size"] / (1024 * 1024), 2)}
        for v in sorted(ext_stats.values(), key=lambda item: item["size"], reverse=True)[:40]
    ]

    an["result"] = {
        "targetPath": target_path,
        "totalFiles": an["scanned_files"],
        "totalSizeMb": round(an["total_size_bytes"] / (1024 * 1024), 2),
        "audioSizeMb": round(audio_bytes / (1024 * 1024), 2),
        "videoSizeMb": round(video_bytes / (1024 * 1024), 2),
        "imageSizeMb": round(image_bytes / (1024 * 1024), 2),
        "otherSizeMb": round(other_bytes / (1024 * 1024), 2),
        "topFiles": top_files,
        "topDirectories": top_dirs,
        "categories": categories,
    }
    an["running"] = False


def reveal_in_file_manager(target_path):
    if not target_path or not os.path.exists(target_path):
        return False
    if IS_ANDROID:
        return android_shim.reveal(target_path)
    system = platform.system()
    try:
        if system == "Darwin":
            if os.path.isdir(target_path):
                subprocess.Popen(["open", target_path])
            else:
                subprocess.Popen(["open", "-R", target_path])
        elif system == "Windows":
            if os.path.isdir(target_path):
                subprocess.Popen(["explorer", target_path])
            else:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target_path)])
        else:
            folder = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
            subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        return False


def pick_native_folder():
    if IS_ANDROID:
        return android_shim.pick_folder()
    system = platform.system()
    try:
        if system == "Darwin":
            script = 'POSIX path of (choose folder with prompt "בחר תיקייה או כונן לסריקה:")'
            proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        elif system == "Windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }"
            )
            proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
    except Exception:
        pass
    return None


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class MediaMorphHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        ui_dir = os.environ.get("MEDIAMORPH_UI_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
        super().__init__(*args, directory=ui_dir, **kwargs)

    def log_message(self, format, *args):
        pass

    def _auth_ok(self):
        tok = os.environ.get("MEDIAMORPH_TOKEN")
        if not tok:
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "mm_token" and v == tok:
                return True
        return False

    def _send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def _serve_media_stream(self, file_path):
        if not file_path or not os.path.isfile(file_path):
            self.send_error(404, "File not found")
            return

        mime, _ = mimetypes.guess_type(file_path)
        if not mime:
            ext = os.path.splitext(file_path)[1].lower()
            mime_map = {
                ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
                ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
                ".flac": "audio/flac", ".mp4": "video/mp4", ".webm": "video/webm",
                ".mkv": "video/x-matroska", ".mov": "video/quicktime",
                ".webp": "image/webp", ".avif": "image/avif", ".png": "image/png",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"
            }
            mime = mime_map.get(ext, "application/octet-stream")

        file_size = os.path.getsize(file_path)
        range_header = self.headers.get("Range")

        try:
            with open(file_path, "rb") as f:
                if range_header and range_header.startswith("bytes="):
                    byte_range = range_header.replace("bytes=", "").split("-")
                    start = int(byte_range[0]) if byte_range[0] else 0
                    end = int(byte_range[1]) if (len(byte_range) > 1 and byte_range[1]) else file_size - 1
                    end = min(end, file_size - 1)
                    length = max(0, end - start + 1)

                    self.send_response(206)
                    self.send_header("Content-Type", mime)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.send_header("Content-Length", str(length))
                    self.end_headers()
                    f.seek(start)
                    self.wfile.write(f.read(length))
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(file_size))
                    self.end_headers()
                    shutil.copyfileobj(f, self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if not self._auth_ok():
            self.send_response(403)
            self.end_headers()
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json({
                "scan": STATE["scan"],
                "convert": STATE["convert"],
                "analyze": STATE["analyze"],
                "duplicates": STATE["duplicates"],
                "system": {
                    "platform": platform.system(),
                    "arch": platform.machine(),
                    "ffmpeg": FFMPEG_BIN,
                    "ffprobe": FFPROBE_BIN,
                }
            })
            return
        if parsed.path == "/api/volumes":
            self._send_json({"volumes": list_mounted_volumes()})
            return
        if parsed.path == "/api/pick-folder":
            folder = pick_native_folder()
            self._send_json({"path": folder})
            return
        if parsed.path == "/api/stream":
            qs = urllib.parse.parse_qs(parsed.query)
            fpath = (qs.get("path") or [""])[0]
            self._serve_media_stream(fpath)
            return
        return super().do_GET()

    def do_POST(self):
        if not self._auth_ok():
            self.send_response(403)
            self.end_headers()
            return
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}

        if parsed.path == "/api/scan/start":
            if STATE["scan"]["running"]:
                self._send_json({"error": "סריקה כבר רצה כעת"}, 400)
                return
            t = threading.Thread(target=run_scan_worker, args=(body,), daemon=True)
            t.start()
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/scan/cancel":
            STATE["scan"]["cancelled"] = True
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/estimate":
            files = body.get("files") or []
            settings = body.get("settings") or {}
            total_orig = 0.0
            total_est = 0.0
            total_saved = 0.0
            items = []
            for f in files:
                est = estimate_job_savings(f, settings)
                total_orig += est["originalMb"]
                total_est += est["estimatedMb"]
                total_saved += est["savedMb"]
                items.append({"path": f["path"], **est})
            saved_pct = round((total_saved / total_orig) * 100, 1) if total_orig > 0 else 0
            self._send_json({
                "totalOriginalMb": round(total_orig, 2),
                "totalEstimatedMb": round(total_est, 2),
                "totalSavedMb": round(total_saved, 2),
                "savedPct": saved_pct,
                "items": items
            })
            return

        if parsed.path == "/api/ab-preview":
            res = generate_ab_preview(body.get("file") or {}, body.get("settings") or {})
            self._send_json(res, 200 if res.get("ok") else 400)
            return

        if parsed.path == "/api/convert/start":
            if STATE["convert"]["running"]:
                self._send_json({"error": "המרה כבר פעילה כעת"}, 400)
                return
            t = threading.Thread(target=run_convert_worker, args=(body,), daemon=True)
            t.start()
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/convert/cancel":
            STATE["convert"]["cancelled"] = True
            if CURRENT_PROC:
                try:
                    CURRENT_PROC.terminate()
                except Exception:
                    pass
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/duplicates/start":
            if STATE["duplicates"]["running"]:
                self._send_json({"error": "איתור כפילויות כבר פעיל"}, 400)
                return
            paths = body.get("paths") or [str(Path.home())]
            t = threading.Thread(target=run_duplicates_worker, args=(paths,), daemon=True)
            t.start()
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/duplicates/cancel":
            STATE["duplicates"]["cancelled"] = True
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/duplicates/delete":
            files_to_del = body.get("paths") or []
            deleted_bytes = 0
            deleted_count = 0
            for p in files_to_del:
                if p and os.path.isfile(p):
                    try:
                        sz = os.path.getsize(p)
                        os.remove(p)
                        deleted_bytes += sz
                        deleted_count += 1
                    except Exception:
                        pass
            saved_mb = round(deleted_bytes / (1024 * 1024), 2)
            STATE["convert"]["total_saved_bytes"] += deleted_bytes
            STATE["convert"]["total_saved_mb"] = round(STATE["convert"]["total_saved_bytes"] / (1024 * 1024), 2)
            self._send_json({"ok": True, "deletedCount": deleted_count, "savedMb": saved_mb})
            return

        if parsed.path == "/api/analyze/start":
            if STATE["analyze"]["running"]:
                self._send_json({"error": "ניתוח כונן כבר פעיל"}, 400)
                return
            target = body.get("path") or str(Path.home())
            t = threading.Thread(target=run_analyze_worker, args=(target,), daemon=True)
            t.start()
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/analyze/cancel":
            STATE["analyze"]["cancelled"] = True
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/reveal":
            ok = reveal_in_file_manager(body.get("path"))
            self._send_json({"ok": ok})
            return

        self._send_json({"error": "Not found"}, 404)


def start_server(port=18492):
    server = ThreadedHTTPServer(("127.0.0.1", port), MediaMorphHandler)
    print(f"MediaMorph Engine v3.0 listening on http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18492
    start_server(port)
