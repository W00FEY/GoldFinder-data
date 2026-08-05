"""Shared requests session: custom UA, retries, sane timeouts."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import USER_AGENT

DEFAULT_TIMEOUT = 60


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


SESSION = make_session()


def get_json(url: str, params: dict | None = None, timeout: int = DEFAULT_TIMEOUT):
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()
