"""
Cloudflare Tunnel Manager for EZ-WebBridge.
Handles downloading, installing, starting, stopping cloudflared.
"""

import os
import stat
import subprocess
import threading
import time
import urllib.request

from core.detector import (
    get_cloudflared_download_url,
    get_cloudflared_exe_name,
    is_windows,
)

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
BIN_DIR = os.path.join(BASE_DIR, 'bin')
CLOUDFLARED_EXE = os.path.join(BIN_DIR, get_cloudflared_exe_name())

# Log buffer for simplified log viewer
_log_buffer = []
_log_lock = threading.Lock()
MAX_LOG_LINES = 200

# Track the running subprocess
_tunnel_process = None
_tunnel_lock = threading.Lock()


class CloudflareTunnelManager:
    """Manages the cloudflared binary lifecycle."""

    # ── Binary Management ──────────────────────────────────

    @staticmethod
    def is_installed():
        """Check if cloudflared binary exists locally."""
        return os.path.isfile(CLOUDFLARED_EXE)

    @staticmethod
    def download_binary(progress_callback=None):
        """Download cloudflared binary from GitHub releases.
        
        Args:
            progress_callback: Optional callable(percent: int) for progress updates.
            
        Returns:
            dict with 'success' and 'message'.
        """
        os.makedirs(BIN_DIR, exist_ok=True)
        url = get_cloudflared_download_url()

        try:
            def _report_hook(block_num, block_size, total_size):
                if progress_callback and total_size > 0:
                    percent = min(int(block_num * block_size * 100 / total_size), 100)
                    progress_callback(percent)

            print(f'[cloudflared] Downloading from {url} ...')
            urllib.request.urlretrieve(url, CLOUDFLARED_EXE, reporthook=_report_hook)

            # Make executable on Unix
            if not is_windows():
                st = os.stat(CLOUDFLARED_EXE)
                os.chmod(CLOUDFLARED_EXE, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

            print('[cloudflared] Download complete.')
            return {'success': True, 'message': 'cloudflared downloaded successfully.'}

        except Exception as e:
            # Clean up partial download
            if os.path.exists(CLOUDFLARED_EXE):
                try:
                    os.remove(CLOUDFLARED_EXE)
                except OSError:
                    pass
            return {'success': False, 'message': f'Download failed: {str(e)}'}

    # ── Tunnel Operation ───────────────────────────────────

    @staticmethod
    def install_service(token):
        """Install cloudflared as a system service.
        
        Runs: cloudflared service install <TOKEN>
        
        Returns:
            dict with 'success' and 'message'.
        """
        if not CloudflareTunnelManager.is_installed():
            return {'success': False, 'message': 'cloudflared is not installed. Please download it first.'}

        try:
            result = subprocess.run(
                [CLOUDFLARED_EXE, 'service', 'install', token],
                capture_output=True, text=True, timeout=60
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode == 0:
                return {'success': True, 'message': 'Cloudflare Tunnel service installed successfully.'}
            else:
                return {'success': False, 'message': f'Service install failed: {output}'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Service install timed out.'}
        except Exception as e:
            return {'success': False, 'message': f'Service install error: {str(e)}'}

    @staticmethod
    def uninstall_service():
        """Uninstall cloudflared system service.
        
        Returns:
            dict with 'success' and 'message'.
        """
        if not CloudflareTunnelManager.is_installed():
            return {'success': False, 'message': 'cloudflared is not installed.'}

        try:
            result = subprocess.run(
                [CLOUDFLARED_EXE, 'service', 'uninstall'],
                capture_output=True, text=True, timeout=30
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode == 0:
                return {'success': True, 'message': 'Cloudflare Tunnel service uninstalled.'}
            else:
                return {'success': False, 'message': f'Service uninstall failed: {output}'}
        except Exception as e:
            return {'success': False, 'message': f'Uninstall error: {str(e)}'}

    @staticmethod
    def start_tunnel(token):
        """Start cloudflared tunnel in temporary (non-service) mode.
        
        Runs: cloudflared tunnel run --token <TOKEN>
        
        Returns:
            dict with 'success' and 'message'.
        """
        global _tunnel_process

        if not CloudflareTunnelManager.is_installed():
            return {'success': False, 'message': 'cloudflared is not installed. Please download it first.'}

        with _tunnel_lock:
            if _tunnel_process and _tunnel_process.poll() is None:
                return {'success': True, 'message': 'Tunnel is already running.'}

            try:
                _clear_logs()
                _add_log('[EZ-WebBridge] Starting Cloudflare Tunnel...')

                proc = subprocess.Popen(
                    [CLOUDFLARED_EXE, 'tunnel', 'run', '--token', token],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                )
                _tunnel_process = proc

                # Start a background thread to read output
                reader = threading.Thread(
                    target=_read_process_output,
                    args=(proc,),
                    daemon=True
                )
                reader.start()

                # Wait briefly to check if it crashes immediately
                time.sleep(2)
                if proc.poll() is not None:
                    return {
                        'success': False,
                        'message': 'Tunnel process exited immediately. Check the token and try again.',
                    }

                _add_log('[EZ-WebBridge] Tunnel process started successfully.')
                return {'success': True, 'message': 'Tunnel started.'}

            except Exception as e:
                return {'success': False, 'message': f'Failed to start tunnel: {str(e)}'}

    @staticmethod
    def stop_tunnel():
        """Stop the running tunnel process.
        
        Returns:
            dict with 'success' and 'message'.
        """
        global _tunnel_process

        with _tunnel_lock:
            if _tunnel_process is None or _tunnel_process.poll() is not None:
                _tunnel_process = None
                return {'success': True, 'message': 'Tunnel is not running.'}

            try:
                _add_log('[EZ-WebBridge] Stopping tunnel...')
                _tunnel_process.terminate()
                try:
                    _tunnel_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _tunnel_process.kill()
                    _tunnel_process.wait(timeout=5)

                _tunnel_process = None
                _add_log('[EZ-WebBridge] Tunnel stopped.')
                return {'success': True, 'message': 'Tunnel stopped.'}

            except Exception as e:
                return {'success': False, 'message': f'Failed to stop tunnel: {str(e)}'}

    # ── Status ─────────────────────────────────────────────

    @staticmethod
    def is_running():
        """Check if the tunnel subprocess is currently running."""
        global _tunnel_process
        if _tunnel_process and _tunnel_process.poll() is None:
            return True
        
        # Also check if cloudflared is running as a system service
        try:
            if is_windows():
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq cloudflared.exe'],
                    capture_output=True, text=True, timeout=5
                )
                return 'cloudflared.exe' in result.stdout
            else:
                result = subprocess.run(
                    ['pgrep', '-f', 'cloudflared'],
                    capture_output=True, timeout=5
                )
                return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def status():
        """Get full status info.
        
        Returns:
            dict with 'installed', 'running', 'bin_path'.
        """
        installed = CloudflareTunnelManager.is_installed()
        running = CloudflareTunnelManager.is_running() if installed else False
        return {
            'installed': installed,
            'running': running,
            'bin_path': CLOUDFLARED_EXE,
        }

    # ── Logs ───────────────────────────────────────────────

    @staticmethod
    def get_logs(last_n=50):
        """Get the last N lines of tunnel logs."""
        with _log_lock:
            return list(_log_buffer[-last_n:])


# ── Internal helpers ───────────────────────────────────────

def _add_log(line):
    """Thread-safe addition of a log line."""
    with _log_lock:
        _log_buffer.append(line)
        if len(_log_buffer) > MAX_LOG_LINES:
            del _log_buffer[:len(_log_buffer) - MAX_LOG_LINES]


def _clear_logs():
    """Clear the log buffer."""
    with _log_lock:
        _log_buffer.clear()


def _read_process_output(proc):
    """Background thread: read cloudflared stdout/stderr and buffer it."""
    try:
        for line in proc.stdout:
            stripped = line.rstrip('\n\r')
            if stripped:
                # Simplify cloudflared's verbose output for non-technical users
                _add_log(stripped)
    except Exception:
        pass
    finally:
        _add_log('[EZ-WebBridge] Tunnel process ended.')
