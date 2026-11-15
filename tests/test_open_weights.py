"""Spec drafting on Muse Spark Open (open weights) through a partner's OpenAI-compatible endpoint."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from expectrail import spec_writer
from expectrail.contracts import validate

SPEC = {"objects": {"player": {"prompt": "blue robot"}, "ground": {"prompt": "grass-topped ground"}},
        "assertion": {"type": "never-crosses", "object": "player",
                      "boundary": {"relativeTo": "ground", "edge": "top", "side": "above", "tolerancePx": 12}}}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SparkOpenSpecWriterTest(unittest.TestCase):
    def test_open_transport_request(self):
        seen = {}

        def fake(req, timeout):
            seen.update(url=req.full_url, auth=req.get_header("Authorization"), body=json.loads(req.data))
            return Resp(json.dumps({"choices": [{"message": {"content": json.dumps(SPEC)}}]}).encode())

        with mock.patch.dict(os.environ, {"EXPECTRAIL_SPEC_USD_CAP": "100"}), \
                mock.patch.object(spec_writer.urllib.request, "urlopen", fake):
            spec, problems = spec_writer.draft("The player never falls through the ground.", "x",
                                               spec_writer.OPEN_MODEL,
                                               transport=spec_writer.open_transport(key="bk"))
        self.assertEqual(problems, [])
        self.assertEqual(validate(spec), "test-spec")
        self.assertEqual(seen["url"], "https://inference.baseten.co/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer bk")
        self.assertEqual(seen["body"]["model"], "meta-models/muse-spark-open")
        self.assertNotIn("approval", spec)

    def test_schema_refusal_falls_back_to_json_mode(self):
        modes = []

        def fake(req, timeout):
            body = json.loads(req.data)
            modes.append(body["response_format"]["type"])
            if body["response_format"]["type"] == "json_schema":
                raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b"response_format"))
            return Resp(json.dumps({"choices": [{"message": {"content": json.dumps(SPEC)}}]}).encode())

        with mock.patch.dict(os.environ, {"EXPECTRAIL_SPEC_USD_CAP": "100"}), \
                mock.patch.object(spec_writer.urllib.request, "urlopen", fake):
            spec, _ = spec_writer.draft("The player never falls through the ground.", "x", spec_writer.OPEN_MODEL,
                                        transport=spec_writer.open_transport(key="bk"))
        self.assertIsNotNone(spec)
        self.assertEqual(modes, ["json_schema", "json_object"])

    def test_cli_needs_a_key_and_uses_spark_open(self):
        with mock.patch.dict(os.environ, {"BASETEN_API_KEY": "", "EXPECTRAIL_OPEN_API_KEY": ""}):
            self.assertEqual(spec_writer.main(["draft", "The player never falls.", "--endpoint", "open"]), 1)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"BASETEN_API_KEY": "bk"}):
            out = Path(tmp) / "draft.json"
            fake = lambda body: {"choices": [{"message": {"content": json.dumps(SPEC)}}]}  # noqa: E731
            with mock.patch.object(spec_writer, "open_transport", return_value=fake), \
                    mock.patch.object(spec_writer, "draft", wraps=spec_writer.draft) as drafted:
                rc = spec_writer.main(["draft", "The player never falls through the ground.", "--id", "p",
                                       "--endpoint", "open", "--out", str(out)])
            self.assertEqual(rc, 0)
            self.assertEqual(drafted.call_args.args[2], "meta-models/muse-spark-open")
            self.assertEqual(validate(json.loads(out.read_text())), "test-spec")


if __name__ == "__main__":
    unittest.main()
