"""
MoodWave – Flask Backend
========================
Serves the frontend and proxies all Jamendo API calls server-side.
Adds in-memory caching (TTL 10 min) so repeated requests are instant.

Setup:
  pip install -r requirements.txt
  python app.py          # dev
  gunicorn app:app       # prod

Optional env vars:
  JAMENDO_CLIENT_ID   – your own Jamendo client_id (default: public sandbox key)
  ANTHROPIC_API_KEY   – enables AI mood-analysis endpoint
  PORT                – listen port (default 5000)
  FLASK_ENV           – set to 'development' for debug mode
"""

import os
import time
import hashlib
import datetime
import requests

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# ── optional Anthropic (graceful if not installed) ──────────────────────────
try:
    import anthropic as _anthropic
    _ant_client = _anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    ANTHROPIC_OK = bool(os.environ.get("ANTHROPIC_API_KEY"))
except Exception:
    _ant_client = None
    ANTHROPIC_OK = False

# ── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app, resources={r"/api/*": {"origins": "*"}})

JAMENDO_CLIENT_ID = os.environ.get("JAMENDO_CLIENT_ID", "b6747d04")
JAMENDO_BASE      = "https://api.jamendo.com/v3.0"

# ── Simple in-memory cache ────────────────────────────────────────────────────
_CACHE: dict = {}          # key → {"data": ..., "ts": float}
CACHE_TTL = 600            # seconds (10 minutes)

def _cache_get(key: str):
    entry = _CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    return None

def _cache_set(key: str, data):
    _CACHE[key] = {"data": data, "ts": time.time()}
    # Evict old entries if cache grows large
    if len(_CACHE) > 500:
        cutoff = time.time() - CACHE_TTL
        stale = [k for k, v in _CACHE.items() if v["ts"] < cutoff]
        for k in stale:
            _CACHE.pop(k, None)

def _cache_key(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES – Static
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Serve the main HTML app."""
    return send_from_directory(".", "moodmusic.html")


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES – Jamendo proxy  (all calls go server-side; CORS + key hidden)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/tracks", methods=["GET"])
def get_tracks():
    """
    Proxy Jamendo track search.
    Query params:
      tags     – space or + separated tag string (required)
      limit    – int, default 15, max 50
      offset   – int, default 0
      order    – string, default popularity_total
    Returns Jamendo results array directly, plus cache metadata.
    """
    tags   = request.args.get("tags", "").strip()
    limit  = min(int(request.args.get("limit",  15)), 50)
    offset = int(request.args.get("offset", 0))
    order  = request.args.get("order", "popularity_total")

    if not tags:
        return jsonify({"error": "tags param required"}), 400

    ck = _cache_key("tracks", tags, limit, offset, order)
    cached = _cache_get(ck)
    if cached is not None:
        return jsonify({"results": cached, "cached": True, "count": len(cached)})

    params = {
        "client_id":   JAMENDO_CLIENT_ID,
        "format":      "json",
        "limit":       limit,
        "offset":      offset,
        "tags":        tags.replace("+", " "),
        "audioformat": "mp32",
        "include":     "musicinfo",
        "order":       order,
    }
    try:
        resp = requests.get(f"{JAMENDO_BASE}/tracks/", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return jsonify({"error": "Jamendo timeout", "results": []}), 504
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 502

    results = data.get("results", [])
    _cache_set(ck, results)
    return jsonify({"results": results, "cached": False, "count": len(results)})


@app.route("/api/search", methods=["GET"])
def search_tracks():
    """
    Full-text search across Jamendo.
    Query params:
      q      – search query string (required)
      limit  – int, default 20, max 50
      offset – int, default 0
    """
    q      = request.args.get("q", "").strip()
    limit  = min(int(request.args.get("limit",  20)), 50)
    offset = int(request.args.get("offset", 0))

    if not q:
        return jsonify({"error": "q param required"}), 400

    ck = _cache_key("search", q, limit, offset)
    cached = _cache_get(ck)
    if cached is not None:
        return jsonify({"results": cached, "cached": True, "count": len(cached)})

    params = {
        "client_id":   JAMENDO_CLIENT_ID,
        "format":      "json",
        "limit":       limit,
        "offset":      offset,
        "namesearch":  q,
        "audioformat": "mp32",
        "include":     "musicinfo",
        "order":       "popularity_total",
    }
    try:
        resp = requests.get(f"{JAMENDO_BASE}/tracks/", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 502

    results = data.get("results", [])
    _cache_set(ck, results)
    return jsonify({"results": results, "cached": False, "count": len(results)})


@app.route("/api/artist-tracks", methods=["GET"])
def artist_tracks():
    """
    Fetch tracks by artist name.
    Query params:
      artist  – artist name string (required)
      limit   – int, default 10
    """
    artist = request.args.get("artist", "").strip()
    limit  = min(int(request.args.get("limit", 10)), 50)

    if not artist:
        return jsonify({"error": "artist param required"}), 400

    ck = _cache_key("artist", artist, limit)
    cached = _cache_get(ck)
    if cached is not None:
        return jsonify({"results": cached, "cached": True})

    params = {
        "client_id":   JAMENDO_CLIENT_ID,
        "format":      "json",
        "limit":       limit,
        "artist_name": artist,
        "audioformat": "mp32",
        "include":     "musicinfo",
        "order":       "popularity_total",
    }
    try:
        resp = requests.get(f"{JAMENDO_BASE}/tracks/", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 502

    results = data.get("results", [])
    _cache_set(ck, results)
    return jsonify({"results": results, "cached": False})


@app.route("/api/mood-playlist", methods=["POST"])
def mood_playlist():
    """
    Build a full playlist for a mood + list of tag-sets.
    Body JSON:
      {
        "mood":     "happy",
        "tag_sets": ["pop+happy+upbeat", "bollywood+dance"],
        "limit":    10,
        "offset":   0
      }
    Returns merged, deduplicated track list.
    """
    body     = request.get_json(silent=True) or {}
    mood     = body.get("mood", "calm")
    tag_sets = body.get("tag_sets", [])
    limit    = min(int(body.get("limit",  10)), 50)
    offset   = int(body.get("offset", 0))

    if not tag_sets:
        return jsonify({"error": "tag_sets required", "tracks": []}), 400

    all_tracks = []
    seen_ids   = set()

    for tags in tag_sets:
        ck = _cache_key("tracks", tags, limit, offset)
        cached = _cache_get(ck)
        if cached is not None:
            results = cached
        else:
            params = {
                "client_id":   JAMENDO_CLIENT_ID,
                "format":      "json",
                "limit":       limit,
                "offset":      offset,
                "tags":        tags.replace("+", " "),
                "audioformat": "mp32",
                "include":     "musicinfo",
                "order":       "popularity_total",
            }
            try:
                resp = requests.get(f"{JAMENDO_BASE}/tracks/", params=params, timeout=10)
                resp.raise_for_status()
                results = resp.json().get("results", [])
                _cache_set(ck, results)
            except Exception:
                results = []

        for t in results:
            tid = t.get("id")
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                all_tracks.append(_format_track(t, mood))

    return jsonify({
        "mood":   mood,
        "tracks": all_tracks,
        "count":  len(all_tracks),
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES – AI  (optional, needs ANTHROPIC_API_KEY)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/analyze-mood", methods=["POST"])
def analyze_mood():
    """
    Analyze free-text journal entry → mood.
    Body: { "text": "feeling really tired and low today…" }
    Returns: { "mood": "sad", "confidence": 0.9, "note": "..." }
    """
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()[:600]

    if not text:
        return jsonify({"error": "No text provided"}), 400

    if not ANTHROPIC_OK:
        return jsonify({
            "mood":       "calm",
            "confidence": 0.5,
            "note":       "Set ANTHROPIC_API_KEY for AI mood detection."
        })

    try:
        resp = _ant_client.messages.create(
            model      = "claude-sonnet-4-20250514",
            max_tokens = 120,
            system     = (
                'Analyze the emotional tone of the text. '
                'Respond ONLY with valid JSON (no markdown): '
                '{"mood":"happy|calm|sad|energetic|focus|sleep|workout",'
                '"confidence":0.0-1.0,"note":"one short sentence"}'
            ),
            messages   = [{"role": "user", "content": text}]
        )
        import json as _json
        raw = resp.content[0].text.strip().replace("```json","").replace("```","")
        return jsonify(_json.loads(raw))
    except Exception as e:
        return jsonify({"mood": "calm", "confidence": 0.5, "error": str(e)})


@app.route("/api/ai-playlist", methods=["POST"])
def ai_playlist():
    """
    Use Claude to suggest Jamendo tag combinations for a mood + journal context.
    Body: { "mood": "sad", "journal": "breakup, miss her" }
    Returns: { "tag_sets": [...], "insight": "..." }
    """
    body    = request.get_json(silent=True) or {}
    mood    = body.get("mood", "calm")
    journal = (body.get("journal") or "").strip()[:400]

    if not ANTHROPIC_OK:
        # Return sensible defaults without AI
        defaults = {
            "happy":     ["pop+happy+upbeat", "bollywood+dance", "afrobeat+afropop"],
            "calm":      ["ambient+relax+chill", "piano+solo+peaceful", "lofi+study"],
            "sad":       ["sad+emotional+melancholy", "piano+sad+solo", "ballad+slow"],
            "energetic": ["edm+electronic+dance", "hiphop+rap+trap", "drumandbass"],
            "focus":     ["lofi+study+focus", "ambient+drone+focus", "piano+ambient"],
            "sleep":     ["sleep+lullaby+soothing", "rain+nature+sleep", "ambient+dark"],
            "workout":   ["hiphop+workout+gym", "edm+workout+power", "metal+heavy"],
        }
        return jsonify({
            "tag_sets": defaults.get(mood, ["ambient"]),
            "insight":  f"A perfect {mood} playlist for you.",
            "ai":       False,
        })

    try:
        content = f"Mood: {mood}"
        if journal:
            content += f"\nContext: {journal}"

        resp = _ant_client.messages.create(
            model      = "claude-sonnet-4-20250514",
            max_tokens = 200,
            system     = (
                "You suggest Jamendo tag search strings for a music mood. "
                "Respond ONLY with valid JSON (no markdown): "
                '{"tag_sets":["tag1+tag2","tag3+tag4","tag5+tag6"],'
                '"insight":"one warm sentence max 12 words"} '
                "Use 3-5 tag_sets. Tags are lowercase, joined by +. "
                "Consider language variety: include at least one non-English genre."
            ),
            messages   = [{"role": "user", "content": content}]
        )
        import json as _json
        raw    = resp.content[0].text.strip().replace("```json","").replace("```","")
        parsed = _json.loads(raw)
        parsed["ai"] = True
        return jsonify(parsed)
    except Exception as e:
        return jsonify({"tag_sets": ["ambient+chill"], "insight": "Music for your mood.", "ai": False, "error": str(e)})


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES – Utility
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/health")
def health():
    return jsonify({
        "status":      "ok",
        "app":         "MoodWave",
        "version":     "2.0.0",
        "ai_enabled":  ANTHROPIC_OK,
        "jamendo_id":  JAMENDO_CLIENT_ID[:4] + "****",
        "cache_size":  len(_CACHE),
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    })


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    """Admin endpoint — clear the in-memory cache."""
    secret = request.get_json(silent=True, force=True) or {}
    if secret.get("key") != os.environ.get("ADMIN_KEY", ""):
        return jsonify({"error": "forbidden"}), 403
    _CACHE.clear()
    return jsonify({"cleared": True})


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _format_track(t: dict, mood_id: str) -> dict:
    """Normalise a raw Jamendo track object into the frontend shape."""
    secs = t.get("duration", 0)
    m, s = divmod(int(secs), 60)
    dur  = f"{m}:{s:02d}" if secs else "--:--"

    musicinfo = t.get("musicinfo") or {}
    tags_obj  = musicinfo.get("tags") or {}
    genres    = tags_obj.get("genres") or []
    instrs    = tags_obj.get("instruments") or []
    genre_str = ", ".join(genres[:2]) or ", ".join(instrs[:2]) or "Music"

    MOOD_EMOJI = {
        "happy":"😄","calm":"😌","sad":"😢","energetic":"⚡",
        "focus":"🎯","sleep":"🌙","workout":"💪",
    }

    return {
        "id":        f"{mood_id}-j-{t.get('id','')}",
        "jamendoId": t.get("id"),
        "n":         t.get("name", "Unknown"),
        "a":         t.get("artist_name", "Unknown Artist"),
        "d":         dur,
        "i":         MOOD_EMOJI.get(mood_id, "🎵"),
        "g":         genre_str,
        "url":       t.get("audio", ""),
        "art":       t.get("album_image") or t.get("image") or "",
        "albumName": t.get("album_name", ""),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    print(f"""
╔══════════════════════════════════════╗
║   🎵  MoodWave  v2.0  starting…     ║
║   http://localhost:{port:<5}              ║
║   AI enabled : {str(ANTHROPIC_OK):<5}              ║
╚══════════════════════════════════════╝""")
    app.run(debug=debug, host="0.0.0.0", port=port)
