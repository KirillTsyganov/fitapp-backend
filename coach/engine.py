"""OpenAI orchestration: memory -> pre-checks -> structured generation -> post-validation."""
import logging
from typing import Callable

from openai import OpenAI, OpenAIError

from schemas import CoachChatRequest, CoachWorkoutResponse, CreateFlowRequest

from . import memory, rules
from .config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_REASONING_EFFORT, OPENAI_TIMEOUT_SECONDS
from .prompts import FEW_SHOT_MESSAGES, FLOW_MODE_INSTRUCTIONS, SYSTEM_PROMPT

MAX_ATTEMPTS = 2

logger = logging.getLogger(__name__)


class CoachError(Exception):
    """Raised with a client-safe message when the coach cannot produce a response."""


def _client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise CoachError('Coach is not configured.')
    # No SDK retries: the timeout is per attempt and MAX_ATTEMPTS must fit the function limit.
    return OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS, max_retries=0)


def _parse(client: OpenAI, messages: list[dict]) -> CoachWorkoutResponse:
    try:
        completion = client.beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=messages,
            response_format=CoachWorkoutResponse,
            **({'reasoning_effort': OPENAI_REASONING_EFFORT} if OPENAI_REASONING_EFFORT else {}),
        )
    except OpenAIError as exc:
        logger.warning('OpenAI request failed: %s: %s', type(exc).__name__, exc)
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
    target_focus: str | None,
    structure: str | None = None,
) -> str:
    constraints = rules.pre_generation_constraints(snapshot, target_focus)
    parts = [
        memory.format_context(snapshot),
        '',
        '## Constraints',
        *(f'- {c}' for c in constraints or ['none']),
        '',
        '## Session parameters',
        f"- Available equipment: {', '.join(equipment) or 'not specified (assume bodyweight only)'}",
        f'- Target duration: {duration_minutes} minutes' if duration_minutes else '- Target duration: not specified',
        f'- Preferred structure: {structure}' if structure else '- Preferred structure: not specified (you choose)',
    ]
    return '\n'.join(parts)


def _generate(
    user_id: int,
    user_message: str,
    equipment: list[str] | None,
    duration_minutes: int | None,
    overrides: dict | None,
    validate: Callable[[CoachWorkoutResponse], list[str]],
    target_focus: str | None = None,
    flow_mode: bool = False,
    structure: str | None = None,
) -> CoachWorkoutResponse:
    snapshot = memory.get_user_snapshot(user_id, overrides)
    context = _build_context_message(
        snapshot, memory.clean_list(equipment), duration_minutes, target_focus, structure,
    )

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        *FEW_SHOT_MESSAGES,
        {'role': 'system', 'content': context},
        *([{'role': 'system', 'content': FLOW_MODE_INSTRUCTIONS}] if flow_mode else []),
        {'role': 'user', 'content': user_message},
    ]

    client = _client()
    for _ in range(MAX_ATTEMPTS):
        response = _parse(client, messages)
        violations = validate(response)
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
        user_id, req.message, req.available_equipment, req.target_duration_minutes, req.context_overrides,
        validate=rules.validate_workout,
        structure=req.structure_preference,
    )


def generate_flow(user_id: int, req: CreateFlowRequest) -> CoachWorkoutResponse:
    target_focus = ' '.join(req.target_focus.split())
    result = _generate(
        user_id,
        f'Create a {req.target_duration_minutes}-minute flow targeting: {target_focus}.',
        req.available_equipment,
        req.target_duration_minutes,
        req.context_overrides,
        validate=lambda r: rules.validate_flow(r, req.target_duration_minutes),
        target_focus=target_focus,
        flow_mode=True,
        structure=req.structure_preference,
    )
    # The runner plays exactly this timeline, so report it rather than the model's own estimate.
    result.estimated_total_minutes = round(rules.total_seconds(result) / 60)
    return result
