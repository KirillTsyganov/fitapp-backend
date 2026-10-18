import os

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
# Overridable via Vercel env vars without a code change.
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.5')
# Must stay below the serverless function's max duration.
OPENAI_TIMEOUT_SECONDS = float(os.environ.get('OPENAI_TIMEOUT_SECONDS', '50'))
