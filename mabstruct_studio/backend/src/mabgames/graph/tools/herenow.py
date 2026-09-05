"""The here.now publishing client.

Ported from the notebook, with two changes:

* **The API key arrives as an argument**, not from `os.getenv` plus a read of
  `~/.herenow/credentials`. pydantic-settings does not populate `os.environ`, so
  the notebook's lookup would silently find nothing here and publish anonymous
  24-hour sites. `Settings.here_now_api_key` already accepts both spellings of
  the variable. The home-directory read is dropped: invisible to the settings
  layer, and silently different per machine.
* **The HTTP session is injectable**, so the three-step publish can be tested
  without touching the network.

Nothing else moves. The sequence, the 409 handling and the upload loop were all
learned against the real service.
"""

import hashlib
import time
from pathlib import Path

import requests

HERENOW_BASE_URL = "https://here.now"
HERENOW_CLIENT = "langgraph/mabstruct_studio"
HERENOW_TIMEOUT = 60
HERENOW_UPLOAD_TIMEOUT = 180
FINALIZE_ATTEMPTS = 4
DEFAULT_RETRY_AFTER = 3.0


class HereNowClient:
    """Publish a single file to here.now.

    here.now does not let a caller choose its slug, so a stable URL means
    creating a site once and updating that slug afterwards. Under Q4/AD5 every
    build gets its own site and nothing overwrites, so `slug` is normally empty.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = HERENOW_BASE_URL,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    @property
    def anonymous(self) -> bool:
        """Without a key every publish is a site that expires 24 hours later."""
        return not self.api_key

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "X-HereNow-Client": HERENOW_CLIENT}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _finalize(self, slug: str, version_id: str, finalize_url: str | None) -> dict:
        """Nothing is live until finalize succeeds.

        It is idempotent by versionId and answers 409 finalize_in_flight plus
        Retry-After while another finalize holds the same version — that is a
        "wait and retry", not a failure.
        """
        url = finalize_url or f"{self.base_url}/api/v1/publish/{slug}/finalize"

        for _ in range(FINALIZE_ATTEMPTS):
            response = self.session.post(
                url,
                json={"versionId": version_id},
                headers=self._headers(),
                timeout=HERENOW_TIMEOUT,
            )
            if response.status_code == 409 and "finalize_in_flight" in response.text:
                time.sleep(float(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER)))
                continue
            response.raise_for_status()
            return response.json()

        raise RuntimeError(f"finalize kept reporting finalize_in_flight for slug {slug}")

    def publish(
        self,
        html_path: Path,
        display_name: str = "",
        display_description: str = "",
        slug: str = "",
    ) -> dict:
        """Three-step publish: create/update -> upload -> finalize."""
        data = html_path.read_bytes()
        body: dict = {
            "files": [
                {
                    "path": "index.html",
                    "size": len(data),
                    "contentType": "text/html",
                    "hash": hashlib.sha256(data).hexdigest(),
                }
            ]
        }
        if display_name:
            body["displayName"] = display_name[:80]
        if display_description:
            body["displayDescription"] = display_description[:280]

        headers = self._headers()
        created = None

        if slug:
            response = self.session.put(
                f"{self.base_url}/api/v1/publish/{slug}",
                json=body,
                headers=headers,
                timeout=HERENOW_TIMEOUT,
            )
            if response.status_code == 404:
                slug = ""  # the recorded site is gone — create a new one
            else:
                response.raise_for_status()
                created = response.json()

        if created is None:
            response = self.session.post(
                f"{self.base_url}/api/v1/publish",
                json=body,
                headers=headers,
                timeout=HERENOW_TIMEOUT,
            )
            response.raise_for_status()
            created = response.json()

        upload = created["upload"]
        version_id = upload["versionId"]

        # Re-publishing identical bytes deduplicates server-side: the file lands
        # in `skipped` with no upload target, so drive the loop off `uploads`,
        # not the manifest.
        for target in upload["uploads"]:
            put_headers = dict(target.get("headers", {}))
            if not any(key.lower() == "content-type" for key in put_headers):
                put_headers["Content-Type"] = "text/html"
            put_response = self.session.put(
                target["url"],
                data=data,
                headers=put_headers,
                timeout=HERENOW_UPLOAD_TIMEOUT,
            )
            put_response.raise_for_status()

        finalized = self._finalize(created["slug"], version_id, upload.get("finalizeUrl"))

        return {
            "slug": finalized.get("slug") or created["slug"],
            "site_url": finalized.get("siteUrl") or created.get("siteUrl", ""),
            "version_id": finalized.get("currentVersionId", version_id),
            "anonymous": bool(created.get("anonymous", self.anonymous)),
            "claim_url": created.get("claimUrl", ""),
            "expires_at": created.get("expiresAt"),
            "unchanged": bool(finalized.get("unchanged")),
            "updated_existing": bool(slug),
        }

    def fetch(self, site_url: str, timeout: int = 30) -> requests.Response:
        return self.session.get(site_url, timeout=timeout)
