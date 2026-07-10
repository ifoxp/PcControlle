"""
Вставляє deep-link intent-filter (pccontrol://pair) у згенерований flet-ом
AndroidManifest.xml. flet 0.85 лишає лише маркер-коментар, а сам filter не додає
(баг версії) — тому патчимо після flet build, перед flutter build.

Ідемпотентно: якщо filter уже є — нічого не робить.
"""

import pathlib
import sys

MANIFEST = pathlib.Path(__file__).parent / "build" / "flutter" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"

MARKER = "<!-- flet: deep linking  -->"
INTENT = """<!-- flet: deep linking  -->
            <!-- PC Control: pccontrol://pair (скан QR -> застосунок) -->
            <intent-filter>
                <action android:name="android.intent.action.VIEW" />
                <category android:name="android.intent.category.DEFAULT" />
                <category android:name="android.intent.category.BROWSABLE" />
                <data android:scheme="pccontrol" android:host="pair" />
            </intent-filter>"""


def main() -> int:
    if not MANIFEST.exists():
        print(f"ПОМИЛКА: маніфест не знайдено: {MANIFEST}")
        return 1
    text = MANIFEST.read_text(encoding="utf-8")
    if 'android:scheme="pccontrol"' in text:
        print("intent-filter уже присутній — пропускаю.")
        return 0
    if MARKER not in text:
        print("ПОМИЛКА: маркер deep-link не знайдено в маніфесті.")
        return 1
    text = text.replace(MARKER, INTENT, 1)
    MANIFEST.write_text(text, encoding="utf-8")
    print("intent-filter вставлено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
