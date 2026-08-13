import os
import threading, time
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import inspect, text
from flask import Flask
from flask_login import LoginManager
from dotenv import load_dotenv

from .config import Config
from .models import db, User, AdSlot, SiteSetting, Post, Category
from .routes import site_bp
from .admin import admin_bp
from .wp_client import WPClient
from .sync import sync_categories, sync_posts

login_manager = LoginManager()
login_manager.login_view = "admin.login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def _ensure_schema_updates():
    inspector = inspect(db.engine)

    if inspector.has_table("user"):
        user_columns = {col["name"] for col in inspector.get_columns("user")}
        user_statements = []
        if "name" not in user_columns:
            user_statements.append('ALTER TABLE "user" ADD COLUMN name VARCHAR(190)')
        if "is_active" not in user_columns:
            user_statements.append('ALTER TABLE "user" ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE')
        if "created_at" not in user_columns:
            user_statements.append('ALTER TABLE "user" ADD COLUMN created_at TIMESTAMP')
        if "updated_at" not in user_columns:
            user_statements.append('ALTER TABLE "user" ADD COLUMN updated_at TIMESTAMP')
        if user_statements:
            with db.engine.begin() as conn:
                for stmt in user_statements:
                    conn.execute(text(stmt))
                conn.execute(text('UPDATE "user" SET is_active = TRUE WHERE is_active IS NULL'))
                conn.execute(text('UPDATE "user" SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL'))
                conn.execute(text('UPDATE "user" SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL'))


    if inspector.has_table("post"):
        post_columns = {col["name"] for col in inspector.get_columns("post")}
        post_statements = []
        # Instalações antigas não tinham esses campos. Sem eles, a tela
        # /admin/importar-parana-atual quebra já no GET ao calcular estatísticas.
        if "source" not in post_columns:
            post_statements.append("ALTER TABLE post ADD COLUMN source VARCHAR(30) DEFAULT 'local'")
        if "source_url" not in post_columns:
            post_statements.append('ALTER TABLE post ADD COLUMN source_url VARCHAR(1000)')
        if "featured_image_credit" not in post_columns:
            post_statements.append('ALTER TABLE post ADD COLUMN featured_image_credit VARCHAR(255)')
        if post_statements:
            with db.engine.begin() as conn:
                for stmt in post_statements:
                    conn.execute(text(stmt))
                if "source" not in post_columns:
                    conn.execute(text("UPDATE post SET source = 'local' WHERE source IS NULL"))

    if inspector.has_table("guide_listing"):
        guide_columns = {col["name"] for col in inspector.get_columns("guide_listing")}
        guide_statements = []
        if "source_provider" not in guide_columns:
            guide_statements.append('ALTER TABLE guide_listing ADD COLUMN source_provider VARCHAR(60)')
        if "source_ref" not in guide_columns:
            guide_statements.append('ALTER TABLE guide_listing ADD COLUMN source_ref VARCHAR(190)')
        if "source_query" not in guide_columns:
            guide_statements.append('ALTER TABLE guide_listing ADD COLUMN source_query VARCHAR(220)')
        if "maps_url" not in guide_columns:
            guide_statements.append('ALTER TABLE guide_listing ADD COLUMN maps_url VARCHAR(1000)')
        if "last_imported_at" not in guide_columns:
            guide_statements.append('ALTER TABLE guide_listing ADD COLUMN last_imported_at TIMESTAMP')
        if guide_statements:
            with db.engine.begin() as conn:
                for stmt in guide_statements:
                    conn.execute(text(stmt))


def _ensure_defaults():
    defaults = [
        ("header_top", "Publicidade (Topo - faixa)"),
        ("home_top", "Publicidade (Home - faixa no meio)"),
        ("home_mid", "Publicidade (Final da matéria)"),
        ("home_bottom", "Publicidade (Home - faixa inferior)"),
        ("sidebar_1", "Publicidade (Sidebar 1)"),
        ("sidebar_2", "Publicidade (Sidebar 2)"),
    ]
    for key, name in defaults:
        if not AdSlot.query.filter_by(key=key).first():
            db.session.add(AdSlot(key=key, name=name, html="", is_active=True))

    for key, value in [
        ("live_embed_html", ""),
        ("logo_url", ""),
        ("site_name", os.getenv("SITE_NAME", "Portal Trivox")),
        ("favicon_url", ""),
        ("default_share_image", ""),
        ("site_tagline", "Notícias de Foz do Iguaçu, Oeste do Paraná e Tríplice Fronteira"),
        ("default_meta_description", "Notícias de Foz do Iguaçu, Tríplice Fronteira, Oeste do Paraná, política, cidades, turismo, esportes e cultura."),
        ("facebook_app_id", ""),
        ("google_site_verification", ""),
        ("google_analytics_id", ""),
        ("contact_email", ""),
        ("contact_phone", ""),
        ("instagram_url", "https://www.instagram.com/trivoxfoz/"),
        ("facebook_url", ""),
        ("youtube_url", ""),
        ("x_url", ""),
        ("footer_contact_label", "Fale conosco"),
        ("footer_contact_url", "#"),
        ("footer_privacy_label", "Privacidade"),
        ("footer_privacy_url", "#"),
        ("footer_terms_label", "Termos e Condições"),
        ("footer_terms_url", "#"),
        ("footer_social_label", "Redes Sociais:"),
        ("footer_copyright_text", "© 2026 Portal Trivox. Todos os direitos reservados."),
        ("site_keywords", "Portal Trivox, notícias, Foz do Iguaçu, Oeste do Paraná, tríplice fronteira, turismo, política"),
        ("top_menu_category_ids", "[]"),
        ("hub_enabled", "0"),
        ("hub_site_key", ""),
        ("hub_receive_token", ""),
        ("hub_auto_push", "1"),
        ("hub_remote_sites_json", "[]"),
    ]:
        if not SiteSetting.query.filter_by(key=key).first():
            db.session.add(SiteSetting(key=key, value=value))

    # Atualiza instalações antigas que ainda estejam com nomes do projeto anterior.
    legacy_values = {
        "site_name": {"Portal Trivox", "Foz do Iguaçu1000grau", "portalparanaatual"},
        "footer_copyright_text": {"Todos os direitos reservados - 2009-2026 - PORTAL PARANÁ ATUAL", "Todos os direitos reservados - 2009-2026 - PORTALPARANAATUAL.COM.BR"},
    }
    site_name = SiteSetting.query.filter_by(key="site_name").first()
    if site_name and (not site_name.value or site_name.value in legacy_values["site_name"]):
        site_name.value = os.getenv("SITE_NAME", "Portal Trivox")
    footer_copy = SiteSetting.query.filter_by(key="footer_copyright_text").first()
    if footer_copy and ("1000" in (footer_copy.value or "") or "STI" in (footer_copy.value or "").upper()):
        footer_copy.value = "Todos os direitos reservados - Portal Trivox"

    db.session.commit()



def _ensure_starter_content():
    if Post.query.count() > 0:
        return
    category_names = [
        ("Cidades", "cidades"), ("Paraná", "parana"), ("Política", "politica"),
        ("Policial", "policial"), ("Esportes", "esportes"), ("Turismo", "turismo"),
        ("Cultura", "cultura"), ("Economia", "economia"),
    ]
    cats = {}
    for name, slug in category_names:
        cat = Category.query.filter_by(slug=slug).first()
        if not cat:
            cat = Category(name=name, slug=slug)
            db.session.add(cat)
            db.session.flush()
        cats[slug] = cat

    now = datetime.utcnow()
    stories = [
        {"title":"Paraná terá sol, calor de 30°C e chuva na virada do fim de semana", "excerpt":"A mudança no tempo deve combinar períodos de sol, elevação das temperaturas e possibilidade de chuva em diferentes regiões do estado.", "cat":"parana", "author":"Redação Trivox", "source":"https://www.bemparana.com.br/", "img":"clima"},
        {"title":"Paraná inicia em agosto a segunda dose da vacina contra a poliomielite", "excerpt":"A nova etapa do calendário de vacinação começa neste mês e reforça a importância de manter a caderneta infantil atualizada.", "cat":"parana", "author":"Redação Trivox", "source":"https://www.bemparana.com.br/", "img":"saude"},
        {"title":"Avião com destino a Curitiba retorna a Lisboa após questão técnica", "excerpt":"A aeronave precisou regressar ao aeroporto de origem. Passageiros receberam assistência enquanto a operação era reorganizada.", "cat":"turismo", "author":"Agência de Notícias", "source":"https://www.gazetadopovo.com.br/ultimas-noticias/", "img":"aviao"},
        {"title":"Moro é confirmado pelo PL na disputa pelo Governo do Paraná", "excerpt":"A convenção partidária confirmou o nome para a corrida ao Palácio Iguaçu e movimentou o cenário eleitoral paranaense.", "cat":"politica", "author":"Redação Política", "source":"https://www.gazetadopovo.com.br/ultimas-noticias/", "img":"politica"},
        {"title":"MDB e PSD oficializam aliança para as eleições estaduais de 2026", "excerpt":"O acordo partidário reorganiza as principais forças políticas do estado e define novos nomes para a chapa majoritária.", "cat":"politica", "author":"Redação Política", "source":"https://oparana.com.br/", "img":"assembleia"},
        {"title":"Dois morrem em grave acidente no Oeste do Paraná", "excerpt":"Equipes de resgate e autoridades foram acionadas para atender a ocorrência. As circunstâncias serão apuradas.", "cat":"policial", "author":"Redação Trivox", "source":"https://cgn.inf.br/", "img":"rodovia"},
        {"title":"Jovem é socorrida após colisão entre carro e moto em Cascavel", "excerpt":"A vítima recebeu atendimento no local e foi encaminhada para avaliação médica após o acidente em uma das principais avenidas da cidade.", "cat":"policial", "author":"Redação Trivox", "source":"https://cgn.inf.br/", "img":"resgate"},
        {"title":"Motociclista fica ferido em colisão frontal na BR-277", "excerpt":"O acidente mobilizou socorristas e chamou a atenção para os cuidados necessários no trecho que corta o Oeste do Paraná.", "cat":"cidades", "author":"Redação Trivox", "source":"https://cgn.inf.br/", "img":"br277"},
        {"title":"Prefeitura cria comissão para avaliar uso do Mounjaro pelo SUS em Foz", "excerpt":"Grupo técnico deverá estabelecer critérios para uma possível oferta do medicamento no atendimento público de pessoas com obesidade.", "cat":"cidades", "author":"Paraná Pop", "source":"https://www.paranapop.com.br/p/prefeitura-cria-comissao-para-viabilizar-uso-do-mounjaro-pelo-sus-em-foz-do-iguacu", "img":"foz"},
        {"title":"Hospital atualiza estado de sobreviventes de acidente em Foz do Iguaçu", "excerpt":"Quatro vítimas permaneciam internadas após a colisão. A Polícia Civil segue investigando as causas do acidente.", "cat":"cidades", "author":"Paraná Pop", "source":"https://www.paranapop.com.br/p/pm-confirma-que-carro-levava-10-pessoas-hospital-atualiza-estado-de-saude-dos-sobreviventes", "img":"hospital"},
        {"title":"Foz do Iguaçu e região ganham uma nova plataforma de notícias", "excerpt":"O Portal Trivox conecta Foz do Iguaçu, Oeste do Paraná e Tríplice Fronteira com informação local, regional e estadual em leitura rápida e visual moderno.", "cat":"cidades", "author":"Redação Trivox", "source":"https://www.instagram.com/trivoxfoz/", "img":"fronteira"},
        {"title":"Turismo de fronteira impulsiona comércio e serviços no Oeste", "excerpt":"A circulação de visitantes entre Brasil, Paraguai e Argentina segue fortalecendo hotéis, restaurantes, transporte e comércio regional.", "cat":"turismo", "author":"Redação Trivox", "source":"https://www.instagram.com/trivoxfoz/", "img":"turismo"},
    ]
    for i, st in enumerate(stories):
        slug = st["title"].lower()
        import re, unicodedata
        slug = unicodedata.normalize('NFKD', slug).encode('ascii','ignore').decode()
        slug = re.sub(r'[^a-z0-9]+','-',slug).strip('-')
        post = Post(
            title=st["title"], slug=slug, excerpt=st["excerpt"],
            content_html=f'<p>{st["excerpt"]}</p><p>Esta matéria inicial foi preparada para a implantação do portal. Acompanhe as atualizações da redação e consulte a fonte original para mais detalhes.</p><p><a href="{st["source"]}" target="_blank" rel="noopener">Consultar fonte original</a></p>',
            featured_image=f'/static/img/news-{st["img"]}.svg', author_name=st["author"],
            source='starter', source_url=st["source"] + (f'#portaltrivox-{i}' if i else ''),
            published_at=now-timedelta(hours=i*2), updated_at=now-timedelta(hours=i*2),
        )
        post.categories.append(cats[st["cat"]])
        db.session.add(post)
    # define menu order automatically
    menu = [cats[x].id for x in ['cidades','parana','politica','policial','esportes','turismo','cultura','economia']]
    menu_setting = SiteSetting.query.filter_by(key='top_menu_category_ids').first()
    if menu_setting:
        import json
        menu_setting.value = json.dumps(menu)
    db.session.commit()


def _auto_sync_loop(app: Flask):
    with app.app_context():
        client = WPClient(app.config["WP_BASE_URL"])
        while True:
            try:
                sync_categories(client)
                sync_posts(client, max_pages=50, per_page=app.config["WP_PER_PAGE"])
            except Exception:
                pass
            time.sleep(app.config["AUTO_SYNC_INTERVAL"])


def create_app():
    load_dotenv()
    app = Flask(__name__)
    app.config.from_object(Config)

    Path(app.config["MEDIA_ROOT"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(site_bp)
    app.register_blueprint(admin_bp)

    from datetime import datetime
    app.jinja_env.globals["now"] = datetime.now

    with app.app_context():
        db.create_all()
        _ensure_schema_updates()
        _ensure_defaults()
        _ensure_starter_content()

        admin_email = "admin@admin.com"
        admin_password = "senha123"

        u = User.query.filter_by(email=admin_email).first()
        if not u:
            u = User(name="Administrador", email=admin_email, is_admin=True, is_active=True)
            u.set_password(admin_password)
            db.session.add(u)
        else:
            u.is_admin = True
            u.is_active = True
            if not u.name:
                u.name = "Administrador"
            if not u.password_hash:
                u.set_password(admin_password)
        db.session.commit()
        print("ADMIN OK:", admin_email)

    if app.config.get("AUTO_SYNC_INTERVAL", 0) and app.config["AUTO_SYNC_INTERVAL"] > 0:
        t = threading.Thread(target=_auto_sync_loop, args=(app,), daemon=True)
        t.start()

    return app
