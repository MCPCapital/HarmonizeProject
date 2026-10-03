import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest

from harmonize_core.observability import HealthFile, JsonFormatter, log_event


class ObservabilityTests(unittest.TestCase):
    def test_json_log_is_single_line_structured_and_redacted(self):
        secret = "private-client-key"
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(JsonFormatter((secret,)))
        logger = logging.getLogger("test.harmonize")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        log_event(
            logger,
            logging.INFO,
            "transport_failed",
            detail=f"key={secret}",
            attempt=2,
        )
        rendered = output.getvalue()
        self.assertEqual(rendered.count("\n"), 1)
        self.assertNotIn(secret, rendered)
        payload = json.loads(rendered)
        self.assertEqual(payload["event"], "transport_failed")
        self.assertEqual(payload["attempt"], 2)
        self.assertEqual(payload["detail"], "key=[REDACTED]")

    def test_health_file_replaces_atomically_with_nonsecret_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run" / "health.json"
            health = HealthFile(path)
            health.write({"state": "STARTING", "ready": False})
            health.write({"state": "STREAMING", "ready": True})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"state": "STREAMING", "ready": True},
            )
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)


if __name__ == "__main__":
    unittest.main()
