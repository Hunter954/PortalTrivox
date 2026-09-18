"""Read-only reports of server-recorded page views (UTC storage, Brazil dates)."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from .models import db, PageView, Post

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
    daily_series = []
    for offset in range(window_days):
        day = start_day + timedelta(days=offset)
        daily_series.append({"iso": day.isoformat(), "label": day.strftime("%d/%m/%Y"),
                             "label_short": day.strftime("%d/%m"), "pageviews": counts.get(day, 0)})

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
            "daily_series": daily_series, "top_pages": top_pages, "top_posts": top_posts}
