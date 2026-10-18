"""Deterministic guardrails run before (constraints) and after (validation) LLM generation."""
import re

from schemas import CoachWorkoutResponse

from .memory import UserSnapshot

HEAVY_PRESS_MIN_RPE = 7
HIGH_VOLUME_MIN_SETS = 3
SHORT_REST_HOURS = 12
SAME_FOCUS_WINDOW_HOURS = 24
FLOW_TIME_TOLERANCE_PERCENT = 15
FLOW_TIME_MIN_TOLERANCE_SECONDS = 60
FLOW_TIME_MAX_TOLERANCE_SECONDS = 120
# Setup time added at every change of exercise; the frontend runner (utils/flowSteps.js) must use the same value.
TRANSITION_BUFFER_SECONDS = 5

BLOCK_ORDER = (
    'Prep / Dynamic Flow',
    'Primary Skill / Strength',
    'Accessory / Hypertrophy',
    'Down-Regulation / Cool Down',
)
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


def station_sequence(response: CoachWorkoutResponse) -> list:
    """Exercises in the order the runner plays them, one entry per set (mirrors frontend buildSteps)."""
    sequence = []
    for block in sorted(response.blocks or [], key=lambda b: BLOCK_ORDER.index(b.block_name)):
        if block.structure == 'circuit' and len(block.exercises) > 1:
            for round_number in range(1, max(ex.sets for ex in block.exercises) + 1):
                sequence.extend(ex for ex in block.exercises if round_number <= ex.sets)
        else:
            for ex in block.exercises:
                sequence.extend([ex] * max(ex.sets, 0))
    return sequence


def total_seconds(response: CoachWorkoutResponse) -> int:
    """Work time plus rest after every set but the last, plus a buffer at each exercise change."""
    sequence = station_sequence(response)
    total = 0
    for i, ex in enumerate(sequence):
        total += ex.allocated_seconds or 0
        if i == len(sequence) - 1:
            break
        total += ex.rest_seconds or 0
        if sequence[i + 1] is not ex:
            total += TRANSITION_BUFFER_SECONDS
    return total


def _exercise_violations(response: CoachWorkoutResponse) -> list[str]:
    violations = []
    heavy_press_seen = None
    for block in response.blocks:
        if block.structure == 'circuit':
            if len(block.exercises) < 2:
                violations.append(f"'{block.block_name}': a circuit needs at least 2 exercises.")
            elif len({ex.sets for ex in block.exercises}) > 1:
                violations.append(
                    f"'{block.block_name}': circuit exercises must share the same sets value (the number of rounds)."
                )
        for ex in block.exercises:
            if ex.sets < 1:
                violations.append(f"'{ex.name}': sets must be at least 1.")
            if not _HAS_NUMBER.search(ex.reps_or_duration):
                violations.append(f"'{ex.name}': reps_or_duration must include a number of reps or seconds.")
            if not ex.allocated_seconds or ex.allocated_seconds < 1:
                violations.append(f"'{ex.name}': allocated_seconds is required (active seconds for one set).")
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

    # Every exercise that is followed by another set or exercise needs a rest to schedule.
    sequence = station_sequence(response)
    for ex in {id(e): e for e in sequence[:-1]}.values():
        if not ex.rest_seconds:
            violations.append(f"'{ex.name}': rest_seconds is required (only the final exercise may omit it).")

    target_seconds = target_minutes * 60
    tolerance = min(
        FLOW_TIME_MAX_TOLERANCE_SECONDS,
        max(FLOW_TIME_MIN_TOLERANCE_SECONDS, target_seconds * FLOW_TIME_TOLERANCE_PERCENT // 100),
    )
    total = total_seconds(response)
    if abs(total - target_seconds) > tolerance:
        violations.append(
            f'Computed session time is {total}s ({total / 60:.1f} min): sum of sets x allocated_seconds, '
            f'rest_seconds after every set except the last, and {TRANSITION_BUFFER_SECONDS}s per exercise change. '
            f'It must be within {tolerance}s of {target_seconds}s for a {target_minutes}-minute flow. '
            'Adjust sets, allocated_seconds or rest_seconds, or remove an exercise.'
        )
    return violations
