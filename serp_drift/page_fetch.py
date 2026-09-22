"""Optional public-page fetch, with DNS-pinned connections and no API credentials."""

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_BYTES = 2_000_000


def public_addresses(host: str, port: int) -> list[str]:
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Page URL must resolve exclusively to public IP addresses.")
    return addresses


def fetch_page(url: str, timeout: float = 20) -> tuple[str, str, str]:
    from .normalize import canonical_url
    for _ in range(4):
        if not canonical_url(url):
            raise ValueError("Page URL must be a public HTTP(S) URL without credentials.")
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in {80, 443}:
            raise ValueError("Page fetch only supports ports 80 and 443.")
        host = parts.hostname.encode("idna").decode("ascii")
        addresses = public_addresses(host, port)
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        raw_socket = socket.create_connection((addresses[0], port), timeout=timeout)
        try:
            # Pin the verified public IP while retaining TLS hostname verification and the Host header.
            connection.sock = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=host) if parts.scheme == "https" else raw_socket
            path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request("GET", path, headers={"User-Agent": "SERPIntentDriftMonitor/0.1 (+https://nikoalho.fi/)", "Accept": "text/html,text/plain,application/xhtml+xml", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Page redirect has no destination.")
                destination = urljoin(url, location)
                if parts.scheme == "https" and urlsplit(destination).scheme != "https":
                    raise ValueError("Page redirect would downgrade HTTPS.")
                url = destination
                continue
            if response.status != 200:
                raise ValueError(f"Page fetch returned HTTP {response.status}.")
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                raise ValueError("Page response is not HTML or plain text.")
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise ValueError("Page returned compressed content despite requesting identity encoding.")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError("Page response exceeds 2 MB.")
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                return body.decode(encoding), content_type, url
            except (UnicodeError, LookupError):
                raise ValueError("Page response could not be decoded. Supply a UTF-8 local export instead.") from None
        except http.client.HTTPException:
            raise ValueError("Page server returned an invalid or interrupted HTTP response.") from None
        finally:
            connection.close()
            raw_socket.close()
    raise ValueError("Page fetch exceeded three redirects.")
