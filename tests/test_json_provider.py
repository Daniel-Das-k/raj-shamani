import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from knowledge.providers import GroqJSON


class JSONProviderTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
