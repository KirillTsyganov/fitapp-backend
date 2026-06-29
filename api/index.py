import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()           # .env
load_dotenv('.env.local', override=True)  # Vercel local overrides

import jwt as pyjwt
from authlib.integrations.flask_client import OAuth
from flask import Flask, jsonify, redirect, request, url_for
from flask_cors import CORS
from pydantic import ValidationError

from models import db, User, WorkoutSession, PushupSet
from schemas import UserCreate, SetCreate

# --- Config ---
JWT_SECRET = os.environ.get('JWT_SECRET_KEY', 'dev-only-jwt-secret')        # JWT signing
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173').rstrip('/')

app = Flask(__name__)
CORS(app, origins=[FRONTEND_URL], allow_headers=['Content-Type', 'Authorization'])
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-secret')  # Flask session signing

# --- Neon DB Configuration ---
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

db.init_app(app)

with app.app_context():
    db.create_all()

# --- Google OAuth ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)


def _make_jwt(user: User) -> str:
    payload = {
        'sub': str(user.id),
        'email': user.email,
        'exp': datetime.now(timezone.utc) + timedelta(days=7),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm='HS256')


def _payload_user_id(payload) -> int | None:
    try:
        return int(payload['sub'])
    except (KeyError, TypeError, ValueError):
        return None


def _current_user():
    """Decode the Bearer JWT and return the User, or None if invalid/missing."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    try:
        payload = pyjwt.decode(auth[7:], JWT_SECRET, algorithms=['HS256'])
        user_id = _payload_user_id(payload)
        if user_id is None:
            return None
        return db.session.get(User, user_id)
    except pyjwt.PyJWTError:
        return None


def _parse_session_day_context():
    data = request.get_json(silent=True) or {}
    date_str = request.args.get('date') or data.get('date')
    tz_offset_raw = request.args.get('tzOffsetMinutes') or data.get('tzOffsetMinutes', 0)

    if not date_str:
        date_str = datetime.utcnow().date().isoformat()

    try:
        tz_offset_minutes = int(tz_offset_raw)
        local_day = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None, jsonify({'error': 'Invalid date context'}), 422

    start_local = datetime(local_day.year, local_day.month, local_day.day)
    start_utc = start_local + timedelta(minutes=tz_offset_minutes)
    end_utc = start_utc + timedelta(days=1)

    return {
        'date': date_str,
        'tz_offset_minutes': tz_offset_minutes,
        'start_utc': start_utc,
        'end_utc': end_utc,
    }, None, None


def _find_session_for_day(user_id: int, day_context):
    return WorkoutSession.query.filter(
        WorkoutSession.user_id == user_id,
        WorkoutSession.created_at >= day_context['start_utc'],
        WorkoutSession.created_at < day_context['end_utc'],
    ).order_by(WorkoutSession.created_at.desc()).first()


def _serialize_session(workout: WorkoutSession, date_str: str):
    total_reps = sum(pushup_set.reps for pushup_set in workout.sets)
    ordered_sets = sorted(workout.sets, key=lambda pushup_set: pushup_set.created_at)
    return {
        'session_id': workout.id,
        'date': date_str,
        'target_pushups': workout.target_pushups,
        'is_completed': workout.is_completed,
        'total_reps': total_reps,
        'sets': [
            {
                'id': pushup_set.id,
                'reps': pushup_set.reps,
                'created_at': pushup_set.created_at.isoformat(),
            }
            for pushup_set in ordered_sets
        ],
        'created_at': workout.created_at.isoformat(),
    }


# ----------------------------------------------------
# GOOGLE AUTH ROUTES
# ----------------------------------------------------

@app.route('/api/auth/google')
def google_login():
    """Redirect the frontend here to kick off the Google OAuth flow."""
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route('/api/auth/google/callback')
def google_callback():
    """Google redirects here after user consents. Issues a JWT to the frontend."""
    token = google.authorize_access_token()
    userinfo = token.get('userinfo')
    if not userinfo:
        return jsonify({'error': 'Failed to retrieve user info from Google'}), 400

    google_id = userinfo['sub']
    email = userinfo['email']
    name = userinfo.get('name', email.split('@')[0])

    # Find by google_id first, then fall back to email (links existing accounts)
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            user.google_id = google_id
        else:
            user = User(username=name, email=email, google_id=google_id)
            db.session.add(user)
    db.session.commit()

    jwt_token = _make_jwt(user)
    # Use URL fragment so the token is never sent to servers or stored in access logs
    return redirect(f"{FRONTEND_URL}/auth/callback#{jwt_token}")


@app.route('/api/auth/logout')
def auth_logout():
    """JWT is stateless; the client drops the token. This endpoint exists for completeness."""
    return jsonify({'message': 'Logged out'}), 200


@app.route('/api/auth/me')
def auth_me():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        payload = pyjwt.decode(auth[7:], JWT_SECRET, algorithms=['HS256'])
    except pyjwt.ExpiredSignatureError:
        return jsonify({'error': 'Token expired'}), 401
    except pyjwt.PyJWTError:
        return jsonify({'error': 'Invalid token'}), 401
    user_id = _payload_user_id(payload)
    if user_id is None:
        return jsonify({'error': 'Invalid token'}), 401
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found', 'sub': payload.get('sub')}), 401
    return jsonify({'name': user.username, 'email': user.email})


# ----------------------------------------------------
# AUTH & USER ROUTES
# ----------------------------------------------------

@app.route('/api/users', methods=['POST'])
def create_user():
    try:
        data = UserCreate(**request.get_json(force=True))
    except ValidationError as e:
        return jsonify({'errors': e.errors()}), 422

    if User.query.filter_by(email=data.email).first():
        return jsonify({'error': 'Email already registered'}), 409

    user = User(username=data.username, email=data.email)
    db.session.add(user)
    db.session.commit()
    return jsonify({'id': user.id, 'username': user.username, 'email': user.email}), 201


# ----------------------------------------------------
# WORKOUT SESSION ROUTES
# ----------------------------------------------------

@app.route('/api/sessions/today', methods=['GET'])
def get_today_session():
    user = _current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    day_context, error_response, status_code = _parse_session_day_context()
    if error_response:
        return error_response, status_code

    workout = _find_session_for_day(user.id, day_context)
    if not workout:
        return jsonify({'date': day_context['date'], 'session': None})

    return jsonify(_serialize_session(workout, day_context['date']))

@app.route('/api/sessions', methods=['POST'])
def start_session():
    user = _current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    day_context, error_response, status_code = _parse_session_day_context()
    if error_response:
        return error_response, status_code

    existing_workout = _find_session_for_day(user.id, day_context)
    if existing_workout:
        return jsonify(_serialize_session(existing_workout, day_context['date'])), 200

    target = random.randint(80, 150)
    workout = WorkoutSession(user_id=user.id, target_pushups=target)
    db.session.add(workout)
    db.session.commit()
    return jsonify(_serialize_session(workout, day_context['date'])), 201


@app.route('/api/sessions/<int:session_id>/sets', methods=['POST'])
def log_pushup_set(session_id):
    user = _current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    workout = db.session.get(WorkoutSession, session_id)
    if not workout:
        return jsonify({'error': 'Session not found'}), 404
    if workout.user_id != user.id:
        return jsonify({'error': 'Forbidden'}), 403
    if workout.is_completed:
        return jsonify({'error': 'Session already completed'}), 400

    try:
        data = SetCreate(**request.get_json(force=True))
    except ValidationError as e:
        return jsonify({'errors': e.errors()}), 422

    # Idempotency: if this client_id was already recorded, return the existing result
    if data.client_id:
        existing_set = PushupSet.query.filter_by(client_id=data.client_id).first()
        if existing_set:
            total_reps = sum(s.reps for s in workout.sets)
            return jsonify({
                'set_id': existing_set.id,
                'reps_logged': existing_set.reps,
                'total_reps': total_reps,
                'target_pushups': workout.target_pushups,
                'session_completed': workout.is_completed,
            }), 200

    # Compute total BEFORE db.session.add to avoid SQLAlchemy autoflush double-counting
    total_reps = sum(s.reps for s in workout.sets) + data.reps

    pushup_set = PushupSet(session_id=session_id, reps=data.reps, client_id=data.client_id)
    db.session.add(pushup_set)

    if total_reps >= workout.target_pushups:
        workout.is_completed = True

    db.session.commit()
    return jsonify({
        'set_id': pushup_set.id,
        'reps_logged': data.reps,
        'total_reps': total_reps,
        'target_pushups': workout.target_pushups,
        'session_completed': workout.is_completed,
    }), 201


# ----------------------------------------------------
# DASHBOARD & ANALYTICS ROUTES
# ----------------------------------------------------

@app.route('/api/users/<int:user_id>/stats', methods=['GET'])
def get_user_stats(user_id):
    current = _current_user()
    if not current:
        return jsonify({'error': 'Unauthorized'}), 401
    if current.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    completed_sessions = WorkoutSession.query.filter_by(
        user_id=user_id, is_completed=True
    ).all()

    cumulative_pushups = sum(
        s.reps for ws in user.sessions for s in ws.sets
    )

    active_session = WorkoutSession.query.filter_by(
        user_id=user_id, is_completed=False
    ).order_by(WorkoutSession.created_at.desc()).first()

    active_data = None
    if active_session:
        active_data = {
            'id': active_session.id,
            'target_pushups': active_session.target_pushups,
            'sets': [{'id': s.id, 'reps': s.reps} for s in active_session.sets],
        }

    return jsonify({
        'user_id': user_id,
        'cumulative_pushups': cumulative_pushups,
        'total_sessions_completed': len(completed_sessions),
        'active_session': active_data,
    })


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true', port=5000)
