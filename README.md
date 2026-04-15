# NicheScope

**Creator Intelligence Platform** — content gaps, competitor radar, forward-looking insights, and performance analysis for YouTube creators.

> *"What should I create next, based on data?"* — answered with evidence, not AI opinions.

## What It Does

### Core Intelligence
- **Content Gap Detection** — finds topics your audience wants but nobody in your niche is covering well
- **Competitor Radar** — tracks what your competitors are posting, what's going viral, and what they're covering that you're not
- **Performance Anomalies** — alerts you when your videos are over/underperforming vs your baseline
- **Daily Briefings** — Telegram push notification every morning with your top opportunities

### Forward-Looking Features (no competitor does these)

- **Comment Demand Mining** — extracts literal viewer requests ("can you make a video about X?") from competitor video comments. These are higher-signal than any keyword tool because they're unprompted requests from real viewers in your niche.

- **Seasonal Content Calendar** — predicts when topics will spike based on 12+ months of historical view patterns. Tells you to publish 2 weeks before each seasonal peak to ride the wave.

- **Collaboration Graph** — maps existing collabs across your niche and finds optimal collab partners: creators with high topic relevance but low audience overlap, maximizing exposure to new viewers.

- **Format Intelligence** — discovers which video format (tutorial, vlog, listicle, review, challenge) performs best for each topic. Answers: "For meal prep, 12-min tutorials get 2.4x more views than vlogs."

- **Title Performance Predictor** — pre-publish A/B testing. Scores title candidates against niche-specific historical patterns before you publish. Unlike TubeBuddy's post-publish A/B test, this predicts winners up front.

## Quick Start

### 1. Prerequisites

- Python 3.12+
- PostgreSQL 16
- Redis 7
- YouTube Data API key ([Get one here](https://console.cloud.google.com/apis/library/youtube.googleapis.com))
- Telegram Bot token ([Create one via @BotFather](https://t.me/BotFather))

### 2. Setup

```bash
# Clone
git clone https://github.com/yourusername/nichescope.git
cd nichescope

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run with Docker
docker compose up -d

# OR run locally
pip install -e ".[dev]"
python scripts/seed_demo.py    # optional: load demo data
uvicorn nichescope.main:app --reload
```

### 3. Connect Telegram

1. Open Telegram, find your bot
2. Send `/start`
3. Follow the onboarding: enter your channel, name your niche, add competitors
4. Get your first content gap analysis in minutes

### 4. Install Chrome Extension

1. Open `chrome://extensions`
2. Enable "Developer mode"
3. Click "Load unpacked"
4. Select `nichescope/chrome_extension/`
5. Click the NicheScope icon, enter your API key
6. Open YouTube Studio — tabbed sidebar appears with Gaps, Demands, Calendar, and Formats

## Architecture

```
Telegram Bot ←→ FastAPI ←→ PostgreSQL
                  ↑
Chrome Extension ←┘
                  ↑
         Background Jobs:
         ├── RSS Poller (every 15 min, zero API quota)
         ├── Video Enricher (hourly, minimal API quota)
         ├── Gap Computer (daily, clusters + scores)
         ├── Brief Sender (hourly, pushes to Telegram)
         └── Anomaly Detector (hourly, viral/flop alerts)
```

## API

### Core Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/register` | — | Create account, get API key |
| POST | `/api/channels/niches` | API key | Create a niche |
| POST | `/api/channels` | API key | Add competitor channel |
| GET | `/api/gaps?niche_id=1` | API key | Get content gap scores |
| GET | `/api/report/{channel_id}` | — | Public channel report |
| GET | `/health` | — | Health check |

### Forward-Looking Intelligence Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/insights/demands?niche_id=1` | API key | Audience demand signals from comments |
| GET | `/api/insights/calendar?niche_id=1` | API key | Seasonal content calendar |
| GET | `/api/insights/collabs?niche_id=1` | API key | Collaboration opportunities |
| GET | `/api/insights/formats?niche_id=1` | API key | Format intelligence per topic |
| POST | `/api/insights/title-score` | API key | Pre-publish title scoring |

#### Title Score Request Body
```json
{
  "niche_id": 1,
  "titles": [
    "5 Mistakes Every Beginner Makes",
    "How to Avoid Common Beginner Mistakes",
    "Beginner? Don't Make These Mistakes!"
  ]
}
```

## Telegram Commands

### Core Commands

| Command | Description |
|---------|-------------|
| `/start` | Onboarding flow |
| `/brief` | Daily briefing (gaps + competitor alerts) |
| `/gaps` | Top 5 content gap opportunities |
| `/rival @handle` | Competitor deep-dive |
| `/trending` | Trending topics in your niche |

### Forward-Looking Intelligence Commands

| Command | Description |
|---------|-------------|
| `/demands` | Mine audience requests from competitor comments |
| `/calendar` | Seasonal content calendar with publish windows |
| `/collabs` | Find optimal collab partners (low overlap, high reach) |
| `/formats` | Best video format per topic (tutorial vs vlog vs listicle) |
| `/titlescore` | Score title candidates before publishing |

#### Title Scorer Usage
```
/titlescore
5 Mistakes Every Beginner Makes
How to Avoid Common Beginner Mistakes
Beginner? Don't Make These Mistakes!
```
Scores each title against your niche's historical patterns and ranks them.

## How Content Gap Detection Works

1. **Ingest** — Pull all videos from your competitors (via YouTube API + RSS feeds)
2. **Cluster** — Group videos into topics using TF-IDF + KMeans
3. **Score** — For each topic: `gap = (demand × recency) / (supply × (your_coverage + 1))`
4. **Rank** — Higher score = bigger opportunity (high demand, low supply, you haven't covered it)

## How Forward-Looking Features Work

### Comment Demand Mining
1. Pull top comments from high-performing competitor videos
2. Extract request patterns with 8 regex classifiers ("can you make...", "please do...", "video idea:")
3. Filter spam/noise with noise patterns
4. Cluster requests by keyword overlap
5. Rank by `strength = request_count × (1 + avg_likes)`

### Seasonal Content Calendar
1. Analyze view velocity of each topic cluster by month (12+ months)
2. Compute monthly performance index vs annual average
3. Detect seasonality when peak/trough spread > 1.5x
4. Recommend publishing 2 weeks before historical peak
5. Classify urgency: 🔴 now / 🟡 upcoming / 🟢 plan ahead

### Collaboration Graph
1. Detect existing collabs from title/description patterns ("feat.", "collab with", @mentions)
2. Map collaboration graph across the niche
3. Estimate audience overlap from subscriber ratios + topic similarity
4. Compute `potential_reach = subscribers × (1 - overlap_factor)`
5. Rank by potential new viewer exposure

### Format Intelligence
1. Classify videos by format (tutorial/listicle/review/challenge/vlog/reaction) via regex
2. Classify by duration bucket (short/medium/long/extra_long)
3. Cross-reference format × topic to find optimal combinations
4. Report multiplier (best format views / worst format views)

### Title Predictor
1. Extract 10 features per title (has_number, has_question, has_how_to, has_listicle, etc.)
2. Build niche-specific model from historical correlation with views_per_day
3. Score new titles 0-100 against niche patterns
4. Report strengths, weaknesses, and improvement suggestions

## YouTube API Quota

NicheScope is designed to operate within the free 10,000 units/day quota:

- RSS feeds: **0 units** (free, unlimited)
- Video enrichment: **~1 unit** per batch of 50 videos
- Channel stats: **1 unit** per channel
- Comment mining: **~1 unit** per 20 comments (commentThreads.list)

Steady-state: ~11 units/user/day → supports ~900 active users on free quota.
Comment mining adds ~5 units per demand analysis run (budget accordingly).

## License

MIT
