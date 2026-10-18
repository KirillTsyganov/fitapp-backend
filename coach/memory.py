"""Builds the user's recent-training snapshot from the DB and formats it for prompt injection."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from models import db, PushupSet, WorkoutSession

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


@dataclass
class UserSnapshot:
    volume_7d: dict[str, int]
    volume_72h: dict[str, int]
    fatigue: dict[str, str]
    sessions_7d: int
    hours_since_last_session: float | None
    flagged_joints: list[str] = field(default_factory=list)
    skill_goals: list[str] = field(default_factory=list)


def clean_list(value, max_items: int = 10, max_len: int = 60) -> list[str]:
    """Normalize untrusted client input into short single-line strings."""
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value[:max_items]:
        if isinstance(item, str):
            text = ' '.join(item.split())[:max_len]
            if text:
                cleaned.append(text)
    return cleaned


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
    ]
    return '\n'.join(lines)
