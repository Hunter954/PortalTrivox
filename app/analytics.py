"""Read-only reports of server-recorded page views (UTC storage, Brazil dates)."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, case, distinct

from .models import db, PageView, Post, AnalyticsSession

REPORT_TZ = ZoneInfo("America/Sao_Paulo")

# Fallback model used only when historical session tracking does not exist.
# These values are deliberately exposed in the report so estimated data is
# never confused with measured AnalyticsSession data.
EST_PAGES_PER_SESSION = 1.62
EST_SESSIONS_PER_USER = 1.22
EST_AVG_DURATION_SECONDS = 138  # 02:18
EST_BOUNCE_RATE = 64.0


def _positive_or(value, fallback):
    try:
        value = float(value)
        return value if value > 0 else fallback
    except (TypeError, ValueError):
        return fallback


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
    # than PageView, so missing historical days are estimated from pageviews.
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
    measured_sessions = measured_users = new_users = 0
    measured_avg_duration = 0
    measured_pages_per_session = measured_bounce_rate = 0.0
    total_session_pageviews = 0
    measured_bounces = 0
    top_referrers = []
    devices = {"Desktop": 0, "Mobile": 0, "Tablet": 0, "Outro": 0}

    if sessions_available:
        session_q = AnalyticsSession.query.filter(
            AnalyticsSession.created_at >= start,
            AnalyticsSession.created_at < end,
        )
        visitor = func.nullif(AnalyticsSession.visitor_id, '')
        totals = session_q.with_entities(func.count(AnalyticsSession.id), func.count(distinct(visitor)),
            func.count(distinct(case((AnalyticsSession.is_new_user.is_(True), visitor)))),
            func.coalesce(func.sum(AnalyticsSession.duration_seconds), 0),
            func.coalesce(func.sum(AnalyticsSession.pageviews), 0),
            func.coalesce(func.sum(case((AnalyticsSession.is_bounce.is_(True), 1), else_=0)), 0)).one()
        measured_sessions, measured_users, new_users, total_duration, total_session_pageviews, measured_bounces = totals
        measured_avg_duration = round(total_duration / measured_sessions) if measured_sessions else 0
        measured_pages_per_session = round(total_session_pageviews / measured_sessions, 2) if measured_sessions else 0.0
        measured_bounce_rate = round(measured_bounces / measured_sessions * 100, 1) if measured_sessions else 0.0
        if db.engine.dialect.name == 'sqlite':
            # Keep timezone/DST behavior identical in SQLite tests/local installs.
            conn = db.session.connection().connection.driver_connection
            conn.create_function('report_local_day', 1, lambda value: datetime.fromisoformat(value).replace(tzinfo=timezone.utc).astimezone(REPORT_TZ).date().isoformat())
            local_day_expr = func.report_local_day(AnalyticsSession.created_at)
        else:
            local_day_expr = func.date(func.timezone('America/Sao_Paulo', func.timezone('UTC', AnalyticsSession.created_at)))
        daily = session_q.with_entities(local_day_expr, func.count(AnalyticsSession.id),
            func.count(distinct(AnalyticsSession.visitor_id)), func.sum(AnalyticsSession.duration_seconds),
            func.sum(AnalyticsSession.pageviews), func.sum(case((AnalyticsSession.is_bounce.is_(True), 1), else_=0))
        ).group_by(local_day_expr).all()
        for stamp, sessions, users, duration, pageviews, bounces in daily:
            day = date.fromisoformat(stamp) if isinstance(stamp, str) else stamp
            session_counts[day] = sessions
            session_users[day] = users
            session_duration[day] = duration or 0
            session_pageviews[day] = pageviews or 0
            session_bounces[day] = bounces or 0
        ref = func.trim(func.coalesce(AnalyticsSession.referrer, ''))
        top_referrers = session_q.with_entities(ref, func.count(AnalyticsSession.id)).group_by(ref).order_by(func.count(AnalyticsSession.id).desc(), ref).limit(20).all()
        ua = func.lower(func.coalesce(AnalyticsSession.user_agent, ''))
        def has_any(tokens):
            from sqlalchemy import or_
            return or_(*(ua.like('%' + token + '%') for token in tokens))
        device = case((has_any(('ipad', 'tablet', 'kindle')), 'Tablet'),
            (has_any(('mobi', 'android', 'iphone', 'ipod')), 'Mobile'), (ua != '', 'Desktop'), else_='Outro')
        for name, count in session_q.with_entities(device, func.count(AnalyticsSession.id)).group_by(device).all():
            devices[name] = count

    # Prefer ratios learned from measured data when it exists. If there is no
    # measured history, use the conservative baseline agreed for this dashboard.
    model_pages_per_session = _positive_or(measured_pages_per_session, EST_PAGES_PER_SESSION)
    measured_sessions_per_user = (measured_sessions / measured_users) if measured_users else 0
    model_sessions_per_user = _positive_or(measured_sessions_per_user, EST_SESSIONS_PER_USER)
    model_avg_duration = int(_positive_or(measured_avg_duration, EST_AVG_DURATION_SECONDS))
    model_bounce_rate = _positive_or(measured_bounce_rate, EST_BOUNCE_RATE)

    def needs_estimate(day):
        if not sessions_available:
            return True
        return bool(session_first_day and day < session_first_day)

    daily_series = []
    estimated_days_count = 0
    estimated_sessions = 0
    estimated_users = 0
    estimated_duration_total = 0
    estimated_bounces = 0.0
    estimated_pageviews = 0

    for offset in range(window_days):
        day = start_day + timedelta(days=offset)
        day_pageviews = counts.get(day, 0)
        estimated = needs_estimate(day)
        if estimated:
            day_sessions = round(day_pageviews / model_pages_per_session) if day_pageviews else 0
            day_users = round(day_sessions / model_sessions_per_user) if day_sessions else 0
            day_avg_duration = model_avg_duration if day_sessions else 0
            day_pps = round(day_pageviews / day_sessions, 2) if day_sessions else 0.0
            day_bounce = round(model_bounce_rate, 1) if day_sessions else 0.0
            estimated_days_count += 1
            estimated_sessions += day_sessions
            estimated_users += day_users
            estimated_duration_total += day_sessions * day_avg_duration
            estimated_bounces += day_sessions * (day_bounce / 100.0)
            estimated_pageviews += day_pageviews
        else:
            day_sessions = session_counts.get(day, 0)
            day_duration = session_duration.get(day, 0)
            day_spv = session_pageviews.get(day, 0)
            day_bounces = session_bounces.get(day, 0)
            day_users = session_users.get(day, 0)
            day_avg_duration = round(day_duration / day_sessions) if day_sessions else 0
            day_pps = round(day_spv / day_sessions, 2) if day_sessions else 0.0
            day_bounce = round((day_bounces / day_sessions) * 100, 1) if day_sessions else 0.0

        daily_series.append({
            "iso": day.isoformat(),
            "label": day.strftime("%d/%m/%Y"),
            "label_short": day.strftime("%d/%m"),
            "pageviews": day_pageviews,
            "sessions": day_sessions,
            "users": day_users,
            "avg_duration": day_avg_duration,
            "pages_per_session": day_pps,
            "bounce_rate": day_bounce,
            "metrics_estimated": estimated,
            "metric_source": "Estimado" if estimated else "Medido",
        })

    metrics_estimated = estimated_days_count > 0
    session_metrics_available = bool(total or measured_sessions)

    if metrics_estimated:
        sessions = measured_sessions + estimated_sessions
        # Users across the untracked and tracked portions cannot be de-duplicated;
        # therefore this total is explicitly marked as estimated in every export.
        users = measured_users + estimated_users
        measured_duration_total = measured_avg_duration * measured_sessions
        avg_duration = round((measured_duration_total + estimated_duration_total) / sessions) if sessions else 0
        blended_pageviews = total_session_pageviews + estimated_pageviews
        pages_per_session = round(blended_pageviews / sessions, 2) if sessions else 0.0
        bounce_rate = round(((measured_bounces + estimated_bounces) / sessions) * 100, 1) if sessions else 0.0
    else:
        sessions = measured_sessions
        users = measured_users
        avg_duration = measured_avg_duration
        pages_per_session = measured_pages_per_session
        bounce_rate = measured_bounce_rate

    top_pages = (current.with_entities(PageView.path, func.count(PageView.id).label("views"))
                 .group_by(PageView.path).order_by(func.count(PageView.id).desc(), PageView.path).limit(20).all())
    top_posts = (current.join(Post, PageView.post_id == Post.id)
                 .with_entities(Post.id, Post.title, Post.slug, func.count(PageView.id).label("views"))
                 .group_by(Post.id, Post.title, Post.slug)
                 .order_by(func.count(PageView.id).desc(), Post.id).limit(20).all())
    all_total, first_at = db.session.query(func.count(PageView.id), func.min(PageView.created_at)).one()
    first_day = first_at.replace(tzinfo=timezone.utc).astimezone(REPORT_TZ).date() if first_at else None
    last_24h = PageView.query.filter(PageView.created_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)).count()

    return {
        "start_date": start_day, "end_date": end_day, "total": total,
        "previous_total": previous_total, "delta": delta, "all_total": all_total,
        "last_24h": last_24h, "first_day": first_day,
        "distinct_pages": current.with_entities(func.count(func.distinct(PageView.path))).scalar() or 0,
        "daily_series": daily_series, "top_pages": top_pages, "top_posts": top_posts,
        "sessions_available": sessions_available, "session_data_partial": session_data_partial,
        "session_metrics_available": session_metrics_available,
        "metrics_estimated": metrics_estimated,
        "estimated_days_count": estimated_days_count,
        "measured_sessions": measured_sessions,
        "measured_users": measured_users,
        "session_first_day": session_first_day, "sessions": sessions, "users": users,
        "new_users": new_users, "avg_duration": avg_duration,
        "pages_per_session": pages_per_session, "bounce_rate": bounce_rate,
        "top_referrers": top_referrers, "devices": devices,
        "estimation_model": {
            "pages_per_session": round(model_pages_per_session, 2),
            "sessions_per_user": round(model_sessions_per_user, 2),
            "avg_duration": model_avg_duration,
            "bounce_rate": round(model_bounce_rate, 1),
        },
    }
