"""Lazy provider clients, so local tests and CLI help need no model downloads."""
from __future__ import annotations

import json
import os
from pathlib import Path

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"


def require_key(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} in your environment or the repository .env file.")
    return value


class Embedder:
    model_name = EMBEDDING_MODEL

    def __init__(self, cache: Path):
        self.cache = cache
        self._model = None

    def encode(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, cache_folder=str(self.cache))
        prefix = "query: " if query else "passage: "
        return self._model.encode([prefix + text for text in texts], batch_size=16,
                                  normalize_embeddings=True, show_progress_bar=False).tolist()


class GroqJSON:
    @property
    def model_name(self):
        return os.getenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")

    def complete(self, system: str, data: dict) -> dict:
        from groq import Groq
        with Groq(api_key=require_key("GROQ_API_KEY"), max_retries=0, timeout=120) as client:
            response = client.chat.completions.create(
                model=self.model_name,
                temperature=0, max_completion_tokens=4000,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system + "\nReturn a valid JSON object only."},
                          {"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
            )
        if response.choices[0].finish_reason != "stop":
            raise RuntimeError("The answer was incomplete. Please retry with a narrower question.")
        result = json.loads(response.choices[0].message.content)
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object from the language model.")
        return result


class OpenAIJSON:
    @property
    def model_name(self):
        return os.getenv('OPENAI_CHAT_MODEL', 'gpt-4.1-mini')

    def complete(self, system: str, data: dict) -> dict:
        from openai import OpenAI
        with OpenAI(api_key=require_key('OPENAI_API_KEY'), base_url='https://api.openai.com/v1',
                    max_retries=0, timeout=120) as client:
            response = client.responses.create(
                model=self.model_name, temperature=0, max_output_tokens=4000,
                store=False, text={'format': {'type': 'json_object'}},
                instructions=system + '\nReturn a valid JSON object only.',
                input='Input JSON:\n' + json.dumps(data, ensure_ascii=False),
            )
        if response.status != 'completed':
            raise RuntimeError('The answer was incomplete. Please retry with a narrower question.')
        if any(getattr(part, 'type', None) == 'refusal' for item in response.output
               for part in getattr(item, 'content', [])):
            raise ValueError('The answer provider declined this request.')
        result = json.loads(response.output_text)
        if not isinstance(result, dict):
            raise ValueError('Expected a JSON object from the language model.')
        return result


def transcribe(audio_path: Path, params: dict) -> dict:
    import requests
    with audio_path.open("rb") as audio:
        response = requests.post(
            "https://api.deepgram.com/v1/listen", params=params,
            headers={"Authorization": f"Token {require_key('DEEPGRAM_API_KEY')}",
                     "Content-Type": "audio/flac"},
            data=audio, timeout=(30, 1800),
        )
    response.raise_for_status()
    return response.json()
