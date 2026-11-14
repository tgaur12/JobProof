"""Deterministic regressions for refreshed shortener data and cache behavior."""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

import requests

from security.shortener_catalog import ShortenerCatalog


class ShortenerCatalogTests(unittest.TestCase):
    def setUp(self):
        self.fixture_root = Path(__file__).resolve().parents[1] / ".jobproof-cache" / "tests"
        self.fixture_root.mkdir(parents=True, exist_ok=True)
        temporary_directory = self.fixture_root / f"shortener-catalog-{uuid.uuid4().hex}"
        self.assertTrue(temporary_directory.is_relative_to(self.fixture_root))
        temporary_directory.mkdir()
        self.addCleanup(self._cleanup_fixture, temporary_directory)
        self.cache_path = temporary_directory / "catalog.json"
        self.source_url = "https://example.test/shorteners.json"
        self.now = 1_700_000_000.0

        clock_patch = patch("security.shortener_catalog.time.time", return_value=self.now)
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        request_patch = patch(
            "security.shortener_catalog.requests.get",
            side_effect=requests.Timeout("offline test"),
        )
        self.request = request_patch.start()
        self.addCleanup(request_patch.stop)

    def _cleanup_fixture(self, directory):
        self.assertTrue(directory.resolve().is_relative_to(self.fixture_root.resolve()))
        for child in directory.iterdir():
            if child.is_dir():
                self.assertFalse(any(child.iterdir()))
                try:
                    child.rmdir()
                except PermissionError:
                    pass
            else:
                child.unlink()
        try:
            directory.rmdir()
        except PermissionError:
            pass

    def _catalog(self, **overrides):
        options = {
            "source_url": self.source_url,
            "cache_path": self.cache_path,
            "ttl_seconds": 10,
            "retry_seconds": 5,
        }
        options.update(overrides)
        return ShortenerCatalog(**options)

    def _serve_payload(self, payload, status_code=200):
        response = requests.Response()
        response.status_code = status_code
        response.url = self.source_url
        response.encoding = "utf-8"
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(payload).encode("utf-8")
        response._content_consumed = True
        self.request.side_effect = None
        self.request.return_value = response

    def _serve(self, domains, status_code=200):
        self._serve_payload({"list": domains, "version": 1}, status_code)

    def _write_cache(self, domains, *, fetched_at=None, source_url=None):
        self.cache_path.write_text(
            json.dumps({
                "source_url": source_url or self.source_url,
                "fetched_at": self.now - 1 if fetched_at is None else fetched_at,
                "domains": domains,
            }),
            encoding="utf-8",
        )

    def test_lazy_download_and_fresh_cache_reuse(self):
        self._serve(["bit.ly"])
        catalog = self._catalog()
        self.request.assert_not_called()

        result = catalog.check("bit.ly")
        self.assertIs(result["is_shortener"], True)
        self.assertEqual(result["matched_domain"], "bit.ly")
        self.assertEqual(result["status"], "fresh")
        self.assertEqual(result["source_url"], self.source_url)
        self.assertEqual(result["fetched_at"], self.now)
        self.assertIsNone(result["error"])
        self.request.assert_called_once()
        self.assertEqual(self.request.call_args.kwargs["timeout"], (3, 5))
        self.assertIs(self.request.call_args.kwargs["allow_redirects"], False)

        self.request.reset_mock()
        result = self._catalog().check("unlisted.example.com")
        self.assertIs(result["is_shortener"], False)
        self.assertIsNone(result["matched_domain"])
        self.assertEqual(result["status"], "fresh")
        self.request.assert_not_called()

    def test_expired_catalog_replaces_removed_entries(self):
        self._serve(["bit.ly"])
        catalog = self._catalog()
        catalog.check("bit.ly")

        self.clock.return_value = self.now + 10
        self._serve(["tinyurl.com"])
        result = catalog.check("tinyurl.com")
        self.assertIs(result["is_shortener"], True)
        self.assertEqual(result["status"], "fresh")
        self.assertEqual(result["fetched_at"], self.now + 10)
        self.assertIs(catalog.check("bit.ly")["is_shortener"], False)
        self.assertEqual(self.request.call_count, 2)
        self.assertEqual(json.loads(self.cache_path.read_text())["domains"], ["tinyurl.com"])

    def test_force_refresh_bypasses_fresh_lifetime(self):
        self._serve(["bit.ly"])
        catalog = self._catalog()
        catalog.check("bit.ly")
        self._serve(["tinyurl.com"])

        result = catalog.check("tinyurl.com", force_refresh=True)
        self.assertIs(result["is_shortener"], True)
        self.assertIs(catalog.check("bit.ly")["is_shortener"], False)
        self.assertEqual(self.request.call_count, 2)

    def test_label_boundaries_and_deep_host_specificity(self):
        self._serve(["bit.ly", "links.example.com", "deep.links.example.com"])
        catalog = self._catalog()
        for hostname, matched_domain in [
            ("bit.ly", "bit.ly"),
            ("jobs.bit.ly", "bit.ly"),
            ("links.example.com", "links.example.com"),
            ("jobs.links.example.com", "links.example.com"),
            ("deep.links.example.com", "deep.links.example.com"),
            ("bit.ly.attacker.net", None),
            ("notbit.ly", None),
            ("example.com", None),
            ("jobs.example.com", None),
        ]:
            with self.subTest(hostname=hostname):
                result = catalog.check(hostname)
                self.assertEqual(result["matched_domain"], matched_domain)
                self.assertEqual(result["is_shortener"], matched_domain is not None)
        self.request.assert_called_once()

    def test_private_suffix_and_unicode_hostname_normalization(self):
        self._serve(["PAGE.LINK", "b\u00fccher.de"])
        catalog = self._catalog()
        for hostname, matched_domain in [
            ("jobs.page.link", "page.link"),
            ("B\u00dcCHER.DE.", "xn--bcher-kva.de"),
            ("b\u00fccher\u3002de", "xn--bcher-kva.de"),
        ]:
            with self.subTest(hostname=hostname):
                result = catalog.check(hostname)
                self.assertIs(result["is_shortener"], True)
                self.assertEqual(result["matched_domain"], matched_domain)

    def test_stale_members_match_while_nonmembers_remain_unknown(self):
        self._write_cache(["bit.ly"], fetched_at=self.now - 20)
        catalog = self._catalog()

        known = catalog.check("bit.ly")
        unknown = catalog.check("unlisted.example.com")
        self.assertIs(known["is_shortener"], True)
        self.assertEqual(known["matched_domain"], "bit.ly")
        self.assertIsNone(unknown["is_shortener"])
        self.assertIsNone(unknown["matched_domain"])
        for result in (known, unknown):
            self.assertEqual(result["status"], "stale")
            self.assertEqual(result["fetched_at"], self.now - 20)
            self.assertTrue(result["error"])
        self.request.assert_called_once()

    def test_unavailable_data_retries_after_cooldown(self):
        catalog = self._catalog()
        for hostname in ["bit.ly", "unlisted.example.com"]:
            result = catalog.check(hostname)
            self.assertIsNone(result["is_shortener"])
            self.assertIsNone(result["matched_domain"])
            self.assertIsNone(result["fetched_at"])
            self.assertEqual(result["status"], "unavailable")
            self.assertTrue(result["error"])
        self.request.assert_called_once()

        self.clock.return_value = self.now + 5
        self._serve(["bit.ly"])
        result = catalog.check("bit.ly")
        self.assertIs(result["is_shortener"], True)
        self.assertEqual(result["status"], "fresh")
        self.assertIsNone(result["error"])
        self.assertEqual(self.request.call_count, 2)

    def test_source_change_does_not_reuse_another_sources_cache(self):
        self._write_cache(["bit.ly"])
        other_source = "https://other.example.test/shorteners.json"
        result = self._catalog(source_url=other_source).check("bit.ly")
        self.assertIsNone(result["is_shortener"])
        self.assertIsNone(result["fetched_at"])
        self.assertEqual(result["source_url"], other_source)
        self.assertEqual(result["status"], "unavailable")
        self.request.assert_called_once()

    def test_corrupt_or_invalid_cache_is_not_used(self):
        valid_cache = {
            "source_url": self.source_url,
            "fetched_at": self.now - 1,
            "domains": ["bit.ly"],
        }
        invalid_values = [
            [],
            {**valid_cache, "fetched_at": self.now + 1},
            {**valid_cache, "fetched_at": float("nan")},
            {**valid_cache, "fetched_at": float("inf")},
            {**valid_cache, "fetched_at": 10 ** 1000},
            {**valid_cache, "fetched_at": True},
            {**valid_cache, "fetched_at": "yesterday"},
            {**valid_cache, "domains": "bit.ly"},
            {**valid_cache, "domains": []},
            {**valid_cache, "domains": ["bit.ly", "com"]},
            {**valid_cache, "domains": ["bit.ly", "bad_host.com"]},
        ]
        for value in invalid_values:
            with self.subTest(cache=value):
                self.cache_path.write_text(json.dumps(value), encoding="utf-8")
                self.assertEqual(self._catalog().check("bit.ly")["status"], "unavailable")
        self.cache_path.write_text("{broken JSON", encoding="utf-8")
        self.assertEqual(self._catalog().check("bit.ly")["status"], "unavailable")

    def test_invalid_feed_preserves_last_good_cache(self):
        for payload in [
            None, [], {}, {"list": []}, {"list": "bit.ly"},
            {"list": ["com"]}, {"list": [42]},
            {"list": ["bit.ly", "https://example.com"]},
        ]:
            with self.subTest(payload=payload):
                self._write_cache(["bit.ly"], fetched_at=self.now - 20)
                previous_cache = self.cache_path.read_bytes()
                self._serve_payload(payload)
                result = self._catalog().check("bit.ly")
                self.assertIs(result["is_shortener"], True)
                self.assertEqual(result["status"], "stale")
                self.assertTrue(result["error"])
                self.assertEqual(self.cache_path.read_bytes(), previous_cache)

    def test_http_failure_does_not_publish_response_domains(self):
        self._serve(["bit.ly"], status_code=503)
        result = self._catalog().check("bit.ly")
        self.assertIsNone(result["is_shortener"])
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(result["error"])
        self.assertFalse(self.cache_path.exists())

    def test_disk_write_failure_keeps_downloaded_memory_snapshot(self):
        self.cache_path.mkdir()
        self._serve(["bit.ly"])
        catalog = self._catalog()

        result = catalog.check("bit.ly")
        self.assertIs(result["is_shortener"], True)
        self.assertEqual(result["status"], "fresh")
        self.assertTrue(result["error"])
        self.assertIs(catalog.check("unlisted.example.com")["is_shortener"], False)
        self.request.assert_called_once()

    def test_atomic_replacement_uses_unique_completed_temporary_files(self):
        self._write_cache(["old.example.com"], fetched_at=self.now - 20)
        temporary_paths = []
        original_replace = os.replace

        def observe_replace(source, destination):
            source = Path(source)
            self.assertEqual(source.parent, self.cache_path.parent)
            self.assertNotEqual(source, self.cache_path)
            self.assertEqual(Path(destination), self.cache_path)
            self.assertIn("domains", json.loads(self.cache_path.read_text()))
            self.assertIn("domains", json.loads(source.read_text()))
            temporary_paths.append(source)
            return original_replace(source, destination)

        catalog = self._catalog()
        with patch("security.shortener_catalog.os.replace", side_effect=observe_replace):
            self._serve(["bit.ly"])
            self.assertIs(catalog.check("bit.ly")["is_shortener"], True)
            self._serve(["tinyurl.com"])
            self.assertIs(catalog.check("tinyurl.com", force_refresh=True)["is_shortener"], True)

        self.assertEqual(len(temporary_paths), 2)
        self.assertNotEqual(temporary_paths[0], temporary_paths[1])
        self.assertEqual(list(self.cache_path.parent.iterdir()), [self.cache_path])
        self.assertEqual(json.loads(self.cache_path.read_text())["domains"], ["tinyurl.com"])

    def test_ip_addresses_skip_catalog_io(self):
        catalog = self._catalog()
        for hostname in ["192.0.2.1", "2001:db8::1"]:
            with self.subTest(hostname=hostname):
                result = catalog.check(hostname)
                self.assertIs(result["is_shortener"], False)
                self.assertIsNone(result["matched_domain"])
                self.assertEqual(result["status"], "not_applicable")
        self.request.assert_not_called()
        self.assertFalse(self.cache_path.exists())

    def test_invalid_configuration_is_visible(self):
        for options in [
            {"source_url": "http://example.test/list.json"},
            {"source_url": "https://user:password@example.test/list.json"},
            {"ttl_seconds": 0}, {"ttl_seconds": float("nan")},
            {"retry_seconds": -1}, {"retry_seconds": float("inf")},
        ]:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    self._catalog(**options)
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
