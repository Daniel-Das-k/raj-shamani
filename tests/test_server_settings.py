import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployment.aws_deploy import provider_configuration
from knowledge.providers import OpenAIJSON
from knowledge.server import load_settings


class ReaderSettingsTests(unittest.TestCase):
    def test_reader_loads_only_its_settings_and_preserves_literal_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text(
                'OPENAI_API_KEY="literal-${UNRELATED}"\n'
                'OPENAI_CHAT_MODEL=gpt-4.1-mini\n'
                'SUPERMEMORY_API_KEY=synthetic-search\n'
                'GROQ_API_KEY=obsolete\nDEEPGRAM_API_KEY=obsolete\nHF_TOKEN=obsolete\n'
                'AWS_SECRET_ACCESS_KEY=deployment-only\n')
            with patch('knowledge.server.ROOT', root), patch.dict(os.environ, {
                    'UNRELATED': 'expanded', 'OPENAI_CHAT_MODEL': 'previous-model'}, clear=True):
                load_settings()
                self.assertEqual(os.environ['OPENAI_API_KEY'], 'literal-${UNRELATED}')
                self.assertEqual(os.environ['SUPERMEMORY_API_KEY'], 'synthetic-search')
                self.assertEqual(OpenAIJSON().model_name, 'gpt-4.1-mini')
                for key in ('GROQ_API_KEY', 'DEEPGRAM_API_KEY', 'HF_TOKEN', 'AWS_SECRET_ACCESS_KEY'):
                    self.assertNotIn(key, os.environ)

    def test_deployment_uses_the_project_model_and_excludes_obsolete_credentials(self):
        result = provider_configuration({
            'OPENAI_API_KEY': 'synthetic-openai', 'OPENAI_CHAT_MODEL': 'gpt-4.1-mini',
            'SUPERMEMORY_API_KEY': 'synthetic-search', 'PUBLIC_AUTH_MODE': 'guest',
            'GROQ_API_KEY': 'obsolete', 'DEEPGRAM_API_KEY': 'obsolete', 'HF_TOKEN': 'obsolete',
        }, environ={'OPENAI_CHAT_MODEL': 'previous-model'})
        self.assertEqual(result, {
            'OPENAI_API_KEY': 'synthetic-openai', 'OPENAI_CHAT_MODEL': 'gpt-4.1-mini',
            'SUPERMEMORY_API_KEY': 'synthetic-search', 'PUBLIC_AUTH_MODE': 'guest',
        })
