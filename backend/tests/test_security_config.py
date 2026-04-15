import asyncio
import importlib
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import contextmanager

import httpx


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@contextmanager
def temporary_environment(overrides: dict[str, str], removals: list[str] | None = None):
    removals = removals or []
    previous: dict[str, tuple[bool, str | None]] = {}

    for key in set(overrides) | set(removals):
        previous[key] = (key in os.environ, os.environ.get(key))

    try:
        for key in removals:
            os.environ.pop(key, None)
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, (existed, value) in previous.items():
            if existed and value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)


def reload_backend_modules():
    config = importlib.import_module("config")
    api_router = importlib.import_module("api.router")
    main = importlib.import_module("main")

    config = importlib.reload(config)
    api_router = importlib.reload(api_router)
    main = importlib.reload(main)
    return config, api_router, main


class BackendSecurityConfigTests(unittest.TestCase):
    def test_development_defaults_allow_local_origins_and_docs(self):
        with tempfile.TemporaryDirectory() as storage_root:
            with temporary_environment(
                {
                    "APP_ENV": "development",
                    "STORAGE_ROOT": storage_root,
                },
                removals=[
                    "API_DOCS_ENABLED",
                    "HEALTH_DETAILS_ENABLED",
                    "CORS_ORIGINS",
                    "TRUSTED_HOSTS",
                    "CORS_ALLOW_CREDENTIALS",
                ],
            ):
                import config

                settings = config.Settings()

                self.assertTrue(settings.API_DOCS_ENABLED)
                self.assertTrue(settings.HEALTH_DETAILS_ENABLED)
                self.assertIn("http://localhost:5173", settings.CORS_ORIGINS)
                self.assertIn("localhost", settings.TRUSTED_HOSTS)
                self.assertFalse(settings.CORS_ALLOW_CREDENTIALS)

    def test_production_rejects_wildcard_cors(self):
        with tempfile.TemporaryDirectory() as storage_root:
            with temporary_environment(
                {
                    "APP_ENV": "production",
                    "STORAGE_ROOT": storage_root,
                    "CORS_ORIGINS": "*",
                },
            ):
                import config

                with self.assertRaises(RuntimeError):
                    config.Settings()

    def test_production_app_hides_docs_and_limits_public_health_data(self):
        with tempfile.TemporaryDirectory() as storage_root:
            with temporary_environment(
                {
                    "APP_ENV": "production",
                    "STORAGE_ROOT": storage_root,
                    "CORS_ORIGINS": "https://app.example.com",
                    "TRUSTED_HOSTS": "api.example.com",
                },
                removals=[
                    "API_DOCS_ENABLED",
                    "HEALTH_DETAILS_ENABLED",
                    "CORS_ALLOW_CREDENTIALS",
                ],
            ):
                config, _, main = reload_backend_modules()
                asyncio.run(self._assert_production_app_surface(main.app, config.settings.APP_VERSION))

    async def _assert_production_app_surface(self, app, app_version: str) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.example.com",
        ) as client:
            docs_response = await client.get("/docs")
            self.assertEqual(docs_response.status_code, 404)

            root_health = await client.get("/health")
            self.assertEqual(root_health.json(), {"status": "healthy"})

            api_health = await client.get("/api/v1/health")
            self.assertEqual(
                api_health.json(),
                {
                    "status": "healthy",
                    "version": app_version,
                },
            )

            allowed = await client.get(
                "/api/v1/health",
                headers={"Origin": "https://app.example.com"},
            )
            self.assertEqual(
                allowed.headers.get("access-control-allow-origin"),
                "https://app.example.com",
            )
            self.assertEqual(allowed.headers.get("x-content-type-options"), "nosniff")
            self.assertEqual(allowed.headers.get("x-frame-options"), "DENY")

            blocked = await client.get(
                "/api/v1/health",
                headers={"Origin": "https://evil.example.com"},
            )
            self.assertIsNone(blocked.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()
