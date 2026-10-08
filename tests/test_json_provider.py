import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from knowledge.caption_answers import TrialOpenAI
from knowledge.providers import GroqJSON, OpenAIJSON
from knowledge.request_timeout import AnswerTimeout, answer_deadline


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
        self.assertEqual(sdk.OpenAI.call_args.kwargs["timeout"], 120)
        self.assertEqual(sdk.OpenAI.call_args.kwargs["base_url"], "https://api.openai.com/v1")
        self.assertEqual(request["model"], "gpt-4.1-mini")
        self.assertNotIn('reasoning', request)
        self.assertEqual(request['max_output_tokens'], 4000)
        self.assertEqual(request['temperature'], 0)
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
        self.assertEqual(request['temperature'], 0)
        self.assertNotIn('reasoning', request)

    def test_empty_model_setting_uses_the_reader_default(self):
        with patch.dict('os.environ', {'OPENAI_CHAT_MODEL': ''}):
            self.assertEqual(OpenAIJSON().model_name, 'gpt-4.1-mini')

    def test_trial_openai_forwards_the_verification_schema_through_retries(self):
        schema = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
        error = RuntimeError('synthetic rate limit')
        error.status_code = 429
        error.response = SimpleNamespace(headers={'retry-after': '1'})
        with patch.object(OpenAIJSON, 'complete', side_effect=[error, {'ok': True}]) as complete, \
                patch('knowledge.caption_answers.time.sleep') as sleep:
            self.assertEqual(TrialOpenAI(1).complete('Verify.', {}, schema=schema), {'ok': True})
        self.assertEqual(complete.call_count, 2)
        for call in complete.call_args_list:
            self.assertEqual(call.kwargs['schema'], schema)
        sleep.assert_called_once_with(1.25)

    def test_provider_clients_share_the_remaining_answer_budget(self):
        groq = MagicMock()
        client = groq.Groq.return_value.__enter__.return_value
        client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{}'))])
        with patch('knowledge.request_timeout.time.monotonic', return_value=100) as clock:
            with answer_deadline(10):
                _, openai, _ = self.openai_response(SimpleNamespace(status="completed", output=[], output_text='{}'))
                self.assertEqual(openai.OpenAI.call_args.kwargs['timeout'], 10)
                clock.return_value = 107
                with patch.dict(sys.modules, {'groq': groq}), patch.dict('os.environ', {'GROQ_API_KEY': 'synthetic-test'}):
                    GroqJSON().complete('Test', {})
                self.assertEqual(groq.Groq.call_args.kwargs['timeout'], 3)

    def test_expired_budget_prevents_starting_another_provider_call(self):
        sdk = MagicMock()
        with patch.dict(sys.modules, {'openai': sdk}), patch.dict('os.environ', {'OPENAI_API_KEY': 'synthetic-test'}):
            with answer_deadline(0), self.assertRaises(AnswerTimeout):
                OpenAIJSON().complete('Test', {})
        sdk.OpenAI.assert_not_called()

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
