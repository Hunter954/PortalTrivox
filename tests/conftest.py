import pytest
from app.config import Config
from app import create_app
from app.models import db


@pytest.fixture
def app(tmp_path, monkeypatch):
    import app as package
    monkeypatch.setattr(package, '_ensure_starter_content', lambda: None)
    for key, value in dict(SQLALCHEMY_DATABASE_URI='sqlite:///' + str(tmp_path/'test.db'),
                           SQLALCHEMY_ENGINE_OPTIONS={}, MEDIA_ROOT=str(tmp_path/'media'),
                           MEDIA_WORKER_ENABLED=False, AUTO_SYNC_INTERVAL=0,
                           WHATSAPP_AUTO_SEND_ENABLED=False, WHATSAPP_SERVICE_TOKEN='test-token',
                           R2_BUCKET='', R2_ENDPOINT_URL='', R2_ACCESS_KEY_ID='', R2_SECRET_ACCESS_KEY='', R2_PUBLIC_URL='').items():
        monkeypatch.setattr(Config, key, value)
    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = '1'
        session['_fresh'] = True
    return client
