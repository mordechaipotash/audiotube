import os
import secrets
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, redirect, make_response
import resend

SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
APP_URL = os.environ.get('APP_URL', 'http://localhost:5050')
FROM_EMAIL = os.environ.get('FROM_EMAIL', 'login@audiotube.mordechaipotash.com')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')

# Initialize resend
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

def generate_magic_token():
    """Generate a secure random token"""
    return secrets.token_urlsafe(32)

def send_magic_link(email, token):
    """Send magic link email via Resend"""
    link = f"{APP_URL}/auth/verify?token={token}"

    if not RESEND_API_KEY or os.environ.get('FLASK_DEBUG'):
        # Dev mode: print to console
        print(f"\n{'='*50}")
        print(f"MAGIC LINK for {email}:")
        print(f"{link}")
        print(f"{'='*50}\n")
        return True

    try:
        resend.Emails.send({
            "from": f"AudioTube <{FROM_EMAIL}>",
            "to": email,
            "subject": "Your AudioTube login link",
            "html": f"""
            <div style="font-family: sans-serif; max-width: 400px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #333;">Login to AudioTube</h2>
                <p style="color: #666;">Click the button below to log in. This link expires in 15 minutes.</p>
                <a href="{link}"
                   style="display: inline-block; background: #000; color: #fff; padding: 12px 24px;
                          text-decoration: none; border-radius: 6px; margin: 20px 0;">
                    Log in to AudioTube
                </a>
                <p style="color: #999; font-size: 12px;">
                    If you didn't request this link, you can safely ignore this email.
                </p>
            </div>
            """
        })
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def create_session_token(user_id, days=30):
    """Create a JWT session token"""
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(days=days),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def decode_session_token(token):
    """Decode and verify a session token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload.get('user_id')
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def get_current_user_id():
    """Get current user ID from cookie"""
    token = request.cookies.get('session')
    if not token:
        return None
    return decode_session_token(token)

def login_required(f):
    """Decorator for protected routes"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'Not logged in'}), 401
        return f(user_id, *args, **kwargs)
    return decorated

def optional_auth(f):
    """Decorator that passes user_id if logged in, None otherwise"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = get_current_user_id()
        return f(user_id, *args, **kwargs)
    return decorated

def set_session_cookie(response, user_id):
    """Set session cookie on response"""
    token = create_session_token(user_id)
    is_prod = not os.environ.get('FLASK_DEBUG')
    response.set_cookie(
        'session',
        token,
        httponly=True,
        secure=is_prod,
        samesite='Lax',
        max_age=30 * 24 * 60 * 60  # 30 days
    )
    return response

def clear_session_cookie(response):
    """Clear session cookie"""
    response.delete_cookie('session')
    return response
