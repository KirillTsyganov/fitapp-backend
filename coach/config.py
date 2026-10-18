import os

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
# Overridable via Vercel env vars without a code change.
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.5')
# Reasoning models only; set to an empty string for models that reject the parameter.
OPENAI_REASONING_EFFORT = os.environ.get('OPENAI_REASONING_EFFORT', 'low')
# Per attempt; vercel.json maxDuration (60s) covers one attempt plus overhead, not two full timeouts.
OPENAI_TIMEOUT_SECONDS = float(os.environ.get('OPENAI_TIMEOUT_SECONDS', '35'))
