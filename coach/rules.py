"""Deterministic guardrails run before (constraints) and after (validation) LLM generation."""
import re

from schemas import CoachWorkoutResponse

from .memory import UserSnapshot

HEAVY_PRESS_MIN_RPE = 7
HIGH_VOLUME_MIN_SETS = 3
SHORT_REST_HOURS = 12
SAME_FOCUS_WINDOW_HOURS = 24
FLOW_TIME_TOLERANCE_PERCENT = 15

_OVERHEAD_PRESS = re.compile(
    r'overhead press|\bohp\b|military press|shoulder press|push press|strict press|\bjerk\b', re.I
)
_STRAIGHT_ARM = re.compile(
    r'planche|front lever|back lever|iron cross|maltese|victorian|straight[- ]arm', re.I
)
_HAS_NUMBER = re.compile(r'\d')


def pre_generation_constraints(snapshot: UserSnapshot, target_focus: str | None = None) -> list[str]:
    """Hard constraints derived from user state, injected into the prompt."""
    constraints = []
    for joint in snapshot.flagged_joints:
        constraints.append(
            f"Flagged joint '{joint}': no loaded end-range work through it; use regressions and controlled mobility."
        )
    for pattern, status in snapshot.fatigue.items():
        if status == 'high':
            constraints.append(
                f"{pattern} fatigue is HIGH over the last 72h: no heavy or high-volume {pattern} work today."
            )
    hours = snapshot.hours_since_last_session
    if hours is not None and hours < SHORT_REST_HOURS:
        constraints.append(
            f"Last session was {hours:.0f}h ago: keep today low intensity (mobility, yoga, light technique work)."
        )
    if target_focus:
        wanted = target_focus.lower()
        for flow in snapshot.recent_flows:
            past = flow.target_focus.lower()
            if flow.hours_ago < SAME_FOCUS_WINDOW_HOURS and (wanted in past or past in wanted):
                constraints.append(
                    f"A '{flow.target_focus}' flow was generated {flow.hours_ago:.0f}h ago: vary exercise selection "
                    f"and do not repeat: {', '.join(flow.exercises) or 'n/a'}."
                )
    return constraints


def _exercise_violations(response: CoachWorkoutResponse) -> list[str]:
    violations = []
    heavy_press_seen = None
    for block in response.blocks:
        for ex in block.exercises:
            if ex.sets < 1:
                violations.append(f"'{ex.name}': sets must be at least 1.")
            if not _HAS_NUMBER.search(ex.reps_or_duration):
                violations.append(f"'{ex.name}': reps_or_duration must include a number of reps or seconds.")
            if ex.rpe is None:
                violations.append(f"'{ex.name}': rpe is required.")

            if (
                ex.modality == 'weights'
                and _OVERHEAD_PRESS.search(ex.name)
                and (ex.rpe or 0) >= HEAVY_PRESS_MIN_RPE
            ):
                heavy_press_seen = heavy_press_seen or ex.name
            elif (
                heavy_press_seen
                and ex.modality == 'calisthenics'
                and _STRAIGHT_ARM.search(ex.name)
                and ex.sets >= HIGH_VOLUME_MIN_SETS
            ):
                violations.append(
                    f"'{ex.name}': high-volume straight-arm work must not follow heavy overhead press "
                    f"('{heavy_press_seen}'); move it before the press or reduce it."
                )
    return violations


def validate_workout(response: CoachWorkoutResponse) -> list[str]:
    """Chat validation: replies without blocks are valid; otherwise check every exercise."""
    if not response.blocks:
        return []
    return _exercise_violations(response)


def validate_flow(response: CoachWorkoutResponse, target_minutes: int) -> list[str]:
    """Flows never defer to a diagnostic question; blocks, exercises and time bounds must pass."""
    if response.diagnostic_needed:
        return ['diagnostic_needed must be false for flows: assume baseline readiness and return all blocks.']
    if not response.blocks:
        return ['blocks are required for a flow.']

    violations = _exercise_violations(response)
    low = -(-target_minutes * (100 - FLOW_TIME_TOLERANCE_PERCENT) // 100)  # ceil
    high = target_minutes * (100 + FLOW_TIME_TOLERANCE_PERCENT) // 100
    if not low <= response.estimated_total_minutes <= high:
        violations.append(
            f'estimated_total_minutes is {response.estimated_total_minutes}; it must be between '
            f'{low} and {high} for a {target_minutes}-minute flow. Adjust sets, rest or exercise count.'
        )
    return violations
