import base64
from io import BytesIO
from datetime import datetime
from unittest.mock import Mock
import pytest
from PIL import Image
from sqlalchemy import select
from app import media
from app.models import db, MediaAsset, MediaTask, Post


def photo(size=(2800, 1800), fmt='JPEG'):
    with Image.effect_noise(size, 60).convert('RGB') as image:
        stream = BytesIO()
        image.save(stream, fmt, quality=95)
        stream.seek(0)
        return stream


def enable_r2(app):
    app.config.update(R2_ENDPOINT_URL='https://r2.example', R2_BUCKET='bucket', R2_ACCESS_KEY_ID='test', R2_SECRET_ACCESS_KEY='test', R2_PUBLIC_URL='https://images.example')


def test_new_upload_goes_directly_to_r2_and_deduplicates(app, monkeypatch):
    enable_r2(app)
    sent = {}
    remote = Mock()
    def upload(stream, bucket, key, **kwargs):
        sent.update(body=stream.read(), key=key, mime=kwargs['ExtraArgs']['ContentType'])
    remote.upload_fileobj.side_effect = upload
    monkeypatch.setattr(media, 'r2_client', lambda: remote)
    def head(*args, **kwargs):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {'Content-Length': str(len(sent['body']))}
        return response
    monkeypatch.setattr(media.requests, 'head', head)
    with app.app_context():
        with photo() as stream:
            original = len(stream.getbuffer())
            first = media.save_upload(stream, 'photo.jpg', 'posts')
            stream.seek(0)
            assert media.save_upload(stream, 'photo.jpg', 'posts') == first
        assert first == 'https://images.example/' + sent['key']
        assert len(sent['body']) < original * .3
        with Image.open(BytesIO(sent['body'])) as image:
            assert image.format == 'WEBP' and image.size == (1280, 823)
        assert sent['mime'] == 'image/webp'
        assert not media.local_path(sent['key'].removeprefix('portaltrivox/')).exists()
        assert MediaAsset.query.count() == 1
        assert MediaTask.query.count() == 0


def test_failed_r2_upload_never_writes_to_local_volume(app, monkeypatch):
    enable_r2(app)
    monkeypatch.setattr(media, 'r2_client', lambda: Mock(upload_fileobj=Mock(side_effect=OSError('r2 unavailable'))))
    with app.app_context():
        with pytest.raises(OSError, match='r2 unavailable'):
            media.save_upload(photo(), 'failed.jpg', 'posts')
        assert not list(media.root().rglob('*.*'))
        assert MediaAsset.query.count() == 0


def test_public_url_changes_only_after_verified_r2_copy_and_original_survives(app, client, monkeypatch):
    enable_r2(app)
    with app.app_context():
        legacy = media.local_path('posts/legacy.jpg')
        legacy.parent.mkdir(parents=True)
        with photo() as stream:
            original = stream.read()
        legacy.write_bytes(original)
        media._remember('/media/posts/legacy.jpg', 'posts/legacy.jpg', len(original))
        sent = {}
        def upload(filename, bucket, key, **kw):
            sent.update(body=media.local_path(filename).read_bytes(), key=key, args=kw)
        remote = Mock()
        remote.upload_file.side_effect = upload
        monkeypatch.setattr(media, 'r2_client', lambda: remote)
        head = Mock()
        head.__enter__ = Mock(return_value=head)
        head.__exit__ = Mock(return_value=False)
        head.raise_for_status.side_effect = ValueError('public endpoint unavailable')
        monkeypatch.setattr(media.requests, 'head', lambda *a, **kw: head)
        with pytest.raises(ValueError):
            media.upload_asset('posts/legacy.jpg')
        assert media.resolve_media('/media/posts/legacy.jpg') == '/media/posts/legacy.jpg'
        assert client.get('/media/posts/legacy.jpg').status_code == 200
        head.raise_for_status.side_effect = None
        head.headers = {'Content-Length': str(len(sent['body']))}
        media.upload_asset('posts/legacy.jpg')
        assert media.resolve_media('/media/posts/legacy.jpg').startswith('https://images.example/portaltrivox/')
        assert sent['body'] == original
        assert sent['args']['ExtraArgs']['ContentType'] == 'image/jpeg'
        assert legacy.read_bytes() == original
        assert client.get('/media/posts/legacy.jpg').status_code == 302


def test_remote_mirror_is_immediate_then_compressed_in_queue(app, monkeypatch):
    from app.sync import download_external_image
    source = 'https://publisher.example/media/photo.jpg'
    with app.app_context():
        monkeypatch.setattr(media.requests, 'get', Mock(side_effect=AssertionError('sync download')))
        assert download_external_image(source) == source
        post = Post(title='Mirror', slug='mirror', source='hub', featured_image=source)
        db.session.add(post)
        db.session.commit()
        task = MediaTask.query.filter_by(kind='post').one()
        assert task.target == str(post.id)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [photo().getvalue()]
        monkeypatch.setattr(media.requests, 'get', lambda *a, **kw: response)
        media.process_post(post.id)
        db.session.expire_all()
        assert db.session.get(Post, post.id).featured_image.endswith('.webp')
        assert not media.is_local_url(source)


def test_rollback_does_not_queue_unpublished_article(app):
    with app.app_context():
        db.session.add(Post(title='Draft', slug='draft', featured_image='https://example/image.jpg'))
        db.session.flush()
        db.session.rollback()
        assert not MediaTask.query.count()
        assert not Post.query.count()


def test_legacy_migration_copies_originals_without_local_derivatives(app, monkeypatch):
    enable_r2(app)
    with app.app_context():
        original = photo().getvalue()
        for name in ['a.jpg','b.jpg']:
            media.local_path(name).write_bytes(original)
        remote = Mock()
        sent = []
        remote.upload_file.side_effect = lambda filename, *a, **kw: sent.append(media.local_path(filename).read_bytes())
        monkeypatch.setattr(media, 'r2_client', lambda: remote)
        def head(*a, **kw):
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.headers = {'Content-Length': str(len(sent[-1]))}
            return response
        monkeypatch.setattr(media.requests, 'head', head)
        media.upload_asset('a.jpg')
        media.upload_asset('b.jpg')
        assert sent == [original, original]
        assert media.resolve_media('/media/a.jpg').startswith('https://images.example/portaltrivox/')
        assert media.resolve_media('/media/b.jpg').startswith('https://images.example/portaltrivox/')
        assert sorted(path.name for path in media.root().iterdir()) == ['a.jpg', 'b.jpg']


def test_pixel_byte_limits_alpha_animation_and_orientation(app):
    with app.app_context():
        app.config['IMAGE_MAX_PIXELS'] = 10
        with pytest.raises(ValueError, match='pixels'):
            media.save_upload(photo((100, 100)), 'image.jpg')
        app.config['IMAGE_MAX_PIXELS'] = 24_000_000
        stream = BytesIO()
        with Image.new('RGBA', (1800,900), (255,0,0,90)) as image:
            image.save(stream, 'PNG')
        url = media.save_upload(stream, 'image.png')
        with Image.open(media.local_path(url.removeprefix('/media/'))) as image:
            assert image.getpixel((1,1))[3] == 90
        gif = BytesIO()
        with Image.new('RGB',(30,30),'red') as a, Image.new('RGB',(30,30),'blue') as b:
            a.save(gif,'GIF',save_all=True,append_images=[b],loop=0,duration=100)
        url = media.save_upload(gif, 'ad.gif')
        assert media.local_path(url.removeprefix('/media/')).read_bytes() == gif.getvalue()
        app.config['IMAGE_MAX_BYTES'] = 10
        with pytest.raises(Exception, match='limite'):
            media.save_upload(photo((100,100)), 'image.jpg')


def test_queue_prioritizes_new_images_over_historical_posts(app, monkeypatch):
    with app.app_context():
        media.enqueue('post', '1', background=True)
        media.enqueue('asset', 'legacy', background=True)
        media.enqueue('asset', 'new')
        completed=[]
        monkeypatch.setattr(media, 'upload_asset', lambda key: completed.append(key))
        with media.worker_lock() as acquired:
            assert acquired
            media.run_one()
        assert completed == ['new']
        assert MediaTask.query.filter_by(target='new').one().state == 'done'


def test_bot_multipart_and_legacy_preserve_social_png(app, client):
    headers={'X-Bot-Token':'test-token'}
    raw=photo((300,200)).getvalue()
    for data, multipart in [({'title':'Teste','image':(BytesIO(raw),'test.jpg')},True),
                             ({'title':'Teste','image_base64':base64.b64encode(raw).decode()},False)]:
        response=client.post('/admin/api/whatsapp-bot/generate-trivox-photo',headers=headers,**({'data':data} if multipart else {'json':data}))
        assert response.status_code == 200, response.json
        url=response.json['images'][0]['url']
        with app.app_context():
            with Image.open(media.local_path(url.split('/media/')[1])) as image:
                assert image.format=='PNG' and image.size==(1080,1440)
    assert client.options('/admin/api/whatsapp-bot/generate-trivox-photo').headers['X-Media-Upload']=='multipart'
