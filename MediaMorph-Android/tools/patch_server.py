#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
יוצר את גרסת האנדרואיד של server.py מהגרסה המקורית של האפליקציה במק.
שימוש:  python3 tools/patch_server.py <server.py מקורי> app/src/main/python/server.py
כל החלפה נבדקת: אם הקובץ המקורי השתנה והמקום לא נמצא, הסקריפט נעצר עם הודעה ברורה.
"""
import sys

REPLACEMENTS = [
    # 1. ב-Android מחליפים את subprocess בשכבת ההתאמה
    (
        "import subprocess\n",
        "IS_ANDROID = \"ANDROID_ROOT\" in os.environ and \"ANDROID_DATA\" in os.environ\n"
        "if IS_ANDROID:\n"
        "    import android_shim\n"
        "    subprocess = android_shim\n"
        "else:\n"
        "    import subprocess\n",
    ),
    # 2. אין קבצי הרצה בנתיב; ffmpeg/ffprobe מנותבים דרך הגשר
    (
        "def find_binary(name):\n",
        "def find_binary(name):\n    if IS_ANDROID:\n        return name\n",
    ),
    # 3. האצת חומרה כבויה בשלב הזה (MediaCodec דורש הגדרות ביטרייט אחרות)
    (
        "    if not use_gpu:\n        return vcodec, False\n    sys_name = platform.system()\n",
        "    if not use_gpu or IS_ANDROID:\n        return vcodec, False\n    sys_name = platform.system()\n",
    ),
    # 4. המרת WebP באנדרואיד דרך libwebp של FFmpeg (אין cwebp)
    (
        "        elif img_format in (\"png\", \"webp\"):\n",
        "        elif img_format == \"webp\" and IS_ANDROID:\n"
        "            cmd += [\"-c:v\", \"libwebp\", \"-lossless\", \"1\" if img_mode == \"lossless\" else \"0\",\n"
        "                    \"-q:v\", str(img_quality), \"-compression_level\", \"6\"]\n"
        "        elif img_format in (\"png\", \"webp\"):\n",
    ),
    # 5. כוננים
    (
        "def list_mounted_volumes():\n    volumes = []\n",
        "def list_mounted_volumes():\n    if IS_ANDROID:\n        return android_shim.volumes()\n    volumes = []\n",
    ),
    # 6. הצגה בתיקייה
    (
        "def reveal_in_file_manager(target_path):\n    if not target_path or not os.path.exists(target_path):\n        return False\n",
        "def reveal_in_file_manager(target_path):\n    if not target_path or not os.path.exists(target_path):\n        return False\n"
        "    if IS_ANDROID:\n        return android_shim.reveal(target_path)\n",
    ),
    # 7. בחירת תיקייה
    (
        "def pick_native_folder():\n    system = platform.system()\n",
        "def pick_native_folder():\n    if IS_ANDROID:\n        return android_shim.pick_folder()\n    system = platform.system()\n",
    ),
    # 8. תיקיית הממשק מגיעה מהאפליקציה
    (
        "        ui_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), \"ui\")\n",
        "        ui_dir = os.environ.get(\"MEDIAMORPH_UI_DIR\") or os.path.join(os.path.dirname(os.path.abspath(__file__)), \"ui\")\n",
    ),
    # 9. הגנה: רק הממשק של האפליקציה (שמחזיק את הטוקן הסודי) יכול לדבר עם השרת.
    #    בלי זה, כל אפליקציה אחרת בטלפון הייתה יכולה לגשת לשרת המקומי ולמחוק קבצים.
    (
        "    def log_message(self, format, *args):\n        pass\n",
        "    def log_message(self, format, *args):\n        pass\n\n"
        "    def _auth_ok(self):\n"
        "        tok = os.environ.get(\"MEDIAMORPH_TOKEN\")\n"
        "        if not tok:\n"
        "            return True\n"
        "        for part in (self.headers.get(\"Cookie\") or \"\").split(\";\"):\n"
        "            k, _, v = part.strip().partition(\"=\")\n"
        "            if k == \"mm_token\" and v == tok:\n"
        "                return True\n"
        "        return False\n",
    ),
    (
        "    def do_GET(self):\n",
        "    def do_GET(self):\n        if not self._auth_ok():\n            self.send_response(403)\n            self.end_headers()\n            return\n",
    ),
    (
        "    def do_POST(self):\n",
        "    def do_POST(self):\n        if not self._auth_ok():\n            self.send_response(403)\n            self.end_headers()\n            return\n",
    ),
]


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    src = open(sys.argv[1], encoding="utf-8").read()
    for old, new in REPLACEMENTS:
        n = src.count(old)
        if n != 1:
            print("נכשל: מצאתי %d התאמות (צריך בדיוק 1) עבור:\n%s" % (n, old))
            sys.exit(1)
        src = src.replace(old, new)
    open(sys.argv[2], "w", encoding="utf-8").write(src)
    print("נוצר:", sys.argv[2])


if __name__ == "__main__":
    main()
