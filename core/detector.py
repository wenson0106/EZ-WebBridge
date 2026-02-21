"""
Environment detection utilities for EZ-WebBridge.
Detects OS, architecture, and determines correct cloudflared binary names.
"""

import platform
import os


def get_os():
    """Return normalized OS name: 'windows', 'darwin', or 'linux'."""
    system = platform.system().lower()
    if system == 'windows':
        return 'windows'
    elif system == 'darwin':
        return 'darwin'
    else:
        return 'linux'


def get_arch():
    """Return normalized architecture: 'amd64' or 'arm64'."""
    machine = platform.machine().lower()
    if machine in ('x86_64', 'amd64', 'x64'):
        return 'amd64'
    elif machine in ('aarch64', 'arm64'):
        return 'arm64'
    else:
        # Fallback to amd64 for most desktop users
        return 'amd64'


def get_cloudflared_filename():
    """Return the correct cloudflared binary filename for the current platform.
    
    Matches the naming convention used by Cloudflare's GitHub releases:
    https://github.com/cloudflare/cloudflared/releases
    """
    os_name = get_os()
    arch = get_arch()

    if os_name == 'windows':
        return f'cloudflared-windows-{arch}.exe'
    elif os_name == 'darwin':
        return f'cloudflared-darwin-{arch}.tgz'
    else:
        return f'cloudflared-linux-{arch}'


def get_cloudflared_download_url(version='latest'):
    """Return the download URL for cloudflared from GitHub releases."""
    filename = get_cloudflared_filename()
    if version == 'latest':
        return f'https://github.com/cloudflare/cloudflared/releases/latest/download/{filename}'
    return f'https://github.com/cloudflare/cloudflared/releases/download/{version}/{filename}'


def get_cloudflared_exe_name():
    """Return the local executable name for cloudflared."""
    if get_os() == 'windows':
        return 'cloudflared.exe'
    return 'cloudflared'


def is_windows():
    return os.name == 'nt'
