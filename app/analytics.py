"""Read-only reports of server-recorded page views (UTC storage, Brazil dates)."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from .models import db, PageView, Post, AnalyticsSession

REPORT_TZ = ZoneInfo("America/Sao_Paulo")


def pageview_report(start_day=None, end_day=None):
    today = datetime.now(REPORT_TZ).date()
    end_day = end_day or today
    if start_day is None:
        end_day = max(date(2000, 1, 30), min(end_day, today))
    start_day = start_day or (end_day - timedelta(days=29))
    start_day, end_day = sorted((start_day, end_day))
    # Bound user-supplied ranges and avoid date arithmetic overflows.
    start_day = max(date(2000, 1, 1), min(start_day, today))
    end_day = max(start_day, min(end_day, today))
    if (end_day - start_day).days > 3660:
        start_day = end_day - timedelta(days=3660)

    def utc_midnight(day):
        return datetime.combine(day, time.min, REPORT_TZ).astimezone(timezone.utc).replace(tzinfo=None)

    start = utc_midnight(start_day)
    end = utc_midnight(end_day + timedelta(days=1))
    window_days = (end_day - start_day).days + 1
    previous_start = utc_midnight(start_day - timedelta(days=window_days))
    current = PageView.query.filter(PageView.created_at >= start, PageView.created_at < end)
    total = current.count()
    previous_total = PageView.query.filter(PageView.created_at >= previous_start, PageView.created_at < start).count()
    delta = round((total - previous_total) / previous_total * 100, 1) if previous_total else None

    # Group on the server, then convert UTC hours into local calendar days.
    # This avoids loading individual visits and also handles historical DST.
    if db.engine.dialect.name == "sqlite":
        hour = func.strftime("%Y-%m-%d %H:00:00", PageView.created_at)
    else:
        hour = func.date_trunc("hour", PageView.created_at)
    hourly = current.with_entities(hour.label("hour"), func.count(PageView.id)).group_by(hour).all()
    counts = {}
    for stamp, count in hourly:
        if isinstance(stamp, str):
            stamp = datetime.fromisoformat(stamp)
        local_day = stamp.replace(tzinfo=timezone.utc).astimezone(REPORT_TZ).date()
        counts[local_day] = counts.get(local_day, 0) + count
    # Session-based metrics are a second, richer source. They were introduced later
    # than PageView, so the report explicitly flags unavailable/partial history.
    first_session_at = db.session.query(func.min(AnalyticsSession.created_at)).scalar()
    session_first_day = (first_session_at.replace(tzinfo=timezone.utc).astimezone(REPORT_TZ).date()
                         if first_session_at else None)
    sessions_available = bool(session_first_day and end_day >= session_first_day)
    session_data_partial = bool(sessions_available and start_day < session_first_day)

    session_counts = {}
    session_users = {}
    session_duration = {}
    session_pageviews = {}
    session_bounces = {}
    sessions = users = new_users = avg_duration = 0
    pages_per_session = bounce_rate = 0.0
    top_referrers = []
    devices = {"Desktop": 0, "Mobile": 0, "Tablet": 0, "Outro": 0}

    if sessions_available:
        session_q = AnalyticsSession.query.filter(
            AnalyticsSession.created_at >= start,
            AnalyticsSession.created_at < end,
        )
        session_rows = session_q.all()
        sessions = len(session_rows)
        users = len({row.visitor_id for row in session_rows if row.visitor_id})
        new_users = len({row.visitor_id for row in session_rows if row.is_new_user and row.visitor_id})
        avg_duration = round(sum((row.duration_seconds or 0) for row in session_rows) / sessions) if sessions else 0
        total_session_pageviews = sum((row.pageviews or 0) for row in session_rows)
        pages_per_session = round(total_session_pageviews / sessions, 2) if sessions else 0.0
        bounces = sum(1 for row in session_rows if row.is_bounce)
        bounce_rate = round((bounces / sessions) * 100, 1) if sessions else 0.0

        ref_counts = {}
        for row in session_rows:
            local_day = row.created_at.replace(tzinfo=timezone.utc).astimezone(REPORT_TZ).date()
            session_counts[local_day] = session_counts.get(local_day, 0) + 1
            session_users.setdefault(local_day, set()).add(row.visitor_id)
            session_duration[local_day] = session_duration.get(local_day, 0) + (row.duration_seconds or 0)
            session_pageviews[local_day] = session_pageviews.get(local_day, 0) + (row.pageviews or 0)
            session_bounces[local_day] = session_bounces.get(local_day, 0) + (1 if row.is_bounce else 0)
            ref = (row.referrer or '').strip()
            ref_counts[ref] = ref_counts.get(ref, 0) + 1

            ua = (row.user_agent or '').lower()
            if any(token in ua for token in ('ipad', 'tablet', 'kindle')):
                devices['Tablet'] += 1
            elif any(token in ua for token in ('mobi', 'android', 'iphone', 'ipod')):
                devices['Mobile'] += 1
            elif ua:
                devices['Desktop'] += 1
            else:
                devices['Outro'] += 1
        top_referrers = sorted(ref_counts.items(), key=lambda item: (-item[1], item[0]))[:20]

    daily_series = []
    for offset in range(window_days):
        day = start_day + timedelta(days=offset)
        day_sessions = session_counts.get(day, 0)
        day_duration = session_duration.get(day, 0)
        day_spv = session_pageviews.get(day, 0)
        day_bounces = session_bounces.get(day, 0)
        daily_series.append({
            "iso": day.isoformat(),
            "label": day.strftime("%d/%m/%Y"),
            "label_short": day.strftime("%d/%m"),
            "pageviews": counts.get(day, 0),
            "sessions": day_sessions,
            "users": len(session_users.get(day, set())),
            "avg_duration": round(day_duration / day_sessions) if day_sessions else 0,
            "pages_per_session": round(day_spv / day_sessions, 2) if day_sessions else 0.0,
            "bounce_rate": round((day_bounces / day_sessions) * 100, 1) if day_sessions else 0.0,
        })

    top_pages = (current.with_entities(PageView.path, func.count(PageView.id).label("views"))
                 .group_by(PageView.path).order_by(func.count(PageView.id).desc(), PageView.path).limit(20).all())
    top_posts = (current.join(Post, PageView.post_id == Post.id)
                 .with_entities(Post.id, Post.title, Post.slug, func.count(PageView.id).label("views"))
                 .group_by(Post.id, Post.title, Post.slug)
                 .order_by(func.count(PageView.id).desc(), Post.id).limit(20).all())
    all_total, first_at = db.session.query(func.count(PageView.id), func.min(PageView.created_at)).one()
    first_day = first_at.replace(tzinfo=timezone.utc).astimezone(REPORT_TZ).date() if first_at else None
    last_24h = PageView.query.filter(PageView.created_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)).count()
    return {"start_date": start_day, "end_date": end_day, "total": total,
            "previous_total": previous_total, "delta": delta, "all_total": all_total,
            "last_24h": last_24h, "first_day": first_day,
            "distinct_pages": current.with_entities(func.count(func.distinct(PageView.path))).scalar() or 0,
            "daily_series": daily_series, "top_pages": top_pages, "top_posts": top_posts,
            "sessions_available": sessions_available, "session_data_partial": session_data_partial,
            "session_first_day": session_first_day, "sessions": sessions, "users": users,
            "new_users": new_users, "avg_duration": avg_duration,
            "pages_per_session": pages_per_session, "bounce_rate": bounce_rate,
            "top_referrers": top_referrers, "devices": devices}
