import os
import subprocess
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, make_response
from dotenv import load_dotenv

load_dotenv()

from database import (
    init_db, get_or_create_user, get_user_by_id,
    create_auth_token, verify_auth_token, cleanup_expired_tokens,
    add_to_history, get_user_history,
    get_cached_stream, cache_stream, cleanup_old_cache,
    get_user_count
)
from auth import (
    generate_magic_token, send_magic_link,
    get_current_user_id, login_required, optional_auth,
    set_session_cookie, clear_session_cookie
)

app = Flask(__name__)

# Initialize database on startup
if os.environ.get('DATABASE_URL'):
    try:
        init_db()
        print("Database initialized")
    except Exception as e:
        print(f"Database init error: {e}")

# ============== Pages ==============

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/stats')
def get_stats():
    """Get user count and pricing info"""
    try:
        count = get_user_count() if os.environ.get('DATABASE_URL') else 0
    except:
        count = 0

    return jsonify({
        'user_count': count,
        'free_slots': max(0, 20 - count),
        'pricing': {
            'free_tier': 20,
            'paid_tier': 100,
            'price': '$1/month'
        }
    })

# ============== Auth Routes ==============

@app.route('/api/auth/request', methods=['POST'])
def request_magic_link():
    """Request a magic link login email"""
    data = request.get_json()
    email = data.get('email', '').lower().strip()

    if not email or '@' not in email:
        return jsonify({'error': 'Valid email required'}), 400

    # Generate token
    token = generate_magic_token()
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    # Store token
    create_auth_token(email, token, expires_at)

    # Send email
    if send_magic_link(email, token):
        return jsonify({'ok': True, 'message': 'Check your email for login link'})
    else:
        return jsonify({'error': 'Failed to send email'}), 500

@app.route('/auth/verify')
def verify_magic_link():
    """Verify magic link and log user in"""
    token = request.args.get('token')

    if not token:
        return redirect('/?error=invalid_link')

    # Verify token
    email = verify_auth_token(token)
    if not email:
        return redirect('/?error=expired_link')

    # Get or create user
    user = get_or_create_user(email)

    # Create response with session cookie
    response = make_response(redirect('/?logged_in=true'))
    set_session_cookie(response, user['id'])

    # Cleanup old tokens
    cleanup_expired_tokens()

    return response

@app.route('/api/auth/me')
def get_current_user():
    """Get current logged in user"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'logged_in': False})

    user = get_user_by_id(user_id)
    if not user:
        return jsonify({'logged_in': False})

    return jsonify({
        'logged_in': True,
        'email': user['email'],
        'user_id': user['id']
    })

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Log out current user"""
    response = make_response(jsonify({'ok': True}))
    clear_session_cookie(response)
    return response

# ============== Search ==============

@app.route('/api/search')
def search():
    query = request.args.get('q', '')
    date_filter = request.args.get('date', '')
    if not query:
        return jsonify([])

    date_filters = {
        'today': 'EgIIAg%3D%3D',
        'week': 'EgIIAw%3D%3D',
        'month': 'EgIIBA%3D%3D',
        'year': 'EgIIBQ%3D%3D',
    }

    try:
        if date_filter and date_filter in date_filters:
            from urllib.parse import quote
            search_url = f'https://www.youtube.com/results?search_query={quote(query)}&sp={date_filters[date_filter]}'
            cmd = [
                'yt-dlp', search_url,
                '--flat-playlist', '--dump-json', '--no-warnings',
                '--playlist-end', '18'
            ]
        else:
            cmd = [
                'yt-dlp', f'ytsearch18:{query}',
                '--flat-playlist', '--dump-json', '--no-warnings'
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        videos = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    data = json.loads(line)
                    video_id = data.get('id')
                    duration = data.get('duration')
                    videos.append({
                        'id': video_id,
                        'title': data.get('title'),
                        'channel': data.get('channel') or data.get('uploader', 'Unknown'),
                        'duration': duration,
                        'duration_raw': duration or 0,
                        'upload_date': '',
                        'upload_timestamp': 0,
                        'views': '',
                        'view_count': 0,
                        'url': f"https://youtube.com/watch?v={video_id}"
                    })
                except json.JSONDecodeError:
                    continue

        return jsonify(videos)
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Search timeout'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============== Metadata ==============

@app.route('/api/metadata/<video_id>')
def get_metadata(video_id):
    """Fetch metadata for a single video"""
    try:
        cmd = [
            'yt-dlp', f'https://youtube.com/watch?v={video_id}',
            '--dump-json', '--no-warnings', '--no-download'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        if result.returncode == 0:
            data = json.loads(result.stdout)

            upload_date = data.get('upload_date', '')
            upload_timestamp = 0
            if upload_date and len(upload_date) == 8:
                try:
                    dt = datetime.strptime(upload_date, '%Y%m%d')
                    upload_timestamp = int(dt.timestamp())
                except:
                    pass
                upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

            views = data.get('view_count', 0) or 0
            if views >= 1000000:
                view_str = f"{views/1000000:.1f}M views"
            elif views >= 1000:
                view_str = f"{views/1000:.1f}K views"
            elif views > 0:
                view_str = f"{views} views"
            else:
                view_str = ""

            return jsonify({
                'id': video_id,
                'upload_date': upload_date,
                'upload_timestamp': upload_timestamp,
                'views': view_str,
                'view_count': views
            })
    except:
        pass

    return jsonify({'id': video_id, 'error': True})

# ============== Streaming ==============

@app.route('/api/stream/<video_id>')
def stream(video_id):
    """Get audio stream URL (with caching)"""
    # Check cache first
    if os.environ.get('DATABASE_URL'):
        cached_url = get_cached_stream(video_id)
        if cached_url:
            return jsonify({'url': cached_url, 'cached': True})

    try:
        cmd = [
            'yt-dlp', f'https://youtube.com/watch?v={video_id}',
            '-f', 'bestaudio', '-g', '--no-warnings'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            audio_url = result.stdout.strip().split('\n')[0]

            # Cache the URL
            if os.environ.get('DATABASE_URL'):
                cache_stream(video_id, audio_url)

            return jsonify({'url': audio_url})
        else:
            return jsonify({'error': 'Failed to get stream'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============== History ==============

@app.route('/api/history', methods=['GET'])
@login_required
def get_history(user_id):
    """Get user's listening history"""
    history = get_user_history(user_id, limit=50)
    # Convert datetime to ISO format
    for item in history:
        if item.get('viewed_at'):
            item['viewed_at'] = item['viewed_at'].isoformat()
    return jsonify(history)

@app.route('/api/history', methods=['POST'])
@login_required
def add_history(user_id):
    """Add to user's listening history"""
    data = request.get_json()
    video_id = data.get('video_id')
    title = data.get('title', '')
    channel = data.get('channel', '')
    duration = data.get('duration', 0)

    if not video_id:
        return jsonify({'error': 'video_id required'}), 400

    add_to_history(user_id, video_id, title, channel, duration)
    return jsonify({'ok': True})

# ============== Utilities ==============

def format_duration(seconds):
    if not seconds:
        return '--:--'
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'

app.jinja_env.filters['duration'] = format_duration

# ============== Main ==============

if __name__ == '__main__':
    app.run(debug=True, port=5050)
