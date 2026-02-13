import os
import subprocess
import zipfile
import shutil
import urllib.request
import platform

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
GENERATED_CONFIGS_DIR = os.path.join(BASE_DIR, 'generated_configs')

IS_WINDOWS = os.name == 'nt'

# Windows paths
NGINX_DIR = os.path.join(BASE_DIR, 'nginx_bin')
NGINX_EXE = os.path.join(NGINX_DIR, 'nginx.exe')
NGINX_CONF = os.path.join(NGINX_DIR, 'conf', 'nginx.conf')
NGINX_DOWNLOAD_URL = 'https://nginx.org/download/nginx-1.26.3.zip'
NGINX_ZIP_FOLDER = 'nginx-1.26.3'

# Linux paths (Standard)
LINUX_NGINX_CONF = '/etc/nginx/nginx.conf'
# In Docker, we might use a different path if we want to control the main config,
# but usually we can just overwrite /etc/nginx/nginx.conf.


class NginxProcess:
    """Manages the nginx binary lifecycle (Windows download/run, Linux system service)."""

    @staticmethod
    def is_installed():
        if IS_WINDOWS:
            return os.path.isfile(NGINX_EXE)
        else:
            # On Linux, check if nginx is in PATH
            return shutil.which('nginx') is not None

    @staticmethod
    def download_and_install():
        """Download and extract nginx (Windows only)."""
        if not IS_WINDOWS:
            return True  # Assume installed via package manager in Docker

        os.makedirs(NGINX_DIR, exist_ok=True)
        zip_path = os.path.join(NGINX_DIR, 'nginx.zip')

        # Download
        print(f'[nginx] Downloading from {NGINX_DOWNLOAD_URL} ...')
        urllib.request.urlretrieve(NGINX_DOWNLOAD_URL, zip_path)

        # Extract
        print('[nginx] Extracting...')
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(NGINX_DIR)

        # Move contents from nested folder to NGINX_DIR
        nested = os.path.join(NGINX_DIR, NGINX_ZIP_FOLDER)
        if os.path.isdir(nested):
            for item in os.listdir(nested):
                src = os.path.join(nested, item)
                dst = os.path.join(NGINX_DIR, item)
                if os.path.exists(dst):
                    if os.path.isdir(dst):
                        shutil.rmtree(dst)
                    else:
                        os.remove(dst)
                shutil.move(src, dst)
            shutil.rmtree(nested)

        # Cleanup zip
        os.remove(zip_path)
        print('[nginx] Installed successfully.')
        return True

    @staticmethod
    def write_master_config():
        """Write the master nginx.conf that includes our generated configs."""
        os.makedirs(GENERATED_CONFIGS_DIR, exist_ok=True)

        # Include path logic
        if IS_WINDOWS:
            target_conf = NGINX_CONF
            os.makedirs(os.path.dirname(NGINX_CONF), exist_ok=True)
            # Nginx on Windows expects / for paths in config
            include_path = GENERATED_CONFIGS_DIR.replace('\\', '/') + '/*.conf'
            pid_path = ''  # Default
        else:
            target_conf = LINUX_NGINX_CONF
            # On Linux (Docker), generated configs are in /app/generated_configs
            include_path = os.path.join(GENERATED_CONFIGS_DIR, '*.conf')
            # Nginx might need a specific PID path if running as non-root, but here we run as root in Docker usually.
            pid_path = 'pid /run/nginx.pid;'

        config = f"""worker_processes auto;
{pid_path}

events {{
    worker_connections 1024;
}}

http {{
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 0;

    include       mime.types;
    default_type  application/octet-stream;

    # Logging
    access_log  /var/log/nginx/access.log;
    error_log   /var/log/nginx/error.log;

    # Include all generated proxy configs
    include {include_path};
}}
"""
        # Adjust logging paths for Windows
        if IS_WINDOWS:
            config = config.replace('/var/log/nginx/', 'logs/')
            config = config.replace('pid /run/nginx.pid;', '')

        try:
            with open(target_conf, 'w', encoding='utf-8') as f:
                f.write(config)
            print(f'[nginx] Master config written to {target_conf}')
        except PermissionError:
            print(f'[nginx] Warning: Could not write to {target_conf}. Assuming running in restricted env or config already managed.')

    @staticmethod
    def is_running():
        """Check if nginx process is running."""
        try:
            if IS_WINDOWS:
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq nginx.exe'],
                    capture_output=True, text=True, timeout=5
                )
                return 'nginx.exe' in result.stdout
            else:
                # Docker/Linux: check if nginx pid exists or pgrep
                # Simple check using pgrep if available, or just check return code of 'pidof nginx'
                result = subprocess.run(['pgrep', 'nginx'], capture_output=True)
                return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def start():
        """Start nginx."""
        if not NginxProcess.is_installed():
            return {'success': False, 'message': 'Nginx is not installed.'}

        if NginxProcess.is_running():
            return {'success': True, 'message': 'Nginx is already running.'}

        NginxProcess.write_master_config()

        try:
            if IS_WINDOWS:
                logs_dir = os.path.join(NGINX_DIR, 'logs')
                os.makedirs(logs_dir, exist_ok=True)
                subprocess.Popen(
                    [NGINX_EXE],
                    cwd=NGINX_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                # Linux/Docker start
                subprocess.Popen(['nginx'])
                
            return {'success': True, 'message': 'Nginx started.'}
        except Exception as e:
            return {'success': False, 'message': f'Failed to start nginx: {str(e)}'}

    @staticmethod
    def reload():
        """Reload nginx configuration (nginx -s reload)."""
        if not NginxProcess.is_installed():
            return {'success': False, 'message': 'Nginx is not installed.'}

        if not NginxProcess.is_running():
            return NginxProcess.start()

        NginxProcess.write_master_config()

        try:
            if IS_WINDOWS:
                cmd = [NGINX_EXE, '-s', 'reload']
                cwd = NGINX_DIR
            else:
                cmd = ['nginx', '-s', 'reload']
                cwd = '/'

            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return {'success': True, 'message': 'Nginx reloaded successfully.'}
            else:
                err = result.stderr.strip() or result.stdout.strip()
                return {'success': False, 'message': f'Reload failed: {err}'}
        except Exception as e:
            return {'success': False, 'message': f'Reload error: {str(e)}'}

    @staticmethod
    def test_config():
        """Test nginx configuration (nginx -t)."""
        if not NginxProcess.is_installed():
            return {'success': False, 'message': 'Nginx is not installed.'}

        NginxProcess.write_master_config()

        try:
            if IS_WINDOWS:
                cmd = [NGINX_EXE, '-t']
                cwd = NGINX_DIR
            else:
                cmd = ['nginx', '-t']
                cwd = '/'

            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True, text=True, timeout=10
            )
            output = (result.stderr + result.stdout).strip()
            success = result.returncode == 0
            return {'success': success, 'message': output}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def stop():
        """Stop nginx."""
        if not NginxProcess.is_running():
            return {'success': True, 'message': 'Nginx is not running.'}

        try:
            if IS_WINDOWS:
                cmd = [NGINX_EXE, '-s', 'stop']
                cwd = NGINX_DIR
            else:
                cmd = ['nginx', '-s', 'stop']
                cwd = '/'

            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return {'success': True, 'message': 'Nginx stopped.'}
            else:
                err = result.stderr.strip() or result.stdout.strip()
                return {'success': False, 'message': f'Stop failed: {err}'}
        except Exception as e:
            return {'success': False, 'message': f'Stop error: {str(e)}'}

    @staticmethod
    def status():
        """Get nginx status info."""
        installed = NginxProcess.is_installed()
        running = NginxProcess.is_running() if installed else False
        return {
            'installed': installed,
            'running': running,
            'nginx_dir': NGINX_DIR if IS_WINDOWS else '/usr/sbin/nginx',
            'config_path': NGINX_CONF if IS_WINDOWS else LINUX_NGINX_CONF,
        }
