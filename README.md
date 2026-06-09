# 🎵 MoodWave v2.0

Mood-based music player backed by **Jamendo** (600 000+ free, full-length, Creative Commons songs). All music requests are proxied server-side through Flask — no API keys exposed in the browser, built-in caching, optional AI mood detection.

---

## Quick start

```bash
# 1. Clone / place these files in one folder:
#    app.py  moodmusic.html  requirements.txt  .env

# 2. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — set your JAMENDO_CLIENT_ID and optionally ANTHROPIC_API_KEY

# 5. Run
python app.py
# → open http://localhost:5000
```

---

## File layout

```
moodwave/
├── app.py              ← Flask backend (this file)
├── moodmusic.html      ← Frontend (served by Flask at /)
├── requirements.txt    ← Python dependencies
├── .env.example        ← Copy to .env and fill in
└── README.md
```

---

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serves `moodmusic.html` |
| GET | `/api/tracks?tags=pop+happy&limit=15&offset=0` | Proxy Jamendo tag search (cached) |
| GET | `/api/search?q=rahman&limit=20` | Full-text track search (cached) |
| GET | `/api/artist-tracks?artist=name&limit=10` | Tracks by artist name (cached) |
| POST | `/api/mood-playlist` | Batch mood playlist builder |
| POST | `/api/analyze-mood` | AI journal → mood detection (needs `ANTHROPIC_API_KEY`) |
| POST | `/api/ai-playlist` | AI-suggested tag combos (needs `ANTHROPIC_API_KEY`) |
| GET | `/api/health` | Status, cache size, AI toggle |
| POST | `/api/cache/clear` | Admin: flush cache (`{"key":"ADMIN_KEY"}`) |

---

## Production deployment

```bash
# Gunicorn (recommended)
gunicorn app:app --workers 4 --bind 0.0.0.0:5000

# With Nginx in front (recommended for HTTPS + static files)
# Point Nginx root to this folder, proxy /api/* to gunicorn
```

---

## Getting your own Jamendo client ID (free)

1. Go to https://developer.jamendo.com/
2. Register → Create application → Copy **Client ID**
3. Set `JAMENDO_CLIENT_ID=your_id` in `.env`

The default sandbox ID (`b6747d04`) works but has lower rate limits.

---

## Language & mood coverage

Each mood has 10 tag categories covering:
🌍 World · 🇮🇳 Bollywood / Tamil / Telugu / Bhangra / Ghazal
🇰🇷 K-Pop · 🇯🇵 J-Pop · 🇪🇸 Latin · 🇧🇷 Samba · 🌍 Afrobeat
🇫🇷 French · ☮️ Ambient · 🎷 Jazz · 🎸 Rock · ⚡ EDM · and more

All songs stream in full — no 30-second previews.
