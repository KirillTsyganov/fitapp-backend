from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(128), unique=True, nullable=True)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    sessions = db.relationship('WorkoutSession', backref='user', lazy=True)


class WorkoutSession(db.Model):
    __tablename__ = 'workout_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    target_pushups = db.Column(db.Integer, nullable=False)
    target_rounds = db.Column(db.Integer, nullable=True)
    reps_per_exercise = db.Column(db.Integer, nullable=True)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    sets = db.relationship('PushupSet', backref='session', lazy=True)


class PushupSet(db.Model):
    __tablename__ = 'pushup_sets'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('workout_sessions.id'), nullable=False)
    reps = db.Column(db.Integer, nullable=False)
    exercise_type = db.Column(db.String(50), nullable=False, server_default='pushups')
    client_id = db.Column(db.String(50), unique=True, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserSettings(db.Model):
    __tablename__ = 'user_settings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    min_rounds = db.Column(db.Integer, nullable=False, default=2)
    max_rounds = db.Column(db.Integer, nullable=False, default=8)
    reps_per_exercise = db.Column(db.Integer, nullable=False, default=20)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FlowSequence(db.Model):
    __tablename__ = 'flow_sequences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    total_duration = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    exercises = db.relationship(
        'FlowExercise', backref='sequence', lazy=True,
        cascade='all, delete-orphan',
    )


class FlowExercise(db.Model):
    __tablename__ = 'flow_exercises'

    id = db.Column(db.Integer, primary_key=True)
    sequence_id = db.Column(
        db.Integer, db.ForeignKey('flow_sequences.id', ondelete='CASCADE'), nullable=False
    )
    position = db.Column(db.Integer, nullable=False)
    exercise_id = db.Column(db.String(20), nullable=False)
    exercise_name = db.Column(db.String(120), nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    repeats = db.Column(db.Integer, nullable=False, default=1)

