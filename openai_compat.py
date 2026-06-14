"""Compatibility shim around the real openai client.

Provides a drop-in OpenAI subclass that:
  - Injects base_url from OPENAI_BASE_URL when the caller doesn't pass one.
  - Rewrites the chat completion model from OPENAI_CHAT_MODEL on every call.
  - Routes audio (Whisper) traffic to a separate endpoint via
    WHISPER_BASE_URL / WHISPER_API_KEY while chat stays on the primary client.

This lets chat traffic go to GitHub Models / OpenRouter while audio traffic
still goes to a Whisper-capable endpoint, without touching call sites beyond
swapping the import.
"""

import os
import openai

_PatchedOpenAI = None


def _build_patched_class():
    base = openai.OpenAI

    class OpenAI(base):
        def __init__(self, *args, **kwargs):
            if "base_url" not in kwargs or kwargs.get("base_url") is None:
                env_base = os.getenv("OPENAI_BASE_URL")
                if env_base:
                    kwargs["base_url"] = env_base

            super().__init__(*args, **kwargs)

            chat_model = os.getenv("OPENAI_CHAT_MODEL")
            if chat_model:
                original_create = self.chat.completions.create

                def create_with_model(*c_args, **c_kwargs):
                    c_kwargs["model"] = chat_model
                    return original_create(*c_args, **c_kwargs)

                self.chat.completions.create = create_with_model

            whisper_base = os.getenv("WHISPER_BASE_URL")
            whisper_key = os.getenv("WHISPER_API_KEY")
            if whisper_base or whisper_key:
                whisper_kwargs = {}
                if whisper_base:
                    whisper_kwargs["base_url"] = whisper_base
                if whisper_key:
                    whisper_kwargs["api_key"] = whisper_key
                whisper_client = base(**whisper_kwargs)
                self.audio = whisper_client.audio

    return OpenAI


def _get_patched_class():
    global _PatchedOpenAI
    if _PatchedOpenAI is None:
        _PatchedOpenAI = _build_patched_class()
    return _PatchedOpenAI


OpenAI = _get_patched_class()
