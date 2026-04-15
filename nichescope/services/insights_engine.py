"""Conversational insights engine — answers questions about competitors,
revenue, traction, strategy, content, monetization, etc.

Responses are designed for Telegram readability:
  - Short paragraphs, not data dumps
  - Comparative language ("2x more than average") instead of raw numbers
  - Every section ends with an actionable takeaway
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import (
    Channel, GapScore, Niche, TopicCluster, User, Video, async_session,
)
from nichescope.models.channel import niche_channels

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
#  SECURITY GUARDRAILS
# ──────────────────────────────────────────────────────────────────────

_MAX_INPUT_LEN = 500
_rate_window: dict[int, list[float]] = {}
_RATE_LIMIT = 15
_RATE_WINDOW_SECS = 60

_BLOCKED_PATTERNS = [
    r"(__|import\s|exec\s*\(|eval\s*\(|os\.|sys\.|subprocess|__builtins__)",
    r"(rm\s+-rf|sudo|chmod|chown|/etc/|/bin/|/usr/|/var/)",
    r"(DROP\s+TABLE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|ALTER\s+TABLE)",
    r"(SELECT\s+\*\s+FROM|UNION\s+SELECT|;\s*DROP|OR\s+1\s*=\s*1)",
    r"(<script|javascript:|onerror=|onclick=|onload=)",
    r"(\.\./|\.\.\\|/tmp/|/home/|/root/|/proc/)",
    r"(api[_\s]?key|secret[_\s]?key|password|token|\.env|credentials)",
    r"(show.*(env|config|secret|database|schema|table|server|infra))",
    r"(dump.*database|export.*data|download.*data|steal|exfiltrate)",
    r"(hack|exploit|crack|brute.?force|ddos|phish|malware|ransomware)",
    r"(copyright.?infring|pirat|torrent|steal.*content|scrape.*email)",
    r"(fake.*view|view.?bot|sub.?bot|buy.*subscriber|buy.*view|inflate)",
    r"(spam|mass.?message|bulk.?email|unsolicited)",
    r"(dox|doxx|swat|stalk|harass)",
    r"(child|csam|underage|minor.*exploit)",
    r"(weapon|bomb|drug|narcotic|launder|fraud|scam\b.*how)",
    r"(hate\s+speech|racial\s+slur|discriminat.*how\s+to)",
]

_BLOCKED_RE = [re.compile(p, re.IGNORECASE) for p in _BLOCKED_PATTERNS]

_REFUSAL_MSGS = [
    "🚫 I can only help with YouTube content strategy. That's outside my scope.",
    "⛔ Sorry, I'm designed for YouTube niche analysis only.",
    "🔒 Can't help with that — try asking about competitors, content gaps, or revenue!",
]


def _sanitize_input(text: str) -> str | None:
    if not text or not text.strip():
        return None
    text = text.strip()
    if len(text) > _MAX_INPUT_LEN:
        text = text[:_MAX_INPUT_LEN]
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    for pattern in _BLOCKED_RE:
        if pattern.search(text):
            return None
    return text


def _check_rate_limit(chat_id: int) -> bool:
    now = time.time()
    if chat_id not in _rate_window:
        _rate_window[chat_id] = []
    _rate_window[chat_id] = [t for t in _rate_window[chat_id] if now - t < _RATE_WINDOW_SECS]
    if len(_rate_window[chat_id]) >= _RATE_LIMIT:
        return False
    _rate_window[chat_id].append(now)
    return True


# ──────────────────────────────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────────────────────────────

_CPM_RATES = {
    "finance": (12, 25), "investing": (12, 25), "insurance": (15, 30),
    "real estate": (10, 20), "business": (8, 18), "marketing": (8, 16),
    "tech": (5, 12), "software": (6, 14), "programming": (5, 12),
    "education": (4, 10), "tutorial": (4, 10), "interview": (4, 10),
    "mock interview": (5, 12), "career": (5, 12), "job": (5, 12),
    "health": (6, 14), "fitness": (4, 10), "cooking": (3, 8),
    "food": (3, 8), "gaming": (2, 5), "entertainment": (2, 6),
    "vlog": (2, 5), "travel": (3, 8), "beauty": (3, 8),
    "fashion": (3, 8), "music": (1, 4), "comedy": (2, 5),
    "default": (3, 8),
}


def _get_cpm(niche_name: str) -> tuple[float, float]:
    lower = niche_name.lower()
    for key, rates in _CPM_RATES.items():
        if key in lower:
            return rates
    return _CPM_RATES["default"]


def _fmt(n: int | float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,.0f}"


def _compare(value: float, benchmark: float) -> str:
    """Human-readable comparison: '2.3x more' or '40% less'."""
    if benchmark <= 0:
        return ""
    ratio = value / benchmark
    if ratio >= 1.5:
        return f"{ratio:.1f}x more than average"
    elif ratio >= 1.1:
        return f"{(ratio - 1) * 100:.0f}% above average"
    elif ratio >= 0.9:
        return "about average"
    else:
        return f"{(1 - ratio) * 100:.0f}% below average"


def _opportunity_label(score: float) -> str:
    if score >= 75:
        return "🟢 Easy win"
    elif score >= 50:
        return "🟡 Good opportunity"
    elif score >= 30:
        return "🟠 Moderate competition"
    else:
        return "🔴 Crowded"


def _engagement_grade(eng_pct: float) -> str:
    if eng_pct >= 8:
        return "🟢 Exceptional"
    elif eng_pct >= 5:
        return "🟢 Strong"
    elif eng_pct >= 3:
        return "🟡 Good"
    elif eng_pct >= 1.5:
        return "🟠 Average"
    else:
        return "🔴 Low"


async def _get_user_context(session: AsyncSession, chat_id: int):
    user = (await session.execute(
        select(User).where(User.telegram_chat_id == chat_id)
    )).scalar_one_or_none()
    if not user:
        return None, None, [], []

    niche = (await session.execute(
        select(Niche).where(Niche.user_id == user.id).limit(1)
    )).scalar_one_or_none()
    if not niche:
        return user, None, [], []

    ch_ids = [r[0] for r in (await session.execute(
        select(niche_channels.c.channel_id).where(niche_channels.c.niche_id == niche.id)
    )).all()]
    channels = []
    for cid in ch_ids:
        ch = await session.get(Channel, cid)
        if ch:
            channels.append(ch)

    if ch_ids:
        vids_result = await session.execute(
            select(Video).where(Video.channel_id.in_(ch_ids))
        )
        videos = list(vids_result.scalars().all())
    else:
        videos = []

    return user, niche, channels, videos


# ──────────────────────────────────────────────────────────────────────
#  ANALYSIS FUNCTIONS (redesigned for readability)
# ──────────────────────────────────────────────────────────────────────

async def _competitor_strategy(session: AsyncSession, channel: Channel, videos: list[Video]) -> str:
    ch_vids = [v for v in videos if v.channel_id == channel.id]
    if not ch_vids:
        return f"No videos stored for *{channel.title}* yet."

    total_views = sum(v.view_count for v in ch_vids)
    avg_views = total_views / len(ch_vids)
    avg_likes = sum(v.like_count for v in ch_vids) / len(ch_vids)
    total_engagement = sum(v.like_count + v.comment_count for v in ch_vids)
    eng_rate = total_engagement / max(total_views, 1) * 100

    sorted_vids = sorted(ch_vids, key=lambda v: v.published_at or datetime.min, reverse=True)
    vids_per_week = 0
    if len(sorted_vids) >= 2 and sorted_vids[0].published_at and sorted_vids[-1].published_at:
        days = max((sorted_vids[0].published_at.replace(tzinfo=None) -
                    sorted_vids[-1].published_at.replace(tzinfo=None)).days, 1)
        vids_per_week = len(sorted_vids) / (days / 7)

    top3 = sorted(ch_vids, key=lambda v: v.view_count, reverse=True)[:3]

    name = channel.handle or channel.title

    r = f"*{name}* — Competitor Breakdown\n\n"

    # Quick stats line
    r += (
        f"👥 {_fmt(channel.subscriber_count)} subs · "
        f"📈 {_fmt(avg_views)} avg views · "
        f"{_engagement_grade(eng_rate)} engagement ({eng_rate:.1f}%)\n\n"
    )

    # What they post
    if vids_per_week >= 3:
        r += f"📅 *Posting:* {vids_per_week:.0f}x/week — high volume strategy, competing on quantity\n\n"
    elif vids_per_week >= 1:
        r += f"📅 *Posting:* {vids_per_week:.1f}x/week — consistent schedule\n\n"
    elif vids_per_week > 0:
        r += f"📅 *Posting:* {vids_per_week:.1f}x/week — quality over quantity approach\n\n"
    else:
        r += f"📅 *Posting:* Inactive or very selective\n\n"

    # Best performing content
    r += "*Their best content:*\n"
    for i, v in enumerate(top3, 1):
        r += f"  {i}. _{v.title[:55]}_ — {_fmt(v.view_count)} views\n"

    # Topic breakdown
    cluster_map = defaultdict(list)
    for v in ch_vids:
        if v.topic_cluster_id:
            cluster_map[v.topic_cluster_id].append(v)
    if cluster_map:
        top_topics = sorted(cluster_map.items(), key=lambda x: -len(x[1]))[:4]
        r += "\n*What topics they cover:*\n"
        for cid, cvids in top_topics:
            tc = await session.get(TopicCluster, cid)
            if tc:
                cavg = sum(v.view_count for v in cvids) / len(cvids)
                r += f"  • {tc.label} ({len(cvids)} vids, {_fmt(cavg)} avg views)\n"

    # Actionable takeaway
    r += "\n*💡 What you can learn:*\n"
    if eng_rate >= 5:
        r += f"  • Their audience is highly engaged — study their thumbnails and hooks\n"
    if top3:
        r += f"  • Their viral hit got {_fmt(top3[0].view_count)} views — make your version with a unique angle\n"
    if vids_per_week >= 2:
        r += f"  • They post frequently — you'll need consistent output to compete"
    else:
        r += f"  • They don't post often — you can win by being more consistent"

    return r


async def _traction_comparison(session: AsyncSession, niche: Niche,
                                channels: list[Channel], videos: list[Video]) -> str:
    channel_stats = []
    for ch in channels:
        ch_vids = [v for v in videos if v.channel_id == ch.id]
        if not ch_vids:
            continue
        total_v = sum(v.view_count for v in ch_vids)
        avg_v = total_v / len(ch_vids)
        eng = sum(v.like_count + v.comment_count for v in ch_vids) / max(total_v, 1) * 100
        best = max(ch_vids, key=lambda v: v.view_count)
        channel_stats.append({
            "ch": ch, "vids": ch_vids, "total": total_v,
            "avg": avg_v, "eng": eng, "best": best, "count": len(ch_vids)
        })

    if not channel_stats:
        return "No video data yet — try again shortly."

    channel_stats.sort(key=lambda x: x["avg"], reverse=True)
    overall_avg = sum(c["avg"] for c in channel_stats) / len(channel_stats)

    r = f"*{niche.name} — Channel Comparison*\n\n"

    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    for i, cs in enumerate(channel_stats[:5]):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        name = cs['ch'].handle or cs['ch'].title
        vs_avg = _compare(cs['avg'], overall_avg)

        r += (
            f"{medal} *{name}*\n"
            f"    {_fmt(cs['avg'])} avg views · "
            f"{_engagement_grade(cs['eng'])} engagement · "
            f"{_fmt(cs['ch'].subscriber_count)} subs\n"
        )
        if vs_avg and vs_avg != "about average":
            r += f"    ↳ {vs_avg}\n"
        r += "\n"

    # Why the leader wins
    if len(channel_stats) >= 2:
        top = channel_stats[0]
        r += f"*💡 Why {top['ch'].handle or top['ch'].title} leads:*\n"
        reasons = []
        if top["avg"] > overall_avg * 1.3:
            reasons.append(f"Gets {top['avg']/overall_avg:.1f}x the average views per video")
        if top["eng"] > 5:
            reasons.append(f"High engagement ({top['eng']:.1f}%) means YouTube promotes their content")
        if top["count"] > channel_stats[-1]["count"]:
            reasons.append(f"More videos ({top['count']}) = more chances to be discovered")
        if not reasons:
            reasons.append("Consistent content in high-demand topics")
        for reason in reasons:
            r += f"  • {reason}\n"

        r += f"\n*Your move:* Target their best-performing topics but add your unique angle."

    return r


async def _revenue_estimate(session: AsyncSession, niche: Niche, videos: list[Video]) -> str:
    if not videos:
        return "No video data yet — try again in a moment."

    cpm_low, cpm_high = _get_cpm(niche.name)
    avg_views = sum(v.view_count for v in videos) / len(videos)
    sorted_views = sorted(v.view_count for v in videos)
    median_views = sorted_views[len(sorted_views) // 2]

    r = f"*💰 Revenue Potential — {niche.name}*\n\n"

    # Simple, scannable revenue tiers
    r += "*If you post 1 video/week (4/month):*\n\n"

    scenarios = [
        ("Starting out", median_views * 0.5, "your first few months"),
        ("Getting traction", median_views, "matching the median competitor"),
        ("Doing well", avg_views, "matching the average"),
        ("Crushing it", avg_views * 2, "top performer level"),
    ]

    for label, views, desc in scenarios:
        mo_low = (views * 4 / 1000) * cpm_low
        mo_high = (views * 4 / 1000) * cpm_high
        if mo_high < 10:
            revenue_str = f"< $10/mo"
        else:
            revenue_str = f"${mo_low:,.0f}–${mo_high:,.0f}/mo"
        r += f"  📊 *{label}* ({_fmt(views)} views/vid)\n"
        r += f"      AdSense: {revenue_str} — _{desc}_\n\n"

    # Beyond AdSense
    r += (
        "*Beyond AdSense (where real money is):*\n"
        f"  💼 Sponsorships — $500–$5,000/video once you hit 10K subs\n"
        f"  🔗 Affiliate links — $200–$2,000/mo in product commissions\n"
        f"  📦 Digital products — $1K–$10K/mo selling courses/guides\n\n"
        f"_Most successful creators earn 3–5x more from sponsorships "
        f"and products than from AdSense alone._"
    )

    return r


async def _earning_opportunities(session: AsyncSession, niche: Niche,
                                  channels: list[Channel], videos: list[Video]) -> str:
    cpm_low, cpm_high = _get_cpm(niche.name)
    avg_views = sum(v.view_count for v in videos) / max(len(videos), 1)
    avg_subs = sum(c.subscriber_count for c in channels) / max(len(channels), 1) if channels else 0
    monthly_ad = (avg_views * 4 / 1000) * ((cpm_low + cpm_high) / 2)

    r = f"*💎 How to Earn in {niche.name}*\n\n"

    r += (
        f"*1. YouTube AdSense* — easiest to start\n"
        f"   ~${monthly_ad:,.0f}/mo at average performance (4 vids/mo)\n"
        f"   ↳ Requires 1K subs + 4K watch hours to enable\n\n"

        f"*2. Sponsorships* — biggest earner for most creators\n"
        f"   $500–$5K per sponsored video (depends on niche + audience)\n"
        f"   ↳ Start pitching brands after 10+ quality videos\n\n"

        f"*3. Affiliate Marketing* — passive income per video\n"
        f"   Link products in every description + pinned comment\n"
        f"   ↳ Amazon Associates, ShareASale, or niche-specific programs\n\n"

        f"*4. Digital Products* — highest margins\n"
        f"   Courses, templates, guides ($19–$197 each)\n"
        f"   ↳ YouTube = free value → course upsell funnel\n\n"

        f"*5. Community* — recurring revenue\n"
        f"   YouTube memberships or Patreon ($5–$25/mo per member)\n"
        f"   ↳ Exclusive content, early access, community\n\n"
    )

    # Niche-specific tip
    lower = niche.name.lower()
    if any(k in lower for k in ["business", "finance", "tech", "marketing", "interview", "career", "consult"]):
        r += (
            f"*6. Consulting* — leverage your expertise\n"
            f"   $100–$500/hr — YouTube builds authority → clients come to you\n\n"
        )

    r += (
        f"*⚡ Priority order:* Get to 1K subs → enable AdSense → "
        f"start affiliate links → pitch sponsors → launch a digital product"
    )

    return r


async def _top_videos(session: AsyncSession, niche: Niche, videos: list[Video]) -> str:
    if not videos:
        return "No videos in database yet."
    top = sorted(videos, key=lambda v: v.view_count, reverse=True)[:8]
    avg_views = sum(v.view_count for v in videos) / len(videos)

    r = f"*🏆 Best Performing Videos — {niche.name}*\n\n"
    for i, v in enumerate(top, 1):
        ch = await session.get(Channel, v.channel_id)
        name = ch.handle or ch.title if ch else "?"
        vs_avg = v.view_count / avg_views
        if vs_avg >= 3:
            tag = "🔥 viral"
        elif vs_avg >= 1.5:
            tag = "⬆️ above avg"
        else:
            tag = ""
        r += (
            f"  {i}. *{v.title[:50]}*\n"
            f"     {_fmt(v.view_count)} views · {name}"
        )
        if tag:
            r += f" · {tag}"
        r += "\n\n"

    r += f"_Average in this niche: {_fmt(avg_views)} views. Study the viral ones — what made them pop?_"
    return r


async def _posting_frequency(channels: list[Channel], videos: list[Video]) -> str:
    lines = []
    rates = []
    for ch in channels:
        ch_vids = sorted(
            [v for v in videos if v.channel_id == ch.id and v.published_at],
            key=lambda v: v.published_at, reverse=True,
        )
        if len(ch_vids) >= 2:
            days = max((ch_vids[0].published_at.replace(tzinfo=None) -
                        ch_vids[-1].published_at.replace(tzinfo=None)).days, 1)
            pw = len(ch_vids) / (days / 7)
            rates.append(pw)
            name = ch.handle or ch.title
            lines.append(f"  • *{name}*: {pw:.1f} videos/week")

    if not lines:
        return "Not enough data to calculate posting frequency yet."

    avg_rate = sum(rates) / len(rates)
    r = f"*📅 How Often Competitors Post*\n\n"
    r += "\n".join(lines)
    r += f"\n\n  Average: {avg_rate:.1f}/week across all channels\n"

    # Recommendation
    r += f"\n*💡 Recommendation:*\n"
    if avg_rate >= 3:
        r += f"  This niche moves fast. Aim for 2–3 videos/week to stay visible."
    elif avg_rate >= 1:
        r += f"  1–2 videos/week is the sweet spot here — quality + consistency."
    else:
        r += f"  Competitors post infrequently — even 1 video/week puts you ahead."

    return r


async def _engagement_analysis(channels: list[Channel], videos: list[Video]) -> str:
    entries = []
    for ch in channels:
        ch_vids = [v for v in videos if v.channel_id == ch.id]
        if ch_vids:
            tv = sum(v.view_count for v in ch_vids)
            tl = sum(v.like_count for v in ch_vids)
            tc = sum(v.comment_count for v in ch_vids)
            eng = (tl + tc) / max(tv, 1) * 100
            entries.append({"ch": ch, "eng": eng, "likes": tl, "comments": tc, "views": tv})

    if not entries:
        return "No engagement data available yet."

    entries.sort(key=lambda x: x["eng"], reverse=True)
    avg_eng = sum(e["eng"] for e in entries) / len(entries)

    r = f"*💬 Engagement Breakdown*\n\n"
    for e in entries:
        name = e["ch"].handle or e["ch"].title
        grade = _engagement_grade(e["eng"])
        r += f"  • *{name}*: {e['eng']:.1f}% {grade}\n"
        r += f"    {_fmt(e['likes'])} likes · {_fmt(e['comments'])} comments\n\n"

    r += f"  Niche average: {avg_eng:.1f}%\n\n"
    r += f"*💡 What this means:*\n"
    if avg_eng >= 5:
        r += f"  This niche has a passionate audience — great for community building and monetization."
    elif avg_eng >= 2:
        r += f"  Average engagement — focus on strong hooks and calls-to-action to stand out."
    else:
        r += f"  Low engagement suggests viewers browse but don't interact — try asking questions and being more personal."

    return r


async def _content_ideas(session: AsyncSession, niche: Niche, videos: list[Video]) -> str:
    gaps_result = await session.execute(
        select(GapScore).where(GapScore.niche_id == niche.id).order_by(desc(GapScore.score)).limit(6)
    )
    gaps = list(gaps_result.scalars().all())

    if not gaps:
        return "I need to finish analyzing your niche to generate ideas. Try again in a moment!"

    r = f"*💡 Content Ideas — {niche.name}*\n\n"

    for i, g in enumerate(gaps, 1):
        tc = await session.get(TopicCluster, g.topic_cluster_id)
        if not tc:
            continue

        label = _opportunity_label(g.score)
        trend = {"up": "trending up 🔥", "stable": "steady demand", "down": "cooling off"}.get(tc.trend_direction, "steady")

        # Get example titles
        ex_result = await session.execute(
            select(Video.title).where(Video.topic_cluster_id == tc.id)
            .order_by(desc(Video.view_count)).limit(2)
        )
        examples = [r[0] for r in ex_result.all()]

        r += f"*{i}. {tc.label}* {label}\n"

        # Explain in comparative terms
        if g.score >= 75:
            r += f"   Few creators covering this but viewers want it ({_fmt(tc.avg_views)} avg views, {trend})\n"
        elif g.score >= 50:
            r += f"   Some competition but room for a fresh angle ({_fmt(tc.avg_views)} avg views, {trend})\n"
        else:
            r += f"   Popular topic, you'll need a unique hook ({_fmt(tc.avg_views)} avg views, {trend})\n"

        if examples:
            r += f"   📝 Inspo: _{examples[0][:55]}_\n"
        r += "\n"

    r += (
        f"*⚡ My pick:* Start with #1 — it has the best ratio of "
        f"viewer demand to creator competition. Make 3–4 videos "
        f"on this topic before branching out."
    )

    return r


async def _niche_overview(session: AsyncSession, niche: Niche,
                           channels: list[Channel], videos: list[Video]) -> str:
    clusters_result = await session.execute(
        select(TopicCluster).where(TopicCluster.niche_id == niche.id)
    )
    clusters = list(clusters_result.scalars().all())

    total_views = sum(v.view_count for v in videos)
    avg_views = total_views / max(len(videos), 1)

    r = f"*📊 {niche.name} — Overview*\n\n"

    # Competitors
    r += f"*Competitors ({len(channels)}):*\n"
    for ch in sorted(channels, key=lambda c: c.subscriber_count, reverse=True):
        cv = len([v for v in videos if v.channel_id == ch.id])
        r += f"  • *{ch.handle or ch.title}* — {_fmt(ch.subscriber_count)} subs, {cv} videos\n"

    # Niche health
    r += f"\n*Niche Health:*\n"
    r += f"  • Average video gets {_fmt(avg_views)} views\n"
    r += f"  • {len(videos)} videos analyzed across {len(clusters)} topics\n"

    if clusters:
        trending_up = [c for c in clusters if c.trend_direction == "up"]
        trending_down = [c for c in clusters if c.trend_direction == "down"]
        if trending_up:
            r += f"  • 🔥 Growing: {', '.join(c.label for c in trending_up[:3])}\n"
        if trending_down:
            r += f"  • 📉 Declining: {', '.join(c.label for c in trending_down[:3])}\n"

    r += "\n_Ask me about revenue, content ideas, or competitor strategies!_"
    return r


# ──────────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ──────────────────────────────────────────────────────────────────────

async def answer_question(chat_id: int, question: str) -> str:
    if not _check_rate_limit(chat_id):
        return "⏳ Slow down a bit — try again in a moment."

    clean = _sanitize_input(question)
    if clean is None:
        import random
        return random.choice(_REFUSAL_MSGS)

    lower = clean.lower()

    async with async_session() as session:
        user, niche, channels, videos = await _get_user_context(session, chat_id)

        if not user:
            return (
                "👋 I don't have your account yet.\n\n"
                "Just tell me what kind of YouTube channel you're interested in "
                "and I'll set everything up!\n\n"
                "Example: _\"I want to start a mock interview channel\"_"
            )

        if not niche:
            return (
                "Tell me what topic you're interested in — like "
                "_\"mock interviews\"_ or _\"budget cooking\"_ — "
                "and I'll analyze the landscape for you!"
            )

        if not channels:
            return (
                f"Still setting up *{niche.name}* — no channels found yet.\n"
                "Try telling me the niche again to restart discovery."
            )

        if not videos:
            return (
                f"Found channels in *{niche.name}* but still fetching videos.\n"
                "Try again in a minute!"
            )

        # ── Route to analysis ──

        # Specific competitor by @handle or name
        handle_match = re.search(r"@(\w+)", clean)
        if handle_match:
            handle = handle_match.group(1)
            ch = next((c for c in channels if c.handle and c.handle.lower() == handle.lower()), None)
            if not ch:
                ch = (await session.execute(
                    select(Channel).where(Channel.handle == handle)
                )).scalar_one_or_none()
            if ch:
                return await _competitor_strategy(session, ch, videos)
            return f"@{handle} not found in tracked channels."

        # Revenue / money
        if re.search(r"(revenue|earn|income|money|monetiz|profit|how much|make money|salary|pay)", lower):
            if re.search(r"(other|all|different|ways|types|opportunit|besides|beyond|streams|sources)", lower):
                return await _earning_opportunities(session, niche, channels, videos)
            return await _revenue_estimate(session, niche, videos)

        # Competitor strategy
        if re.search(r"(what|why|how).{0,20}(competitor|rival|they|channel).{0,20}(do|doing|strategy|about|work)", lower):
            if len(channels) == 1:
                return await _competitor_strategy(session, channels[0], videos)
            return await _traction_comparison(session, niche, channels, videos)

        # Traction / why more views
        if re.search(r"(traction|why.{0,10}more|more views|outperform|winning|ahead|behind|losing|growth|growing)", lower):
            return await _traction_comparison(session, niche, channels, videos)

        # Compare
        if re.search(r"(compare|comparison|versus|vs\b|differ|benchmark|rank)", lower):
            return await _traction_comparison(session, niche, channels, videos)

        # Content ideas
        if re.search(r"(content idea|what.{0,10}(create|make|post|upload)|suggest|inspir|idea|next video)", lower):
            return await _content_ideas(session, niche, videos)

        # Top videos
        if re.search(r"(best|top|most viewed|most popular|viral|highest|perform)", lower):
            return await _top_videos(session, niche, videos)

        # Posting frequency
        if re.search(r"(how often|frequen|upload schedule|posting|consistent|how many.{0,5}(video|upload|post))", lower):
            return await _posting_frequency(channels, videos)

        # Engagement
        if re.search(r"(engagement|like.{0,5}rate|comment.{0,5}rate|interact|audience.{0,5}(react|respond))", lower):
            return await _engagement_analysis(channels, videos)

        # Gaps / opportunities
        if re.search(r"(gap|opportunit|miss|untapped|underserved|white.?space)", lower):
            return await _content_ideas(session, niche, videos)

        # Overview
        if re.search(r"(overview|summary|status|dashboard|snapshot|how.{0,5}(am i|are we)|report)", lower):
            return await _niche_overview(session, niche, channels, videos)

        # Trends
        if re.search(r"(trend|rising|hot|blow.?up|taking off|going viral)", lower):
            clusters = list((await session.execute(
                select(TopicCluster).where(TopicCluster.niche_id == niche.id)
                .order_by(desc(TopicCluster.avg_views_30d))
            )).scalars().all())
            if not clusters:
                return "No trend data yet — try again in a moment!"
            r = f"*📈 What's Trending in {niche.name}*\n\n"
            for tc in clusters[:8]:
                trend = {"up": "🔥 Rising", "stable": "➡️ Steady", "down": "📉 Declining"}.get(tc.trend_direction, "➡️ Steady")
                r += f"  • *{tc.label}* — {_fmt(tc.avg_views)} avg views · {trend}\n"
            r += "\n_Focus on 🔥 Rising topics for maximum early traction._"
            return r

        # Strategy / advice
        if re.search(r"(strategy|plan|should i|what to|where.{0,5}start|how to grow|next step|advice|recommend|tip)", lower):
            ideas = await _content_ideas(session, niche, videos)
            return ideas + "\n\n_Want a deeper competitor breakdown? Ask \"what is [channel] doing?\"_"

        # Match channel name
        for ch in channels:
            if ch.title and ch.title.lower() in lower:
                return await _competitor_strategy(session, ch, videos)

        # Fallback
        avg_v = sum(v.view_count for v in videos) / max(len(videos), 1)
        return (
            f"*{niche.name}* — {len(channels)} channels, {_fmt(avg_v)} avg views/video\n\n"
            f"Here's what I can tell you:\n"
            f"  • _\"How much can I earn?\"_\n"
            f"  • _\"What content should I create?\"_\n"
            f"  • _\"Why does the top channel get more views?\"_\n"
            f"  • _\"Show me the best performing videos\"_\n"
            f"  • _\"What strategy should I follow?\"_\n\n"
            f"_Just ask naturally — I'll figure it out!_"
        )
