"""A configured public IP must accept host-bound Secure API cookies, without network I/O."""
import asyncio
import os
from http.cookies import SimpleCookie
from unittest.mock import patch

from api import PaymentsClient
from yarl import URL


async def main():
    with patch.dict(os.environ, {
        "API_BASE_URL": "https://8.8.8.8/api/v1", "API_ORIGIN": "https://8.8.8.8",
        "API_USERNAME": "fixture", "API_PASSWORD": "fixture-password", "API_TIMEOUT": "10",
    }):
        client = PaymentsClient()
        try:
            client._configure()
            cookie = SimpleCookie("session_id=fixture-session; Path=/; Secure; HttpOnly")
            jar = client._session.cookie_jar
            jar.update_cookies(cookie, response_url=URL("https://8.8.8.8/api/v1/auth/login"))
            assert "session_id" in jar.filter_cookies(URL("https://8.8.8.8/api/v1/auth/me"))
            assert "session_id" not in jar.filter_cookies(URL("http://8.8.8.8/api/v1/auth/me"))
            assert "session_id" not in jar.filter_cookies(URL("https://8.8.4.4/api/v1/auth/me"))
            print("PASS: public-IP session cookie is accepted only for its HTTPS host")
        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
