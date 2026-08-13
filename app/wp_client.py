import requests
from urllib.parse import urljoin


class WPClient:
    def __init__(self, base_url: str, timeout: int = 25):
        self.base_url = (base_url or "").rstrip("/") + "/"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Portal-Trivox-WordPress-Importer/1.0",
            "Accept": "application/json",
        })

    def _get(self, path: str, params: dict):
        url = urljoin(self.base_url, path.lstrip("/"))
        last_exc = None
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                return r.json(), r.headers
            except requests.RequestException as exc:
                last_exc = exc
                if attempt >= 2:
                    raise
        raise last_exc

    def list_posts(self, page: int = 1, per_page: int = 20):
        return self._get(
            "/wp-json/wp/v2/posts",
            {
                "page": page,
                "per_page": per_page,
                "_embed": 1,
                "orderby": "date",
                "order": "desc",
                "status": "publish",
            },
        )

    def list_categories(self, page: int = 1, per_page: int = 100):
        return self._get(
            "/wp-json/wp/v2/categories",
            {"page": page, "per_page": per_page, "hide_empty": True},
        )

    def get_post(self, wp_id: int):
        data, _headers = self._get(f"/wp-json/wp/v2/posts/{int(wp_id)}", {"_embed": 1})
        return data

    def inspect_source(self, per_page: int = 20) -> dict:
        """Faz um preflight barato e retorna o tamanho real do WordPress."""
        posts, post_headers = self.list_posts(page=1, per_page=1)
        categories, category_headers = self.list_categories(page=1, per_page=1)
        total_posts = int(post_headers.get("X-WP-Total", len(posts)) or 0)
        total_pages = int(post_headers.get("X-WP-TotalPages", 1) or 1)
        # X-WP-TotalPages depende do per_page usado no preflight; recalculamos.
        total_pages = max(1, (total_posts + max(1, per_page) - 1) // max(1, per_page)) if total_posts else 0
        total_categories = int(category_headers.get("X-WP-Total", len(categories)) or 0)
        return {
            "total_posts": total_posts,
            "total_pages": total_pages,
            "total_categories": total_categories,
        }
