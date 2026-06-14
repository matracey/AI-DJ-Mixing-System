# Configuration

This fork of the AI DJ Mixing System adds several environment variables for
pluggable chat and Whisper backends. All of them are optional except
`OPENAI_API_KEY` (or the equivalent key for whichever backend you point at).
Set them in a `.env` file at the repo root or in your shell environment.

## Environment variables

### `OPENAI_API_KEY`
The API key used for the primary (chat) client and, unless overridden, the
audio/Whisper client. Still required for whichever backend you use. When
talking to an OpenAI-compatible gateway (GitHub Models, OpenRouter, etc.), this
holds that gateway's token rather than an OpenAI key.

### `OPENAI_BASE_URL`
Overrides the base URL of the primary chat client. When set, every `OpenAI`
client constructed through `openai_compat` is pointed at this endpoint unless
the caller explicitly passes its own `base_url`. Use it to route chat traffic to
GitHub Models, OpenRouter, a local proxy, or any OpenAI-compatible API.

### `OPENAI_CHAT_MODEL`
When set, this model name is forced onto every `chat.completions.create` call,
overriding whatever model the code requested. Handy when your gateway exposes a
model under a different name (e.g. `openai/gpt-4o-mini` on OpenRouter) than the
hardcoded `gpt-4o-mini` the pipeline asks for.

### `WHISPER_BACKEND`
Selects the transcription backend. One of:
- `local` (default) - run Whisper locally via `faster-whisper`.
- `openai` - call the OpenAI Whisper API (`whisper-1`).
- `disabled` - skip transcription entirely and return empty text, which makes
  the structure detector fall back to its energy-curve analysis.

### `WHISPER_MODEL`
The model size for the local `faster-whisper` backend. Defaults to `small`.
Common values: `tiny`, `base`, `small`, `medium`, `large-v3`. Larger models are
more accurate but slower and need more memory.

### `WHISPER_DEVICE`
Device for the local Whisper backend. Defaults to `cpu`. Set to `cuda` if you
have a compatible GPU and the CUDA libraries installed.

### `WHISPER_COMPUTE`
Compute type for the local Whisper backend. Defaults to `int8` (fast, low
memory, CPU-friendly). Other options include `int8_float16`, `float16`, and
`float32` depending on your hardware.

### `WHISPER_BASE_URL`
Base URL for a dedicated audio/Whisper endpoint. When set (together with or
instead of `WHISPER_API_KEY`), `openai_compat` builds a second client just for
audio and swaps it onto `client.audio`. This lets chat traffic go to one
provider (e.g. GitHub Models) while audio/Whisper traffic goes to a separate
Whisper-capable endpoint. Only relevant when `WHISPER_BACKEND=openai`.

### `WHISPER_API_KEY`
API key for the dedicated audio/Whisper endpoint described above. If only this
is set (without `WHISPER_BASE_URL`), the audio client uses the default OpenAI
endpoint with this key. Only relevant when `WHISPER_BACKEND=openai`.

## Example `.env` snippets

### OpenAI direct (defaults)
```dotenv
OPENAI_API_KEY=sk-your-openai-key
# Everything else uses defaults:
#   chat -> OpenAI, model as coded
#   whisper -> local faster-whisper (small, cpu, int8)
```

### GitHub Models + local Whisper
```dotenv
OPENAI_API_KEY=ghp_your_github_token
OPENAI_BASE_URL=https://models.inference.ai.azure.com
OPENAI_CHAT_MODEL=gpt-4o-mini
WHISPER_BACKEND=local
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE=int8
```

### OpenRouter + OpenAI Whisper
```dotenv
OPENAI_API_KEY=sk-or-your-openrouter-key
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_CHAT_MODEL=openai/gpt-4o-mini
WHISPER_BACKEND=openai
WHISPER_BASE_URL=https://api.openai.com/v1
WHISPER_API_KEY=sk-your-openai-key
```
