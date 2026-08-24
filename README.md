# Portal Trivox

Portal de notícias em Flask pronto para implantação em um novo projeto do Railway.

## Implantação

1. Crie um repositório novo no GitHub e envie todo o conteúdo desta pasta.
2. No Railway, crie um projeto a partir do repositório.
3. Adicione um PostgreSQL e configure `DATABASE_URL` com a referência fornecida pelo Railway.
4. Configure `SECRET_KEY` com uma chave forte.
5. Para uploads persistentes, monte um volume em `/data` (o projeto usa `/data/uploads`).
6. O comando de inicialização já está definido no `Procfile`.

## Primeiro acesso ao painel

- URL: `/admin/login`
- E-mail: `admin@admin.com`
- Senha: `senha123`

Altere a senha no painel logo após o primeiro acesso.

## Publicidade configurada

- Cabeçalho: 728 × 90 px
- Após a manchete principal: 728 × 180 px
- Centro da home: 970 × 180 px
- Final das matérias: 970 × 180 px
- Laterais internas: 460 × 320 px

O painel aceita múltiplos banners por posição e faz rotação automática.

## Conteúdo inicial

Em uma instalação com banco vazio, o sistema cria automaticamente categorias e matérias iniciais recentes para a home não ficar vazia. Elas podem ser editadas ou removidas normalmente no painel.

## Menu Admin do Portal Trivox via WhatsApp

O projeto agora expõe duas APIs protegidas para o serviço Baileys:

- `POST /admin/api/whatsapp-menu/action` — gerenciamento de matérias, categorias, usuários, insights, SEO e publicidade.
- `POST /admin/api/whatsapp-bot/generate-trivox-photo` — geração da imagem padrão 1080x1440.

Configure no Railway do Portal Trivox:

```env
WHATSAPP_ADMIN_TOKEN=troque-por-um-token-forte
```

O token deve ser igual ao `ADMIN_MENU_TRIVOX_TOKEN` e `PHOTO_TRIVOX_TOKEN` do serviço WhatsApp.
A rota pública `/foto` existente não foi alterada.
