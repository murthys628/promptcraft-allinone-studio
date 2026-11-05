import json
import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
import datetime
import urllib.error
import urllib.request
import os
import re
import tempfile
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import edge_tts
except ImportError:
    edge_tts = None


LANGUAGE_PREFIXES = {
    "kn-IN": ("kn", "kannada"),
    "hi-IN": ("hi", "hindi"),
    "ta-IN": ("ta", "tamil"),
    "te-IN": ("te", "telugu"),
    "ml-IN": ("ml", "malayalam"),
    "bn-IN": ("bn", "bengali"),
    "mr-IN": ("mr", "marathi"),
    "gu-IN": ("gu", "gujarati"),
    "pa-IN": ("pa", "punjabi"),
    "en-IN": ("en", "english"),
    "en-US": ("en", "english"),
}

EDGE_VOICES = {
    "kn-IN": "kn-IN-SapnaNeural",
    "hi-IN": "hi-IN-SwaraNeural",
    "ta-IN": "ta-IN-PallaviNeural",
    "te-IN": "te-IN-ShrutiNeural",
    "ml-IN": "ml-IN-SobhanaNeural",
    "bn-IN": "bn-IN-TanishaaNeural",
    "mr-IN": "mr-IN-AarohiNeural",
    "gu-IN": "gu-IN-DhwaniNeural",
    "ur-IN": "ur-IN-GulNeural",
    "ne-NP": "ne-NP-HemkalaNeural",
    # No dedicated Edge voice: closest voice of the same script is used.
    "as-IN": "bn-IN-TanishaaNeural",
    "sa-IN": "hi-IN-SwaraNeural",
    "kok-IN": "mr-IN-AarohiNeural",
    "mai-IN": "hi-IN-SwaraNeural",
    "doi-IN": "hi-IN-SwaraNeural",
    "brx-IN": "hi-IN-SwaraNeural",
    "ks-IN": "ur-IN-GulNeural",
    "sd-IN": "ur-IN-GulNeural",
    "en-IN": "en-IN-NeerjaNeural",
    "en-US": "en-US-AriaNeural",
}


def choose_voice(engine, language):
    prefixes = LANGUAGE_PREFIXES.get(language, ("en", "english"))
    voices = engine.getProperty("voices")
    for voice in voices:
        metadata = " ".join(
            str(getattr(voice, key, "")) for key in ("id", "name", "languages")
        ).lower()
        if any(prefix in metadata for prefix in prefixes):
            return voice
    raise RuntimeError(
        f"No installed Windows speech voice matches {language}. "
        "Install that language's speech voice in Windows Settings and try again."
    )


def create_wav(text, language):
    if pyttsx3 is None:
        raise RuntimeError(
            "pyttsx3 is not installed. Run: py -m pip install pyttsx3"
        )
    engine = pyttsx3.init()
    voice = choose_voice(engine, language)
    engine.setProperty("voice", voice.id)
    engine.setProperty("rate", 145)
    output_path = tempfile.mktemp(suffix=".wav")
    engine.save_to_file(text, output_path)
    engine.runAndWait()
    engine.stop()
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("The installed speech voice returned no audio.")
    return output_path


async def create_edge_audio(text, language, output_path):
    voice = EDGE_VOICES.get(language, EDGE_VOICES["en-IN"])
    parts = split_brand_segments(text) if language != "en-IN" else [(text, False)]
    if len(parts) == 1:
        communicator = edge_tts.Communicate(text, voice)
        await communicator.save(output_path)
        return
    audio = b""
    for segment, is_brand in parts:
        segment_voice = EDGE_VOICES["en-IN"] if is_brand else voice
        chunks = edge_tts.Communicate(segment, segment_voice).stream()
        async for chunk in chunks:
            if chunk["type"] == "audio":
                audio += chunk["data"]
    with open(output_path, "wb") as output:
        output.write(audio)


# The Kannada voice misreads the letter ಝ, so the company name is spoken by the English voice.
BRAND_SPOKEN = {
    "ಪೆಝೋಸಿಸ್": "Pezosys",
}


def split_brand_segments(text):
    pattern = "(" + "|".join(re.escape(name) for name in BRAND_SPOKEN) + ")"
    segments = []
    for piece in re.split(pattern, text):
        if not piece.strip():
            continue
        if piece in BRAND_SPOKEN:
            segments.append((BRAND_SPOKEN[piece], True))
        else:
            segments.append((piece, False))
    return segments


def create_audio(text, language):
    if edge_tts is not None:
        output_path = tempfile.mktemp(suffix=".mp3")
        try:
            asyncio.run(create_edge_audio(text, language, output_path))
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path, "audio/mpeg"
        except Exception:
            if os.path.exists(output_path):
                os.remove(output_path)
    return create_wav(text, language), "audio/wav"


IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_QUALITY = os.environ.get("OPENAI_IMAGE_QUALITY", "medium")
IMAGE_DAILY_LIMIT = int(os.environ.get("IMAGE_DAILY_LIMIT", "20"))
_image_usage = {"day": "", "count": 0}


def load_openai_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openai_key.txt")
    if os.path.exists(key_file):
        with open(key_file, encoding="utf-8") as handle:
            return handle.read().strip()
    return ""


def create_openai_image(prompt, orientation):
    key = load_openai_key()
    if not key:
        raise ValueError(
            "No OpenAI API key found. Put your key in a file named openai_key.txt next to tts_server.py "
            "(or set OPENAI_API_KEY) and restart the server."
        )
    today = datetime.date.today().isoformat()
    if _image_usage["day"] != today:
        _image_usage.update(day=today, count=0)
    if _image_usage["count"] >= IMAGE_DAILY_LIMIT:
        raise ValueError(f"Daily image limit of {IMAGE_DAILY_LIMIT} reached. Try again tomorrow.")
    size = "1536x1024" if orientation == "landscape" else "1024x1536"
    payload = json.dumps({
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "size": size,
        "quality": IMAGE_QUALITY,
        "n": 1,
    }).encode("utf-8")
    api_request = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(api_request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "ignore")
        try:
            detail = json.loads(detail)["error"]["message"]
        except Exception:
            pass
        raise ValueError(f"OpenAI error {error.code}: {detail}")
    _image_usage["count"] += 1
    item = data["data"][0]
    if item.get("b64_json"):
        return item["b64_json"]
    raise ValueError("OpenAI returned no image data.")


APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", APP_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
AUTH_DB = os.path.join(DATA_DIR, "users.db")
if os.environ.get("PORT") and not os.environ.get("DATA_DIR"):
    print("WARNING: DATA_DIR is not set. Accounts are stored on temporary storage and will be lost on every deploy. "
          "Attach a persistent disk and set DATA_DIR to its mount path.")
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500").split(",")
    if origin.strip()
}
SESSION_DAYS = 30


def auth_db():
    db = sqlite3.connect(AUTH_DB)
    db.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, "
        "salt BLOB, pw_hash BLOB, created TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER, expires TEXT)"
    )
    return db


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)


def issue_session(db, user_id):
    token = secrets.token_urlsafe(32)
    expires = (datetime.datetime.utcnow() + datetime.timedelta(days=SESSION_DAYS)).isoformat()
    db.execute(
        "INSERT INTO sessions VALUES (?, ?, ?)",
        (hashlib.sha256(token.encode()).hexdigest(), user_id, expires),
    )
    db.commit()
    return token


def user_for_token(token):
    if not token:
        return None
    with closing(auth_db()) as db:
        row = db.execute(
            "SELECT u.id, u.name, u.email, s.expires FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
    if not row or row[3] < datetime.datetime.utcnow().isoformat():
        return None
    return {"id": row[0], "name": row[1], "email": row[2]}


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def signup_user(name, email, password):
    name = name.strip()
    email = email.strip().lower()
    if len(name) < 2:
        raise ValueError("Please enter your name.")
    if not EMAIL_PATTERN.match(email):
        raise ValueError("Please enter a valid email address.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_bytes(16)
    with closing(auth_db()) as db:
        try:
            cursor = db.execute(
                "INSERT INTO users (name, email, salt, pw_hash, created) VALUES (?, ?, ?, ?, ?)",
                (name, email, salt, hash_password(password, salt), datetime.datetime.utcnow().isoformat()),
            )
        except sqlite3.IntegrityError:
            raise ValueError("An account with this email already exists. Please log in.")
        token = issue_session(db, cursor.lastrowid)
    return token, {"name": name, "email": email}


def login_user(email, password):
    email = email.strip().lower()
    with closing(auth_db()) as db:
        row = db.execute("SELECT id, name, salt, pw_hash FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not hmac.compare_digest(hash_password(password, row[2]), row[3]):
            raise ValueError("Incorrect email or password.")
        token = issue_session(db, row[0])
    return token, {"name": row[1], "email": email}


class TtsHandler(BaseHTTPRequestHandler):
    def current_user(self):
        header = self.headers.get("Authorization", "")
        return user_for_token(header[7:] if header.startswith("Bearer ") else "")

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path == "/auth/me":
            user = self.current_user()
            if user:
                self.send_json(200, {"user": user})
            else:
                self.send_json(401, {"error": "Please log in."})
            return
        if self.path in ("/", "/index.html"):
            with open(os.path.join(APP_DIR, "index.html"), "rb") as page:
                body = page.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/healthz":
            self.send_json(200, {"ok": True})
            return
        if self.path == "/config":
            self.send_json(200, {"imageGeneration": bool(load_openai_key())})
            return
        self.send_json(404, {"error": "Not found."})

    def send_cors_origin(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_cors_origin()
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_origin()
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_POST(self):
        if self.path in ("/auth/signup", "/auth/login"):
            try:
                request = self.read_json()
                if self.path == "/auth/signup":
                    token, user = signup_user(
                        str(request.get("name", "")), str(request.get("email", "")), str(request.get("password", ""))
                    )
                else:
                    token, user = login_user(str(request.get("email", "")), str(request.get("password", "")))
                self.send_json(200, {"token": token, "user": user})
            except Exception as error:
                self.send_json(400, {"error": str(error)})
            return
        if self.path == "/auth/logout":
            header = self.headers.get("Authorization", "")
            token = header[7:] if header.startswith("Bearer ") else ""
            with closing(auth_db()) as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
                db.commit()
            self.send_json(200, {"ok": True})
            return
        if self.path in ("/image", "/tts") and not self.current_user():
            self.send_json(401, {"error": "Please log in to use this feature."})
            return
        if self.path == "/image":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                prompt = str(request.get("prompt", "")).strip()
                if not prompt:
                    raise ValueError("Image prompt is empty.")
                if len(prompt) > 4000:
                    raise ValueError("Image prompt is too long; keep it under 4000 characters.")
                orientation = "landscape" if request.get("orientation") == "landscape" else "portrait"
                self.send_json(200, {"image": create_openai_image(prompt, orientation)})
            except Exception as error:
                self.send_json(400, {"error": str(error)})
            return
        if self.path != "/tts":
            self.send_json(404, {"error": "Use POST /tts or POST /image."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            text = str(request.get("text", "")).strip()
            language = str(request.get("language", "en-IN"))
            if not text:
                raise ValueError("Narration text is empty.")
            if len(text) > 12000:
                raise ValueError("Narration text is too long; keep it under 12000 characters.")
            path, content_type = create_audio(text, language)
            try:
                with open(path, "rb") as audio:
                    body = audio.read()
            finally:
                os.remove(path)
            self.send_response(200)
            self.send_cors_origin()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as error:
            self.send_json(400, {"error": str(error)})


if __name__ == "__main__":
    # Render sets PORT and needs 0.0.0.0; locally we stay on 127.0.0.1:8765.
    port = int(os.environ.get("PORT", "8765"))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    print(f"PromptCraft server: http://{host}:{port}/")
    ThreadingHTTPServer((host, port), TtsHandler).serve_forever()
