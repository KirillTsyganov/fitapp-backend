"""OpenAI orchestration: memory -> pre-checks -> structured generation -> post-validation."""
from openai import OpenAI, OpenAIError

from schemas import CoachChatRequest, CoachRoutineRequest, CoachWorkoutResponse

from . import memory, rules
from .config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TIMEOUT_SECONDS
from .prompts import FEW_SHOT_MESSAGES, SYSTEM_PROMPT

MAX_ATTEMPTS = 2
ROUTINE_REQUEST_MESSAGE = "Generate my full session for today."


class CoachError(Exception):
    """Raised with a client-safe message when the coach cannot produce a response."""


def _client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise CoachError('Coach is not configured.')
    return OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS)


def _parse(client: OpenAI, messages: list[dict]) -> CoachWorkoutResponse:
    try:
        completion = client.beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=messages,
            response_format=CoachWorkoutResponse,
        )
    except OpenAIError as exc:
        raise CoachError('Coach service is unavailable.') from exc

    message = completion.choices[0].message
    if message.refusal:
        raise CoachError('The coach declined this request.')
    if message.parsed is None:
        raise CoachError('Coach returned an unreadable response.')
    return message.parsed


def _build_context_message(
    snapshot: memory.UserSnapshot,
    equipment: list[str],
    duration_minutes: int | None,
) -> str:
    constraints = rules.pre_generation_constraints(snapshot)
    parts = [
        memory.format_context(snapshot),
        '',
        '## Constraints',
        *(f'- {c}' for c in constraints or ['none']),
        '',
        '## Session parameters',
        f"- Available equipment: {', '.join(equipment) or 'not specified (assume bodyweight only)'}",
        f'- Target duration: {duration_minutes or 45} minutes',
    ]
    return '\n'.join(parts)


def _generate(
    user_id: int,
    user_message: str,
    equipment: list[str] | None,
    duration_minutes: int | None,
    overrides: dict | None,
) -> CoachWorkoutResponse:
    snapshot = memory.get_user_snapshot(user_id, overrides)
    context = _build_context_message(snapshot, memory.clean_list(equipment), duration_minutes)

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        *FEW_SHOT_MESSAGES,
        {'role': 'system', 'content': context},
        {'role': 'user', 'content': user_message},
    ]

    client = _client()
    for _ in range(MAX_ATTEMPTS):
        response = _parse(client, messages)
        violations = rules.validate_workout(response)
        if not violations:
            return response
        messages = [
            *messages,
            {'role': 'assistant', 'content': response.model_dump_json()},
            {
                'role': 'user',
                'content': 'The workout broke these rules; return a corrected full response:\n'
                + '\n'.join(f'- {v}' for v in violations),
            },
        ]
    raise CoachError('Could not produce a workout that passes safety checks.')


def chat(user_id: int, req: CoachChatRequest) -> CoachWorkoutResponse:
    return _generate(
        user_id, req.message, req.available_equipment, req.target_duration_minutes, req.context_overrides
    )


def routine(user_id: int, req: CoachRoutineRequest) -> CoachWorkoutResponse:
    return _generate(
        user_id, ROUTINE_REQUEST_MESSAGE, req.available_equipment, req.target_duration_minutes,
        req.context_overrides,
    )
