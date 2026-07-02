"""
PyInstaller entry point.

When bundled, this replaces `manage.py` as the startup script.
The Electron main process spawns this executable as:

    nexapos-server.exe runserver 127.0.0.1:18000 --noreload

On first run (or after an update) the local SQLite schema is automatically
migrated before the HTTP server starts.
"""
import os
import sys

# Make bundled modules importable
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    sys.path.insert(0, bundle_dir)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.setdefault('USE_SQLITE', 'True')

# Stable secret key derived from machine identity (stored path acts as seed)
_user_data = os.environ.get('SECRET_KEY', '')
if not _user_data or len(_user_data) < 32:
    import hashlib
    import platform
    _seed = platform.node() + platform.machine()
    os.environ['SECRET_KEY'] = hashlib.sha256(_seed.encode()).hexdigest()

from django.core.management import execute_from_command_line


def _auto_migrate():
    """Run migrations silently — creates or upgrades the local SQLite schema."""
    try:
        execute_from_command_line(['manage.py', 'migrate', '--run-syncdb', '--no-input'])
    except Exception as exc:
        # Non-fatal: server will start and report DB errors when accessed
        print(f'[entrypoint] migrate warning: {exc}', file=sys.stderr)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''

    if cmd == 'runserver':
        # Auto-migrate before serving so first-time installs work out of the box
        _auto_migrate()

    execute_from_command_line(sys.argv)
