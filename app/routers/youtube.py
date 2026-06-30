import json
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.helpers import get_ai_client
from app.core.security import ai_rate_limit

router = APIRouter(tags=["youtube"])


class YoutubeRequest(BaseModel):
    url: str


class YoutubeAskRequest(BaseModel):
    url: str
    question: str
    transcript: Optional[str] = None


def _extract_video_id(url: str) -> Optional[str]:
    patterns = [r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})"]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


@router.post("/api/youtube/info")
async def youtube_info(req: YoutubeRequest):
    vid = _extract_video_id(req.url)
    if not vid:
        raise HTTPException(400, "Invalid YouTube URL")
    try:
        import yt_dlp
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        return {
            "video_id":   vid,
            "title":      info.get("title", ""),
            "channel":    info.get("uploader", ""),
            "duration":   info.get("duration", 0),
            "view_count": info.get("view_count", 0),
            "like_count": info.get("like_count", 0),
            "description": (info.get("description") or "")[:800],
            "thumbnail":  info.get("thumbnail", ""),
            "upload_date": info.get("upload_date", ""),
            "tags":       (info.get("tags") or [])[:10],
        }
    except Exception as e:
        raise HTTPException(502, f"Could not fetch video info: {e}")


@router.post("/api/youtube/transcript")
async def youtube_transcript(req: YoutubeRequest):
    vid = _extract_video_id(req.url)
    if not vid:
        raise HTTPException(400, "Invalid YouTube URL")
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(vid)
            try:
                t = transcript_list.find_manually_created_transcript(["ar", "en"])
            except Exception:
                try:
                    t = transcript_list.find_generated_transcript(["ar", "en"])
                except Exception:
                    t = next(iter(transcript_list))
            entries = t.fetch()
            text = " ".join(e.text for e in entries)
            return {"video_id": vid, "language": t.language_code, "transcript": text, "length": len(text)}
        except (NoTranscriptFound, TranscriptsDisabled):
            raise HTTPException(404, "No transcript available for this video.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


@router.post("/api/youtube/analyze/stream")
async def youtube_analyze_stream(req: YoutubeAskRequest, request: Request):
    ai_rate_limit(request)
    ai = get_ai_client()

    transcript = req.transcript or ""
    system = (
        "You are a YouTube video analyst. You are given the transcript of a video and a user question. "
        "Answer thoughtfully using the transcript content. If summarizing, include key points with bullet points. "
        "If the transcript is empty, say so and answer from general knowledge."
    )
    user_msg = f"VIDEO TRANSCRIPT:\n{transcript[:6000]}\n\n---\nQUESTION: {req.question}"

    async def event_stream():
        try:
            with ai.messages.stream(
                model="claude-sonnet-4-6", max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
