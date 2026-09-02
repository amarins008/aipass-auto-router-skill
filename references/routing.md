# Task-Class to Model Priority Mapping

These are the **actual model names discovered via CDP scan of ThaiAI-Pass** (Sep 2026). Priority 1 = highest preference. The bridge uses this file as the priority list — edit it to change routing behavior.

The 32 models on ThaiAI-Pass as of Sep 2026:
- Gemini 3.1 Flash Lite, Gemini 3.7 Flash, Gemini 3.1 Pro (Preview)
- Claude Sonnet 5, Claude Opus 5
- GPT-5.6 Terra, GPT-5.6 Sol
- o3 Deep Research
- DeepSeek V3.2, Grok 4.3, Qwen3-Next, GLM 5.2, Kimi K2.7 Code
- Sonar, Sonar Reasoning Pro, Sonar Deep Research
- Llama 4 Maverick, Llama 4 Scout
- MiniMax M2, Mistral Large 3, Mistral Medium 3
- Pathumma ThaiLLM 8B
- Seedream 4.0, Seedream 5.0 Lite
- Seedance 2.0 Mini, Seedance 2.0 Fast, Seedance 2.0
- Nano Banana, Nano Banana Pro
- Veo 3.1 Fast
- Lyria 3 Clip, Lyria 3 Pro

---

## code
Models optimized for code generation, debugging, and technical tasks.

- Claude Opus 5
- Kimi K2.7 Code
- DeepSeek V3.2
- Claude Sonnet 5
- GPT-5.6 Terra
- Llama 4 Scout
- Mistral Large 3
- Qwen3-Next

## deep-reasoning
Models with strong reasoning, chain-of-thought, and complex problem solving.

- Claude Opus 5
- Claude Sonnet 5
- o3 Deep Research
- Sonar Reasoning Pro
- Sonar Deep Research
- DeepSeek V3.2
- GPT-5.6 Terra

## thai-content
Models with strong Thai language understanding and generation.

- Pathumma ThaiLLM 8B
- Claude Sonnet 5
- Claude Opus 5
- Gemini 3.7 Flash
- GPT-5.6 Terra
- Llama 4 Maverick

## fast
Models optimized for speed and low latency (text chat). Video/audio "Fast" variants are NOT included here — those route under `video` / `audio`.

- Gemini 3.1 Flash Lite
- Gemini 3.7 Flash
- Llama 4 Scout
- Qwen3-Next
- MiniMax M2
- Mistral Medium 3

## research
Models with broad knowledge, long context, and research capabilities.

- o3 Deep Research
- Sonar Deep Research
- Claude Opus 5
- Claude Sonnet 5
- GPT-5.6 Sol
- Gemini 3.1 Pro (Preview)
- Sonar Reasoning Pro

## music
Text-to-music generation.

- Lyria 3 Pro
- Lyria 3 Clip

## image-thai
Image generation with strong Thai text rendering. Use when the image needs to contain readable Thai characters (signs, posters, text overlays, etc.). Models listed here are tested for Thai typography accuracy.
- Nano Banana Pro
- Nano Banana
- Seedream 5.0 Lite
- Seedream 4.0

## image
Image generation from text prompts. Returns base64/URL in the assistant message.
- Nano Banana Pro
- Nano Banana
- Seedream 5.0 Lite
- Seedream 4.0

## video
Text-to-video generation. Higher latency than image.

- Veo 3.1 Fast      (quick previews / drafts)
- Seedance 2.0 Mini (budget / short clips)
- Seedance 2.0 Fast (balanced)
- Seedance 2.0      (best quality, slower)

## audio
Audio/speech generation (TTS, voice).

- Lyria 3 Pro
- Lyria 3 Clip
- (TTS models in ThaiAI-Pass; if unavailable, fall back to text)

---

- **Auto-routing uses the EXACT model name** (e.g., "Claude Sonnet 5") as the model ID — no slug translation.
- Cooldowns (15 min default) are tracked per-model in `state/model_status.json`.
- The `infer_task_classes()` heuristic is a fallback; explicit ordering here overrides it.
- If ThaiAI-Pass adds/removes models, re-run `python scripts/check_models.py --scan` and update this file.
- Models that are image/video/audio (Seedream, Seedance, Veo, Lyria, Nano Banana) are NOT routed by text task classes. Use `/aipass-scan` to discover them and pick manually.