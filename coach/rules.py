"""Deterministic guardrails run before (constraints) and after (validation) LLM generation."""
import re

from schemas import CoachWorkoutResponse

from .memory import UserSnapshot

HEAVY_PRESS_MIN_RPE = 7
HIGH_VOLUME_MIN_SETS = 3
SHORT_REST_HOURS = 12

_OVERHEAD_PRESS = re.compile(
    r'overhead press|\bohp\b|military press|shoulder press|push press|strict press|\bjerk\b', re.I
)
_STRAIGHT_ARM = re.compile(
    r'planche|front lever|back lever|iron cross|maltese|victorian|straight[- ]arm', re.I
)
_HAS_NUMBER = re.compile(r'\d')


def pre_generation_constraints(snapshot: UserSnapshot) -> list[str]:
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
    return constraints


def validate_workout(response: CoachWorkoutResponse) -> list[str]:
    """Return rule violations for a generated workout; an empty list means it passes."""
    if not response.blocks:
        return []

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
