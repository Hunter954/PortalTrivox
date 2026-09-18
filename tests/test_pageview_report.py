import csv
import io
from datetime import date, datetime

import pytest
from flask import Flask

from app import login_manager
from app.admin import admin_bp
from app.analytics import pageview_report
from app.models import db, PageView, AnalyticsSession, Post, User
from app.routes import site_bp


@pytest.fixture
def app(tmp_path):
    app = Flask("app")
    app.config.update(TESTING=True, SECRET_KEY="test-only", SQLALCHEMY_DATABASE_URI="sqlite://",
                      MEDIA_ROOT=str(tmp_path), SITE_NAME="Portal Trivox")
    db.init_app(app)
    login_manager.init_app(app)
    app.register_blueprint(admin_bp)
    app.register_blueprint(site_bp)
    with app.app_context():
        db.create_all()
        db.session.add(User(id=1, email="test@example.com", password_hash="unused", is_admin=True))
        db.session.add(User(id=2, email="reader@example.com", password_hash="unused", is_admin=False))
        post = Post(id=1, title="Matéria <teste>", slug="teste", published_at=datetime(2026, 8, 1))
        db.session.add(post)
        db.session.flush()
        for stamp, path, post_id in [
            ("2026-08-30T12:00:00", "/", None),  # preceding two-day window
            ("2026-09-01T02:59:59", "/", None),  # Aug 31 Brazil
            ("2026-09-01T03:00:00", "/p/teste", 1),  # Sep 1 Brazil
            ("2026-09-02T02:59:59", "/p/teste", 1),  # Sep 1 Brazil
            ("2026-09-03T02:59:59", "/", None),  # Sep 2 Brazil
            ("2026-09-03T03:00:00", "/", None),  # excluded from Sep 1-2
        ]:
            db.session.add(PageView(created_at=datetime.fromisoformat(stamp), path=path, post_id=post_id))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def test_saved_views_with_empty_sessions_and_brazil_boundaries(app):
    report = pageview_report(date(2026, 9, 1), date(2026, 9, 2))
    assert report["total"] == 3
    assert report["previous_total"] == 2
    assert report["delta"] == 50
    assert [d["pageviews"] for d in report["daily_series"]] == [2, 1]
    assert report["all_total"] == 6
    assert report["distinct_pages"] == 2
    assert report["top_posts"][0].views == 2
    assert sum(row.views for row in report["top_pages"]) == report["total"]


def test_sessions_do_not_double_count_server_views(app):
    db.session.add(AnalyticsSession(session_id="a", visitor_id="v", pageviews=999,
                                   created_at=datetime(2026, 9, 1, 12)))
    db.session.commit()
    assert pageview_report(date(2026, 9, 1), date(2026, 9, 2))["total"] == 3


def test_inverted_range_and_zero_filled_days(app):
    report = pageview_report(date(2026, 9, 4), date(2026, 9, 1))
    assert report["start_date"] == date(2026, 9, 1)
    assert [d["pageviews"] for d in report["daily_series"]] == [2, 1, 1, 0]


def test_empty_database_and_extreme_dates(app):
    PageView.query.delete()
    db.session.commit()
    report = pageview_report(date.min, date.max)
    assert report["total"] == 0 and report["delta"] is None
    assert report["first_day"] is None
    assert len(report["daily_series"]) <= 3661


def login(client, user_id=1):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_admin_html_and_csv_agree_and_do_not_write(app):
    client = app.test_client()
    login(client)
    response = client.get("/admin/insights?from=2026-09-01&to=2026-09-02&metric=sessions")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Visualizações no período" in html
    assert "Matéria &lt;teste&gt;" in html
    assert "indisponíveis neste histórico" in html
    assert 'data-value="2"' in html
    response = client.get("/admin/insights?from=2026-09-01&to=2026-09-02&format=csv")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    rows = list(csv.reader(io.StringIO(response.data.decode("utf-8-sig")), delimiter=";"))
    assert rows[1:] == [["2026-09-01", "2"], ["2026-09-02", "1"]]
    assert PageView.query.count() == 6
    assert AnalyticsSession.query.count() == 0


@pytest.mark.parametrize("suffix", ["", "?format=csv"])
def test_report_requires_admin(app, suffix):
    client = app.test_client()
    assert client.get("/admin/insights" + suffix).status_code == 302
    login(client, 2)
    response = client.get("/admin/insights" + suffix)
    assert response.status_code in (302, 403)


def test_invalid_date_filter_does_not_fail(app):
    client = app.test_client()
    login(client)
    assert client.get("/admin/insights?from=invalid&to=0001-01-01").status_code == 200
