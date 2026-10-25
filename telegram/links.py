"""Panel addresses and URLs that can be used in Telegram keyboards."""

from ipaddress import ip_address
from urllib.parse import urlsplit


def http_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
            or parsed.port == 0
        ):
            return None
    except ValueError:
        return None
    return value


def keyboard_url(value):
    value = http_url(value)
    if value is None:
        return None
    host = urlsplit(value).hostname.rstrip(".")
    try:
        address = ip_address(host)
    except ValueError:
        # TDLib LinkManager::check_link_impl requires a dotted HTTP host (or IPv6).
        return value if "." in host and not host.endswith(".localhost") else None
    # Loopback links would open the recipient's device, not the application host.
    return None if address.is_loopback or address.is_unspecified else value
