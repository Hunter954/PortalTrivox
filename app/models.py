from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

post_categories = db.Table(
    "post_categories",
    db.Column("post_id", db.Integer, db.ForeignKey("post.id"), primary_key=True),
    db.Column("category_id", db.Integer, db.ForeignKey("category.id"), primary_key=True),
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(190), unique=True, nullable=False)
    name = db.Column(db.String(190), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wp_id = db.Column(db.Integer, unique=True, index=True, nullable=True)
    name = db.Column(db.String(190), nullable=False)
    slug = db.Column(db.String(190), unique=True, index=True, nullable=False)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    wp_id = db.Column(db.Integer, unique=True, index=True, nullable=True)
    source = db.Column(db.String(30), default="local")  # local | wp | hub | parana_atual_import
    source_url = db.Column(db.String(1000), unique=True, index=True, nullable=True)

    title = db.Column(db.String(500), nullable=False)
    slug = db.Column(db.String(220), unique=True, index=True, nullable=False)
    excerpt = db.Column(db.Text, nullable=True)
    content_html = db.Column(db.Text, nullable=True)

    featured_image = db.Column(db.String(800), nullable=True)
    featured_image_credit = db.Column(db.String(255), nullable=True)
    author_name = db.Column(db.String(190), nullable=True)

    published_at = db.Column(db.DateTime, index=True, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)

    categories = db.relationship("Category", secondary=post_categories, lazy="joined")



class WPImportJob(db.Model):
    __tablename__ = "wp_import_job"
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(30), default="queued", nullable=False, index=True)  # queued | running | completed | failed | cancelled
    phase = db.Column(db.String(60), default="Aguardando início", nullable=False)
    base_url = db.Column(db.String(1000), nullable=True)

    total_posts = db.Column(db.Integer, default=0, nullable=False)
    processed_posts = db.Column(db.Integer, default=0, nullable=False)
    imported_posts = db.Column(db.Integer, default=0, nullable=False)
    updated_posts = db.Column(db.Integer, default=0, nullable=False)
    failed_posts = db.Column(db.Integer, default=0, nullable=False)
    skipped_posts = db.Column(db.Integer, default=0, nullable=False)

    total_categories = db.Column(db.Integer, default=0, nullable=False)
    processed_categories = db.Column(db.Integer, default=0, nullable=False)
    image_successes = db.Column(db.Integer, default=0, nullable=False)
    image_failures = db.Column(db.Integer, default=0, nullable=False)

    current_wp_id = db.Column(db.Integer, nullable=True)
    current_title = db.Column(db.String(500), nullable=True)
    current_page = db.Column(db.Integer, default=0, nullable=False)
    total_pages = db.Column(db.Integer, default=0, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    cancel_requested = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    heartbeat_at = db.Column(db.DateTime, nullable=True, index=True)
    finished_at = db.Column(db.DateTime, nullable=True)


class WPImportLog(db.Model):
    __tablename__ = "wp_import_log"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("wp_import_job.id", ondelete="CASCADE"), nullable=False, index=True)
    wp_id = db.Column(db.Integer, nullable=True, index=True)
    title = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(30), nullable=False, index=True)  # imported | updated | error | info
    message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    job = db.relationship("WPImportJob", backref=db.backref("logs", lazy="dynamic", cascade="all, delete-orphan"))


class AdSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)  # ex: lateral_1, lateral_2, header_top
    name = db.Column(db.String(190), nullable=False)
    html = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)



class GuideCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(190), nullable=False, unique=True)
    slug = db.Column(db.String(190), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    listings = db.relationship('GuideListing', back_populates='category', lazy='dynamic', cascade='all, delete-orphan')


class GuideListing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('guide_category.id'), nullable=False, index=True)
    name = db.Column(db.String(220), nullable=False, index=True)
    slug = db.Column(db.String(220), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(60), nullable=True)
    whatsapp = db.Column(db.String(60), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    neighborhood = db.Column(db.String(120), nullable=True)
    city = db.Column(db.String(120), nullable=True, default='Foz do Iguaçu')
    state = db.Column(db.String(10), nullable=True, default='PR')
    postal_code = db.Column(db.String(30), nullable=True)
    latitude = db.Column(db.String(40), nullable=True)
    longitude = db.Column(db.String(40), nullable=True)
    route_url = db.Column(db.String(1000), nullable=True)
    website = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)
    source_provider = db.Column(db.String(60), nullable=True)
    source_ref = db.Column(db.String(190), nullable=True, index=True)
    source_query = db.Column(db.String(220), nullable=True)
    maps_url = db.Column(db.String(1000), nullable=True)
    last_imported_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    category = db.relationship('GuideCategory', back_populates='listings')


class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

class PageView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=True)
    path = db.Column(db.String(800), nullable=False)
    ua = db.Column(db.String(400), nullable=True)
    ip = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class AdClick(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_key = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class AnalyticsSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(120), unique=True, index=True, nullable=False)
    visitor_id = db.Column(db.String(120), index=True, nullable=False)
    landing_path = db.Column(db.String(800), nullable=True)
    referrer = db.Column(db.String(800), nullable=True)
    user_agent = db.Column(db.String(400), nullable=True)
    pageviews = db.Column(db.Integer, default=1, nullable=False)
    duration_seconds = db.Column(db.Integer, default=0, nullable=False)
    is_bounce = db.Column(db.Boolean, default=True, nullable=False)
    is_new_user = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
