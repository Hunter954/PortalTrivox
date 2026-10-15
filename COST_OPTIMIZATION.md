# Portal Trivox: memory and media delivery

Baseline from Railway, before this release (24-hour window): web average 0.5492 GB, current 0.6030 GB, maximum 0.6561 GB; volume usage 2.5021 GB. Compare similar traffic windows after deployment; a fresh process alone does not establish sustained savings.

## Application changes

- One Gunicorn worker, four threads; database pool 4 + 1 overflow, 10-second checkout timeout. PostgreSQL explicitly uses psycopg2 and SQLAlchemy is pinned.
- Session analytics aggregate in SQL, preserving distinct users, Brazil date boundaries, device classification and measured/estimated report behavior. Unrelated admin pages do not run dashboard reports.
- Article list: 40 rows per page without article bodies. Media catalog: 48 rows per page, indexed in a background directory walk. Original files are retained.
- Editorial uploads: single WebP encode, maximum edge 1280 px, quality 68/method 3. Small originals are kept when conversion would increase file size. Alpha, EXIF orientation and animations are preserved. Input limits: 15 MB / 24 MP. Decoder work is serialized per process and intermediate files are on disk.
- Multipart WhatsApp uploads are supported alongside bounded legacy base64. Heavy generators reject concurrent jobs before reading the request body. Generated PNG dimensions are unchanged. FFmpeg uses two encoder threads, one filter thread and disk streams instead of full video input/output buffers.
- Local uploads are compressed and saved atomically before returning. R2 transfer happens in a persistent database queue. Remote mirror images retain their source until background localization succeeds. Article image tasks commit/roll back with editorial changes and compare snapshots before replacing URLs, so concurrent edits remain safe.
- New R2 objects use content hashes and immutable cache headers. R2 copy must pass a public HEAD size check before any live link is changed. Original local media remain available throughout migration.

## Activate Cloudflare R2

Create a separate bucket, suggested name `portaltrivox-media`, and configure a public custom domain (suggested `imagens.portaltrivox.com.br`). Create a bucket-scoped Object Read & Write credential. Set these variables in Railway project PORTAL TRIVOX - NATALIA, service web:

| Variable | Value |
| --- | --- |
| `R2_ENDPOINT_URL` | Account S3 endpoint from Cloudflare, without the bucket path |
| `R2_BUCKET` | Actual bucket name |
| `R2_ACCESS_KEY_ID` | Bucket credential Access Key ID |
| `R2_SECRET_ACCESS_KEY` | Bucket credential Secret Access Key |
| `R2_PUBLIC_URL` | Public custom-domain URL, no trailing slash |

These variable names match the Foz1000Grau integration. Do not paste credentials into chats, logs or source control. A Railway redeploy activates the configuration. Until all five values are present, files continue to be served locally and publication still compresses new uploads.

After activation, the single background worker automatically indexes the existing volume, queues legacy files and post images, compresses eligible originals and uploads them to R2. Generated social cards are exempt from editorial resizing. Normal uploads are prioritized before historical work, and image transfers before historical post backfills. Nothing requires deleting or detaching the existing /data volume.

`GET /health` reports release capabilities and `r2_enabled`. Authenticated administrator endpoint `/admin/api/resources` reports queue counts, catalog totals and process RSS. Failed jobs retry with exponential backoff; `flask retry-media` requeues terminal failures. `flask migrate-media` manually indexes existing files. All CLI operations use the same production environment and must not run concurrently with another media worker.

Before R2 activation, legacy compression is off by default. `MEDIA_OPTIMIZE_LEGACY=1` optionally compresses local historical photos in the background while retaining original files. `MEDIA_WORKER_ENABLED=0` disables background processing for tests or diagnostics.

## Validation

Install `requirements-dev.txt`, run `python -m pytest -q tests`. Integration tests use SQLite and a real FFmpeg/ffprobe. Coverage includes compression/deduplication, no synchronous R2 transfer, public verification failure, preservation of originals and PNG dimensions, repeated migration aliases, mirror processing, atomic queue rollback, queue priority, multipart/base64 compatibility, paginated SQL, report aggregates and FFmpeg output.

The pre-existing report UI test referenced labels and CSV columns from an older dashboard. Its failure was reproduced on unmodified commit 5090669; assertions were updated to the already-shipped UI and explicit estimated-data columns without changing the report design or estimation rules.
