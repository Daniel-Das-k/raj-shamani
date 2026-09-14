import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from knowledge.providers import GroqJSON, OpenAIJSON


class JSONProviderTests(unittest.TestCase):
    def openai_response(self, response, model=None, schema=None):
        sdk = MagicMock()
        client = sdk.OpenAI.return_value.__enter__.return_value
        client.responses.create.return_value = response
        env = {"OPENAI_API_KEY": "synthetic-openai", "GROQ_API_KEY": "synthetic-groq",
               "OPENAI_BASE_URL": "https://unrelated-provider.invalid/v1"}
        if model:
            env["OPENAI_CHAT_MODEL"] = model
        with patch.dict(sys.modules, {"openai": sdk}), patch.dict("os.environ", env, clear=True):
            result = OpenAIJSON().complete("Verify claims.", {"question": "क्या कहा?"}, schema=schema)
        return result, sdk, client.responses.create.call_args.kwargs

    def test_openai_uses_own_key_and_responses_json_without_storing(self):
        result, sdk, request = self.openai_response(SimpleNamespace(
            status="completed", output=[], output_text='{"checks":[]}'))
        self.assertEqual(result, {"checks": []})
        self.assertEqual(sdk.OpenAI.call_args.kwargs["api_key"], "synthetic-openai")
        self.assertEqual(sdk.OpenAI.call_args.kwargs["max_retries"], 0)
        self.assertEqual(sdk.OpenAI.call_args.kwargs["base_url"], "https://api.openai.com/v1")
        self.assertEqual(request["model"], "gpt-4.1-mini")
        self.assertFalse(request["store"])
        self.assertEqual(request["text"], {"format": {"type": "json_object"}})
        self.assertIn("JSON", request["instructions"])
        self.assertIn('English only', request['instructions'])
        self.assertIn('respond in another language', request['instructions'])
        self.assertIn("JSON", request["input"])
        self.assertIn("क्या कहा?", request["input"])

    def test_openai_honors_configured_model(self):
        _, _, request = self.openai_response(SimpleNamespace(
            status="completed", output=[], output_text='{}'), model="configured-model")
        self.assertEqual(request["model"], "configured-model")

    def test_schema_is_sent_as_strict_structured_output(self):
        schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        _, _, request = self.openai_response(SimpleNamespace(status="completed", output=[], output_text='{}'), schema=schema)
        self.assertEqual(request["text"]["format"], {"type": "json_schema", "name": "evidence_checks", "strict": True, "schema": schema})

    def test_openai_rejects_incomplete_refused_and_malformed_outputs(self):
        cases = [
            (SimpleNamespace(status="incomplete"), RuntimeError),
            (SimpleNamespace(status="completed", output=[SimpleNamespace(content=[
                SimpleNamespace(type="refusal")])], output_text='{}'), ValueError),
            (SimpleNamespace(status="completed", output=[], output_text='[]'), ValueError),
            (SimpleNamespace(status="completed", output=[], output_text='not json'), ValueError),
        ]
        for response, error in cases:
            with self.subTest(response=response), self.assertRaises(error):
                self.openai_response(response)

    def test_json_mode_always_has_explicit_json_instruction(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"checks":[]}'))])
        sdk = MagicMock()
        sdk.Groq.return_value.__enter__.return_value = client
        with patch.dict(sys.modules, {"groq": sdk}), patch.dict("os.environ", {"GROQ_API_KEY": "synthetic-test"}):
            self.assertEqual(GroqJSON().complete("Verify these claims.", {}), {"checks": []})
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertIn("JSON", request["messages"][0]["content"])
        self.assertIn('English only', request['messages'][0]['content'])


if __name__ == "__main__":
    unittest.main()
