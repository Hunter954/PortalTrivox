import io
import json
import subprocess
import threading
from datetime import datetime, date, timedelta
from unittest.mock import Mock
from sqlalchemy import event
from PIL import Image
from app.models import db, Post, AnalyticsSession, PageView
from app import media
from app.analytics import pageview_report
from app.admin import _analytics_stats


def test_posts_are_paginated_without_loading_article_bodies_or_dashboard(app, client, monkeypatch):
    import app.admin as admin
    monkeypatch.setattr(admin, '_dashboard_stats', Mock(side_effect=AssertionError('dashboard query')))
    with app.app_context():
        db.session.add_all([Post(title=f'Title {i}', slug=f'post-{i}', source='local', content_html='x'*10000,
                                published_at=datetime(2026,1,1)+timedelta(days=i)) for i in range(85)])
        db.session.commit()
        statements=[]
        def collect(_conn,_cursor,statement,*args): statements.append(statement)
        event.listen(db.engine,'before_cursor_execute',collect)
        response=client.get('/admin/posts?page=2&q=Title&source=local')
        assert response.status_code==200
        assert response.data.count(b'onsubmit="return confirm')==40
        assert response.data.count('aria-label="Paginação"'.encode())==1
        assert b'page=3' in response.data
        assert not any('post.content_html' in sql for sql in statements)
        event.remove(db.engine,'before_cursor_execute',collect)


def test_catalog_is_paginated_and_route_does_not_scan_disk(app,client,monkeypatch):
    with app.app_context():
        for i in range(55):
            path=media.local_path(f'file-{i}.svg');path.write_text('<svg/>')
            media._remember('/media/'+path.name,path.name)
        monkeypatch.setattr(media.os, 'walk', Mock(side_effect=AssertionError('request scans disk')))
        response=client.get('/admin/media')
        assert response.status_code==200
        assert response.data.count(b'media-library-card')==48
        assert b'page=2' in response.data


def test_measured_reports_preserve_distinct_users_boundaries_devices_and_bounces(app):
    with app.app_context():
        rows=[('a','one',datetime(2026,9,1,3),2,30,True,'Android','google'),
              ('b','one',datetime(2026,9,2,2),4,90,False,'iPad','google'),
              ('c','two',datetime(2026,9,2,4),1,60,True,'Windows',''),
              ('outside','excluded',datetime(2026,9,3,3),50,999,True,'Windows','')]
        for key,visitor,stamp,views,duration,bounce,ua,ref in rows:
            db.session.add(AnalyticsSession(session_id=key,visitor_id=visitor,created_at=stamp,pageviews=views,
                duration_seconds=duration,is_bounce=bounce,is_new_user=True,user_agent=ua,referrer=ref))
        db.session.add_all([PageView(path='/',created_at=datetime(2026,9,1,10)),PageView(path='/',created_at=datetime(2026,9,2,10))])
        db.session.commit()
        report=pageview_report(date(2026,9,1),date(2026,9,2))
        assert report['measured_sessions']==3
        assert report['measured_users']==2
        assert report['new_users']==2
        assert report['avg_duration']==60
        assert report['bounce_rate']==66.7
        assert [day['users'] for day in report['daily_series']]==[1,1]
        assert [day['sessions'] for day in report['daily_series']]==[2,1]
        assert report['devices']=={'Desktop':1,'Mobile':1,'Tablet':1,'Outro':0}
        assert report['top_referrers'][0]==('google',2)
        stats=_analytics_stats(start_date=date(2026,9,1),end_date=date(2026,9,2))
        assert stats['current']['total_users']==2


def test_busy_generation_rejects_before_body_parse(app,client):
    from app.resources import generation_slot
    ready=threading.Event();release=threading.Event()
    def occupy():
        with generation_slot():
            ready.set();release.wait(5)
    thread=threading.Thread(target=occupy);thread.start();ready.wait(5)
    try:
        response=client.post('/admin/api/whatsapp-bot/generate-trivox-video',data=b'invalid')
        assert response.status_code==429
    finally:
        release.set();thread.join()


def test_real_ffmpeg_video_keeps_dimensions_with_disk_stream(app,tmp_path):
    from app.video_generator import generate_trivox_reels_video
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=5',
                    '-t','0.4','-c:v','libx264','-threads','1','-y',str(source)],check=True)
    with app.app_context(),source.open('rb') as stream:
        result=generate_trivox_reels_video(video_stream=stream,title='Teste de vídeo')
        target=media.local_path(result['url'].removeprefix('/media/'))
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(target)]))
        video=next(item for item in info['streams'] if item['codec_type']=='video')
        assert (video['width'],video['height'])==(1080,1920)


def test_health_admin_pages_and_resource_auth(app,client):
    for route in ['/','/admin/','/admin/settings','/admin/posts/new','/admin/categories','/admin/insights','/admin/media','/health','/admin/api/resources']:
        response=client.get(route)
        assert response.status_code==200,(route,response.status_code)
    assert client.get('/health').json['image_compression']=='webp-v1'
    assert app.test_client().get('/admin/api/resources').status_code==401


def test_postgres_driver_and_pool_bound(monkeypatch):
    from app.config import _database_url,_engine_options
    from sqlalchemy import create_engine
    for url in ['postgres://user:password@localhost/db','postgresql://user:password@localhost/db','postgresql+psycopg://user:password@localhost/db']:
        monkeypatch.setenv('DATABASE_URL',url)
        uri=_database_url()
        engine=create_engine(uri,**_engine_options(uri))
        assert engine.dialect.driver=='psycopg2'
        assert engine.pool.size()==4
        engine.dispose()
