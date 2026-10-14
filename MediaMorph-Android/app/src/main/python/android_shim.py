# -*- coding: utf-8 -*-
"""
שכבת התאמה לאנדרואיד עבור שרת MediaMorph.

באנדרואיד אין קבצי ffmpeg/ffprobe להרצה, אלא ספריית FFmpegKit. המודול הזה מחליף את `subprocess`
בשרת: כל קריאה ל-ffmpeg/ffprobe מנותבת דרך הגשר ב-Java (FfBridge), וההתקדמות מוחזרת בפורמט שורות
"מפתח=ערך" בדיוק כמו `ffmpeg -progress`, כך שהלוגיקה המקורית של השרת נשארת כמעט ללא שינוי.
"""
import os
import shutil
import time

from java import jarray, jclass

PIPE = -1
DEVNULL = -3
DONE = "\x00DONE"


class TimeoutExpired(Exception):
    def __init__(self, cmd=None, timeout=None):
        super().__init__("timeout expired")
        self.cmd = cmd
        self.timeout = timeout


class CompletedProcess:
    def __init__(self, args, returncode, stdout="", stderr=""):
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_FF = None
_APP = None


def _ff():
    global _FF
    if _FF is None:
        _FF = jclass("com.mediamorph.studio.FfBridge")
    return _FF


def _app():
    global _APP
    if _APP is None:
        _APP = jclass("com.mediamorph.studio.AppBridge")
    return _APP


def _jstrings(items):
    return jarray(jclass("java.lang.String"))([str(i) for i in items])


def _split(cmd):
    """מחזיר (סוג, ארגומנטים) ומתאים את פקודת ה-ffmpeg לגרסת האנדרואיד."""
    exe = os.path.basename(str(cmd[0])).lower()
    args = [str(a) for a in cmd[1:]]
    if exe == "ffprobe":
        return "probe", args
    if exe == "ffmpeg":
        out = []
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-progress":  # ההתקדמות מגיעה מהגשר, לא מ-pipe:1
                i += 2
                continue
            if a == "-nostats":
                i += 1
                continue
            out.append(a)
            i += 1
        return "ffmpeg", out
    raise FileNotFoundError("not available on Android: %s" % exe)


def run(cmd, capture_output=False, text=False, timeout=None, **kwargs):
    kind, args = _split(cmd)
    timeout_ms = int((timeout if timeout else 3600) * 1000)
    if kind == "probe":
        # הפקודה המקורית מסתיימת בנתיב הקובץ; הגשר מחזיר JSON באותו מבנה של ffprobe
        js = _ff().probeJson(str(args[-1]), timeout_ms)
        js = str(js) if js is not None else ""
        return CompletedProcess(cmd, 0 if js else 1, js, "")
    res = str(_ff().runSync(_jstrings(args), timeout_ms))
    head, _, body = res.partition("\n")
    code = head[3:] if head.startswith("RC:") else "-1"
    if code == "TIMEOUT":
        raise TimeoutExpired(cmd, timeout)
    return CompletedProcess(cmd, int(code), "", body)


class Popen:
    """תחליף ל-subprocess.Popen עבור המרות עם התקדמות בזמן אמת."""

    def __init__(self, cmd, stdout=None, stderr=None, text=False, bufsize=-1, **kwargs):
        kind, args = _split(cmd)
        if kind != "ffmpeg":
            raise FileNotFoundError("only ffmpeg can be streamed on Android")
        self._h = int(_ff().start(_jstrings(args)))
        self.returncode = None
        self.stdout = self._lines()
        self.stderr = iter(())

    def _lines(self):
        while True:
            chunk = str(_ff().poll(self._h))
            if chunk == DONE:
                return
            if not chunk:
                time.sleep(0.15)
                continue
            for line in chunk.split("\n"):
                if line:
                    yield line + "\n"

    def poll(self):
        if self.returncode is None and _ff().isDone(self._h):
            self.returncode = int(_ff().returnCode(self._h))
        return self.returncode

    def wait(self, timeout=None):
        start = time.time()
        while self.poll() is None:
            if timeout is not None and time.time() - start > timeout:
                raise TimeoutExpired(None, timeout)
            time.sleep(0.05)
        _ff().release(self._h)
        return self.returncode

    def terminate(self):
        _ff().cancel(self._h)

    kill = terminate


# ---------- פונקציות שעוקפות פעולות של מק/וינדוס ----------

def volumes():
    out = []

    def add(name, path):
        try:
            u = shutil.disk_usage(path)
        except Exception:
            return
        out.append({
            "name": name,
            "path": path,
            "totalGb": round(u.total / (1024 ** 3), 1),
            "usedGb": round(u.used / (1024 ** 3), 1),
            "freeGb": round(u.free / (1024 ** 3), 1),
            "usedPct": round((u.used / u.total) * 100, 1) if u.total else 0,
        })

    primary = "/storage/emulated/0"
    if os.path.isdir(primary):
        add("זיכרון פנימי", primary)
    try:
        for n in sorted(os.listdir("/storage")):
            if n in ("emulated", "self"):
                continue
            p = os.path.join("/storage", n)
            if os.path.isdir(p) and os.access(p, os.R_OK):
                add("כרטיס זיכרון (%s)" % n, p)
    except Exception:
        pass
    if not out:
        add("אחסון", os.path.expanduser("~"))
    return out


def pick_folder():
    p = str(_app().pickFolder())
    return p or None


def reveal(path):
    return bool(_app().reveal(str(path)))
