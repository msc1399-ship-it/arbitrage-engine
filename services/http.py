import time
import requests


class ConnectorError(RuntimeError):
    def __init__(self, message, *, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class ConnectorAuthenticationError(ConnectorError):
    pass


class ConnectorRateLimitError(ConnectorError):
    pass


def request_with_backoff(method, url, *, session=None, headers=None, params=None, data=None,
                         auth=None, timeout=30, max_retries=6, base_delay=2.0,
                         sleep=time.sleep, on_rate_limit=None):
    requester = session or requests
    last_error = None
    last_status_code = None
    for attempt in range(max_retries):
        try:
            r = requester.request(method, url, headers=headers or {}, params=params,
                                  data=data, auth=auth, timeout=timeout)
            if r.status_code in (401, 403):
                raise ConnectorAuthenticationError(
                    "Connector authentication failed", status_code=r.status_code
                )
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else base_delay * (2 ** attempt)
                except ValueError:
                    wait = base_delay * (2 ** attempt)
                wait = min(wait, 120)
                if attempt == max_retries - 1:
                    raise ConnectorRateLimitError("Connector rate limit exceeded")
                if on_rate_limit is not None:
                    on_rate_limit(attempt=attempt + 1, wait_seconds=wait)
                sleep(wait)
                continue
            if 400 <= r.status_code < 500:
                raise ConnectorError(
                    f"Connector request rejected with HTTP {r.status_code}",
                    status_code=r.status_code,
                )
            r.raise_for_status()
            return r
        except (ConnectorAuthenticationError, ConnectorRateLimitError):
            raise
        except requests.RequestException as e:
            last_error = e
            last_status_code = getattr(getattr(e, "response", None), "status_code", None)
            if last_status_code is None and "r" in locals():
                last_status_code = getattr(r, "status_code", None)
            if attempt == max_retries - 1:
                break
            wait = min(base_delay * (2 ** attempt), 60)
            sleep(wait)
    raise ConnectorError(
        f"Connector request failed after {max_retries} attempts",
        status_code=last_status_code,
    ) from last_error


def get_with_backoff(url, *, headers=None, params=None, timeout=30, max_retries=6,
                     base_delay=2.0):
    return request_with_backoff("GET", url, headers=headers, params=params,
                                timeout=timeout, max_retries=max_retries,
                                base_delay=base_delay)
