import time
import requests


class ConnectorError(RuntimeError):
    pass


class ConnectorAuthenticationError(ConnectorError):
    pass


class ConnectorRateLimitError(ConnectorError):
    pass


def request_with_backoff(method, url, *, session=None, headers=None, params=None, data=None,
                         auth=None, timeout=30, max_retries=6, base_delay=2.0,
                         sleep=time.sleep):
    requester = session or requests
    last_error = None
    for attempt in range(max_retries):
        try:
            r = requester.request(method, url, headers=headers or {}, params=params,
                                  data=data, auth=auth, timeout=timeout)
            if r.status_code in (401, 403):
                raise ConnectorAuthenticationError("Connector authentication failed")
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else base_delay * (2 ** attempt)
                except ValueError:
                    wait = base_delay * (2 ** attempt)
                wait = min(wait, 120)
                if attempt == max_retries - 1:
                    raise ConnectorRateLimitError("Connector rate limit exceeded")
                sleep(wait)
                continue
            if 400 <= r.status_code < 500:
                raise ConnectorError(f"Connector request rejected with HTTP {r.status_code}")
            r.raise_for_status()
            return r
        except (ConnectorAuthenticationError, ConnectorRateLimitError):
            raise
        except requests.RequestException as e:
            last_error = e
            if attempt == max_retries - 1:
                break
            wait = min(base_delay * (2 ** attempt), 60)
            sleep(wait)
    raise ConnectorError(f"Connector request failed after {max_retries} attempts") from last_error


def get_with_backoff(url, *, headers=None, params=None, timeout=30, max_retries=6,
                     base_delay=2.0):
    return request_with_backoff("GET", url, headers=headers, params=params,
                                timeout=timeout, max_retries=max_retries,
                                base_delay=base_delay)
