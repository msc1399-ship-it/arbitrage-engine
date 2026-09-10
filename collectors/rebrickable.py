import os
from dotenv import load_dotenv
from services.http import get_with_backoff

load_dotenv()
BASE_URL = "https://rebrickable.com/api/v3/lego"

class RebrickableClient:
    def __init__(self):
        self.api_key = os.getenv("REBRICKABLE_API_KEY")
        if not self.api_key:
            raise RuntimeError("Missing REBRICKABLE_API_KEY")
        self.headers = {"Authorization": f"key {self.api_key}"}

    def _get(self, path, params=None):
        r = get_with_backoff(
            f"{BASE_URL}{path}",
            headers=self.headers,
            params=params or {},
            timeout=30,
        )
        return r.json()

    def get_set(self, set_num):
        return self._get(f"/sets/{set_num}/")

    def list_sets(self, page=1, page_size=100, min_year=None, max_year=None,
                  theme_id=None, search=None, ordering="-year"):
        params = {"page": page, "page_size": page_size, "ordering": ordering}
        if min_year is not None: params["min_year"] = min_year
        if max_year is not None: params["max_year"] = max_year
        if theme_id is not None: params["theme_id"] = theme_id
        if search: params["search"] = search
        return self._get("/sets/", params=params)

    def list_themes(self, page=1, page_size=1000):
        return self._get("/themes/", params={"page": page, "page_size": page_size})
