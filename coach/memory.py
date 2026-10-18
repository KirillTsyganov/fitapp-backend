"""Builds the user's recent-training snapshot from the DB and formats it for prompt injection."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from models import db, Flow, PushupSet, WorkoutSession

# Only the pushup/lunge circuit is logged today; extend as new exercise types are added.
EXERCISE_TO_PATTERN = {
    'pushups': 'horizontal_push',
    'lunges': 'knee_dominant',
}
PATTERNS = (
    'horizontal_push', 'horizontal_pull', 'vertical_push', 'vertical_pull', 'knee_dominant', 'hip_hinge',
)
LOOKBACK_DAYS = 7
FATIGUE_WINDOW_HOURS = 72
FATIGUE_MODERATE_REPS = 60
FATIGUE_HIGH_REPS = 120
FLOW_LOOKBACK_DAYS = 14
FLOW_HISTORY_LIMIT = 5


@dataclass
class RecentFlow:
    name: str
    target_focus: str
    duration_minutes: int
    hours_ago: float
    exercises: list[str]


@dataclass
class UserSnapshot:
    volume_7d: dict[str, int]
    volume_72h: dict[str, int]
    fatigue: dict[str, str]
    sessions_7d: int
    hours_since_last_session: float | None
    flagged_joints: list[str] = field(default_factory=list)
    skill_goals: list[str] = field(default_factory=list)
    recent_flows: list[RecentFlow] = field(default_factory=list)


def _one_line(text, max_len: int) -> str:
    return ' '.join(str(text).split())[:max_len]


def clean_list(value, max_items: int = 10, max_len: int = 60) -> list[str]:
    """Normalize untrusted client input into short single-line strings."""
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value[:max_items]:
        if isinstance(item, str):
            text = _one_line(item, max_len)
            if text:
                cleaned.append(text)
    return cleaned


def _exercise_names(routine_data) -> list[str]:
    """Tolerant of malformed or older routine_data shapes."""
    blocks = routine_data.get('blocks') if isinstance(routine_data, dict) else None
    names = []
    for block in blocks if isinstance(blocks, list) else []:
        exercises = block.get('exercises') if isinstance(block, dict) else None
        for ex in exercises if isinstance(exercises, list) else []:
            if isinstance(ex, dict) and isinstance(ex.get('name'), str):
                names.append(_one_line(ex['name'], 60))
    return names


def _recent_flows(user_id: int, now: datetime) -> list[RecentFlow]:
    flows = (
        Flow.query
        .filter(Flow.user_id == user_id, Flow.created_at >= now - timedelta(days=FLOW_LOOKBACK_DAYS))
        .order_by(Flow.created_at.desc())
        .limit(FLOW_HISTORY_LIMIT)
        .all()
    )
    return [
        RecentFlow(
            name=_one_line(f.name, 120),
            target_focus=_one_line(f.target_focus, 120),
            duration_minutes=f.duration_minutes,
            hours_ago=(now - f.created_at).total_seconds() / 3600,
            exercises=_exercise_names(f.routine_data),
        )
        for f in flows
    ]


def _fatigue_level(reps: int) -> str:
    if reps >= FATIGUE_HIGH_REPS:
        return 'high'
    if reps >= FATIGUE_MODERATE_REPS:
        return 'moderate'
    return 'low'


def get_user_snapshot(user_id: int, overrides: dict | None = None) -> UserSnapshot:
    """Must be called inside a Flask app context."""
    now = datetime.utcnow()
    rows = (
        db.session.query(PushupSet.session_id, PushupSet.exercise_type, PushupSet.reps, PushupSet.created_at)
        .join(WorkoutSession, PushupSet.session_id == WorkoutSession.id)
        .filter(
            WorkoutSession.user_id == user_id,
            PushupSet.created_at >= now - timedelta(days=LOOKBACK_DAYS),
        )
        .all()
    )

    volume_7d = {p: 0 for p in PATTERNS}
    volume_72h = {p: 0 for p in PATTERNS}
    fatigue_cutoff = now - timedelta(hours=FATIGUE_WINDOW_HOURS)
    for _, exercise_type, reps, created_at in rows:
        pattern = EXERCISE_TO_PATTERN.get(exercise_type)
        if pattern is None:
            continue
        volume_7d[pattern] += reps
        if created_at >= fatigue_cutoff:
            volume_72h[pattern] += reps

    last_set_at = max((r.created_at for r in rows), default=None)
    overrides = overrides or {}
    return UserSnapshot(
        volume_7d=volume_7d,
        volume_72h=volume_72h,
        fatigue={p: _fatigue_level(v) for p, v in volume_72h.items()},
        sessions_7d=len({r.session_id for r in rows}),
        hours_since_last_session=(now - last_set_at).total_seconds() / 3600 if last_set_at else None,
        flagged_joints=clean_list(overrides.get('flagged_joints')),
        skill_goals=clean_list(overrides.get('skill_goals')),
        recent_flows=_recent_flows(user_id, now),
    )


def format_context(snapshot: UserSnapshot) -> str:
    """Concise markdown block for prompt injection."""
    last = (
        f"{snapshot.hours_since_last_session:.0f}h ago"
        if snapshot.hours_since_last_session is not None
        else 'none in the last 7 days'
    )
    lines = [
        '## User context',
        f'- Logged sessions (last {LOOKBACK_DAYS} days): {snapshot.sessions_7d}',
        f'- Last logged activity: {last}',
        '',
        '| Pattern | Reps 72h | Reps 7d | Fatigue |',
        '|---|---|---|---|',
    ]
    for p in PATTERNS:
        lines.append(f'| {p} | {snapshot.volume_72h[p]} | {snapshot.volume_7d[p]} | {snapshot.fatigue[p]} |')
    lines += [
        '',
        f"- Flagged joints: {', '.join(snapshot.flagged_joints) or 'none reported'}",
        f"- Skill goals: {', '.join(snapshot.skill_goals) or 'none reported'}",
        '- Logged data only covers the pushup/lunge circuit; other training is unknown.',
        '',
        f'## Recent flows (last {FLOW_LOOKBACK_DAYS} days)',
    ]
    if snapshot.recent_flows:
        for f in snapshot.recent_flows:
            lines.append(
                f'- {f.hours_ago:.0f}h ago: "{f.name}" | focus: {f.target_focus} | {f.duration_minutes} min | '
                f"{', '.join(f.exercises) or 'no exercise detail'}"
            )
    else:
        lines.append('- none')
    return '\n'.join(lines)
