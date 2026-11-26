import json
import os
import re
import urllib.request
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi

PREFERRED = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
]
NOT_CHAT = ("whisper", "tts", "guard", "orpheus", "playai", "embed", "compound", "safeguard")
MAX_CHARS = 20000
STYLES = {
    "short": "Write a short summary (3-4 sentences), then 5 key takeaways as bullet points.",
    "detailed": "Write a detailed, well-structured summary with headings and bullet points "
    "covering every major section of the video.",
    "simple": "Explain the video in very simple language, like to a 15-year-old, "
    "using short sentences and one everyday example.",
}
LANGUAGES = {
    "English": "English",
    "Hindi": "Hindi (Devanagari script)",
    "Hinglish": "Hinglish (Hindi written in English letters)",
}

app = FastAPI(title="Chat with YouTube")
BASE = Path(__file__).parent / "static"


@lru_cache(maxsize=1)
def client() -> Groq:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise HTTPException(500, "Server is missing GROQ_API_KEY.")
    return Groq(api_key=key)


@lru_cache(maxsize=1)
def models() -> list:
    try:
        ids = [m.id for m in client().models.list().data]
    except Exception:  # noqa: BLE001
        return PREFERRED
    chat = [i for i in ids if not any(b in i.lower() for b in NOT_CHAT)]
    return ([m for m in PREFERRED if m in chat] + [m for m in chat if m not in PREFERRED]) or PREFERRED


def ask(messages: list) -> str:
    errors = []
    for model in models()[:4]:
        try:
            r = client().chat.completions.create(model=model, messages=messages, temperature=0.3)
            return r.choices[0].message.content
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    text = " ".join(errors).lower()
    if "429" in text or "rate limit" in text:
        raise HTTPException(429, "Rate limit hit on the free tier. Wait a minute and try again.")
    if "413" in text or "too large" in text:
        raise HTTPException(413, "The transcript is too long for the free tier. Try a shorter video.")
    raise HTTPException(502, "The AI service failed. Try again in a moment.")


def system_prompt(transcript: str, language: str) -> str:
    lang = LANGUAGES.get(language, "English")
    return (
        "You answer questions about a YouTube video using ONLY its transcript below. "
        "If the answer is not in the transcript, say so. Be clear and concise. "
        f"Always reply in {lang}.\n\nTRANSCRIPT:\n{transcript[:MAX_CHARS]}"
    )


def video_id_from(url: str):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def fetch_title(video_id: str) -> str:
    try:
        u = f"https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={video_id}"
        with urllib.request.urlopen(u, timeout=5) as r:
            return json.load(r).get("title", "")
    except Exception:  # noqa: BLE001
        return ""


class LoadReq(BaseModel):
    url: str = ""
    transcript: str = ""


class SummaryReq(BaseModel):
    transcript: str
    style: str = "short"
    language: str = "English"


class Msg(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    transcript: str
    messages: list[Msg]
    language: str = "English"


@app.post("/api/load")
def load(req: LoadReq):
    vid = video_id_from(req.url)
    transcript = req.transcript.strip()
    if not transcript:
        if not vid:
            raise HTTPException(400, "That doesn't look like a YouTube link. Paste a full video URL.")
        try:
            snippets = YouTubeTranscriptApi().fetch(vid, languages=["en", "hi"])
            transcript = " ".join(s.text for s in snippets)
        except Exception:  # noqa: BLE001
            raise HTTPException(
                422,
                "Couldn't fetch the transcript. Captions may be off, or YouTube is blocking "
                "this server. Paste the transcript manually instead.",
            )
    return {
        "video_id": vid,
        "title": fetch_title(vid) if vid else "",
        "transcript": transcript,
        "words": len(transcript.split()),
        "truncated": len(transcript) > MAX_CHARS,
        "max_chars": MAX_CHARS,
    }


@app.post("/api/summary")
def summary(req: SummaryReq):
    msgs = [
        {"role": "system", "content": system_prompt(req.transcript, req.language)},
        {"role": "user", "content": STYLES.get(req.style, STYLES["short"])},
    ]
    return {"text": ask(msgs)}


@app.post("/api/chat")
def chat(req: ChatReq):
    history = [m.model_dump() for m in req.messages if m.role in ("user", "assistant")][-20:]
    msgs = [{"role": "system", "content": system_prompt(req.transcript, req.language)}] + history
    return {"text": ask(msgs)}


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


app.mount("/static", StaticFiles(directory=BASE), name="static")
