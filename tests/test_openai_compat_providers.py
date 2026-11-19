"""Provider selection checks without credentials or network requests."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI


RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts/llm-eval/run/run_sequential_openai_compat.py"
)
spec = importlib.util.spec_from_file_location("openai_compat_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
# Do not load the user's actual credentials during tests.
with patch("dotenv.load_dotenv"):
    spec.loader.exec_module(runner)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.config_path = self.root / "providers.json"
        self.providers = json.loads(runner.PROVIDERS_CONFIG_PATH.read_text(encoding="utf-8"))
        self.providers["custom"] = {
            "base_url": "https://custom.example/v1",
            "api_key_env": "CUSTOM_API_KEY",
            "response_fields": {
                "response": "result.answer",
                "reasoning_details": "result.trace",
            },
        }
        self.write_config(self.providers)
        config_patch = patch.object(runner, "PROVIDERS_CONFIG_PATH", self.config_path)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def write_config(self, config):
        self.config_path.write_text(json.dumps(config), encoding="utf-8")

    def test_selected_provider_pairs_its_url_and_key(self):
        os.environ.update({
            "OPENROUTER_API_KEY": "test-openrouter-key",
            "DEEPINFRA_API_KEY": "test-deepinfra-key",
            "CUSTOM_API_KEY": "test-custom-key",
            "OPENAI_COMPAT_API_KEY": "test-old-key",
            "OPENAI_COMPAT_BASE_URL": "https://old.example/v1",
        })
        for name, config in self.providers.items():
            with self.subTest(provider=name), patch.object(runner, "OpenAI") as client:
                runner._create_client(runner._load_provider(name))
                client.assert_called_once_with(
                    api_key=os.environ[config["api_key_env"]],
                    base_url=config["base_url"],
                )

    def test_missing_selected_key_never_falls_back(self):
        os.environ.update({
            "DEEPINFRA_API_KEY": "test-other-service-key",
            "OPENAI_COMPAT_API_KEY": "test-old-key",
        })
        for value in (None, "", "   "):
            with self.subTest(value=value), patch.object(runner, "OpenAI") as client:
                if value is not None:
                    os.environ["OPENROUTER_API_KEY"] = value
                with self.assertRaisesRegex(SystemExit, "OPENROUTER_API_KEY is required"):
                    runner._create_client(runner._load_provider("openrouter"))
                client.assert_not_called()

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "Unknown provider: missing"):
            runner._load_provider("missing")

    def test_invalid_provider_configuration_is_rejected(self):
        for invalid in ([], {"custom": None}, {"custom": {}},
                        {"custom": {"base_url": "", "api_key_env": "KEY"}},
                        {"custom": {"base_url": "https://custom.example", "api_key_env": 1}}):
            with self.subTest(config=invalid):
                self.write_config(invalid)
                with self.assertRaises(SystemExit):
                    runner._load_provider("custom")

    def test_unreadable_or_malformed_configuration_is_rejected(self):
        self.config_path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "Cannot read providers.json"):
            runner._load_provider("custom")
        self.config_path.unlink()
        with self.assertRaisesRegex(SystemExit, "Cannot read providers.json"):
            runner._load_provider("custom")

    def test_invalid_response_mapping_and_request_body_are_rejected(self):
        for field, value in (
            ("response_fields", {}),
            ("response_fields", {"response": "choices..content"}),
            ("response_fields", {"response": 123}),
            ("response_fields", {"response": "content", "id": "id"}),
            ("response_fields", {"response": "content", "raw_response": "data"}),
            ("extra_body", []),
            ("extra_body", {"stream": True}),
            ("extra_body", {"model": "other-model"}),
        ):
            with self.subTest(field=field, value=value):
                config = {**self.providers["custom"], field: value}
                self.write_config({"custom": config})
                with self.assertRaises(SystemExit):
                    runner._load_provider("custom")

    def test_provider_argument_is_required(self):
        with patch("sys.argv", [str(RUNNER_PATH)]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                runner.main()
            self.assertEqual(exc.exception.code, 2)

    def test_dry_run_needs_no_key_and_creates_no_client(self):
        queue = self.root / "queues" / "test"
        queue.mkdir(parents=True)
        request = queue / "seq__gpt-oss-20b__NRP-full__rva__rdfs2.jsonl"
        request.write_text(json.dumps({
            "id": "test", "model": "custom/model", "input": "test"
        }) + "\n", encoding="utf-8")
        argv = [
            str(RUNNER_PATH), "--provider", "custom", "--queue", "test",
            "--queue-base", str(queue.parent),
            "--response-root", str(self.root / "responses"), "--dry-run",
        ]
        with patch("sys.argv", argv), patch.object(runner, "_create_client") as client:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(), 0)
            self.assertIn("Provider: custom", output.getvalue())
            self.assertIn("dry-run", output.getvalue())
            client.assert_not_called()
        self.assertFalse((self.root / "responses").exists())

    def save_responses(self, provider_name, payloads):
        """Exercise real SDK parsing and JSONL writing with an in-memory HTTP transport."""
        provider = runner._load_provider(provider_name)
        responses = iter(payloads)
        requests = []

        def handle(request):
            requests.append(json.loads(request.content))
            payload = next(responses)
            status, body = payload if isinstance(payload, tuple) else (200, payload)
            return httpx.Response(status, json=body)

        request_path = self.root / "seq__test-model__NRP-full__rva__rdfs2.jsonl"
        request_path.write_text(json.dumps({
            "id": "request-1", "model": "test/model", "input": "test"
        }) + "\n", encoding="utf-8")
        response_root = self.root / "responses"
        with OpenAI(
            api_key="test-key", base_url=provider["base_url"], max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        ) as client, patch.object(runner.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            runner.run_file(
                req_path=request_path, client=client, provider=provider,
                response_root=response_root, overwrite=False, verbose=False,
                file_idx=1, total_files=1,
                global_stats={"processed": 0, "total": 1, "start": runner.time.time()},
            )
        files = list(response_root.rglob("*.jsonl"))
        self.assertEqual(len(files), 1)
        lines = files[0].read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        return json.loads(lines[0]), requests

    @staticmethod
    def completion(content="<Alice, rdf:type, Person>", **message_fields):
        return {
            "id": "generation-test", "object": "chat.completion", "created": 1,
            "model": "test/model", "provider": "TestProvider",
            "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, **message_fields},
            }],
            "usage": {
                "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30,
                "completion_tokens_details": {"reasoning_tokens": 15}, "cost": 0.001,
            },
            "new_api_field": {"preserve": True},
        }

    def test_openrouter_trace_and_full_response_survive_sdk_and_jsonl(self):
        trace = [
            {"type": "reasoning.text", "text": "推論\nステップ", "signature": "test-signature"},
            {"type": "reasoning.summary", "summary": "Summary"},
            {"type": "reasoning.encrypted", "data": "test-encrypted-data"},
        ]
        payload = self.completion(reasoning="推論\nステップ", reasoning_details=trace)
        row, requests = self.save_responses("openrouter", [payload])
        self.assertEqual(row["id"], "request-1")
        self.assertEqual(row["completion_id"], "generation-test")
        self.assertEqual(row["response"], "<Alice, rdf:type, Person>")
        self.assertEqual(row["reasoning"], "推論\nステップ")
        self.assertEqual(row["reasoning_details"], trace)
        self.assertEqual(row["usage"], payload["usage"])
        self.assertEqual(row["finish_reason"], "stop")
        self.assertEqual(row["model"], "test/model")
        self.assertEqual(row["provider"], "TestProvider")
        self.assertEqual(row["raw_response"], payload)
        self.assertNotIn("reasoning_content", row)
        self.assertNotIn("error", row)
        self.assertEqual(requests[0]["reasoning"], {"exclude": False})
        self.assertEqual(row["request_extra_body"], {"reasoning": {"exclude": False}})
        self.assertEqual(requests[0]["model"], "test/model")
        # The existing evaluator must continue to score only the final answer.
        eval_spec = importlib.util.spec_from_file_location(
            "evaluate_outputs", RUNNER_PATH.parents[1] / "eval/evaluate_outputs.py"
        )
        evaluator = importlib.util.module_from_spec(eval_spec)
        eval_spec.loader.exec_module(evaluator)
        self.assertEqual(evaluator._extract_output(row), row["response"])

    def test_deepinfra_reasoning_content_is_preserved(self):
        payload = self.completion(reasoning_content="DeepInfra trace")
        row, requests = self.save_responses("deepinfra", [payload])
        self.assertEqual(row["reasoning_content"], "DeepInfra trace")
        self.assertEqual(row["raw_response"], payload)
        self.assertNotIn("reasoning", requests[0])

    def test_custom_json_paths_and_request_settings_need_no_code_changes(self):
        self.providers["custom"]["extra_body"] = {"reasoning": {"enabled": True}}
        self.write_config(self.providers)
        payload = {"result": {"answer": "answer", "trace": [{"step": 1}]}}
        row, requests = self.save_responses("custom", [payload])
        self.assertEqual(row["response"], "answer")
        self.assertEqual(row["reasoning_details"], [{"step": 1}])
        self.assertEqual(row["raw_response"], payload)
        self.assertEqual(requests[0]["reasoning"], {"enabled": True})

    def test_null_trace_is_preserved_and_missing_trace_is_not_invented(self):
        payload = self.completion(reasoning=None)
        row, _ = self.save_responses("openrouter", [payload])
        self.assertIsNone(row["reasoning"])
        self.assertNotIn("reasoning_details", row)
        self.assertEqual(row["raw_response"], payload)

    def test_retries_keep_earlier_traces_without_replacing_final_answer(self):
        first = self.completion(content=None, reasoning="Earlier attempt trace")
        final = self.completion(reasoning="Final attempt trace")
        row, requests = self.save_responses("openrouter", [first, final])
        self.assertEqual(len(requests), 2)
        self.assertEqual(row["reasoning"], "Final attempt trace")
        self.assertEqual(row["raw_response"], final)
        self.assertEqual(row["attempts"][0]["raw_response"], first)
        self.assertEqual(row["attempts"][1]["raw_response"], final)
        self.assertNotIn("error", row)

    def test_exhausted_empty_responses_keep_trace_and_error(self):
        payload = self.completion(content=None, reasoning="Trace without final answer")
        row, requests = self.save_responses("openrouter", [payload] * 5)
        self.assertEqual(len(requests), 5)
        self.assertEqual(row["response"], "")
        self.assertEqual(row["reasoning"], "Trace without final answer")
        self.assertEqual(row["raw_response"], payload)
        self.assertEqual(row["error"]["type"], "EmptyResponse")
        self.assertEqual(len(row["attempts"]), 5)

    def test_api_errors_do_not_discard_an_earlier_trace(self):
        payload = self.completion(content=None, reasoning="Trace before API errors")
        api_error = (429, {"error": {"message": "Test rate limit", "code": 429}})
        row, _ = self.save_responses("openrouter", [payload] + [api_error] * 4)
        self.assertEqual(row["response"], "")
        self.assertEqual(row["reasoning"], "Trace before API errors")
        self.assertEqual(row["raw_response"], payload)
        self.assertEqual(row["error"]["type"], "RateLimitError")
        self.assertEqual(row["error"]["status_code"], 429)
        self.assertEqual(row["error"]["body"], api_error[1])
        self.assertEqual(len(row["attempts"]), 5)


if __name__ == "__main__":
    unittest.main()
