import os
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from config import Config
from models import db, GlobalConfig, Domain, Service, TunnelConfig, CaddyConfig, UserAccount
from nginx_manager.generator import NginxConfigGenerator
from nginx_manager.cloudflare import CloudflareManager
from nginx_manager.nginx_process import NginxProcess
from core.cf_tunnel import CloudflareTunnelManager
from core.caddy import CaddyManager
from core.auth import (
    hash_password, verify_password,
    login_admin, logout_admin, is_admin_logged_in, require_admin,
    login_visitor_for_service, is_visitor_authed_for_service,
)

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Ensure directories exist
os.makedirs(Config.GENERATED_CONFIGS_DIR, exist_ok=True)
os.makedirs(Config.DATA_DIR, exist_ok=True)
os.makedirs(Config.BIN_DIR, exist_ok=True)

with app.app_context():
    db.create_all()


# ─── Helpers ───────────────────────────────────────────────

def is_setup_done():
    return GlobalConfig.get('setup_done') == 'true'


def get_connection_mode():
    return GlobalConfig.get('connection_mode')  # 'tunnel' or 'nginx' or None


# ─── Page Routes ───────────────────────────────────────────

@app.route('/')
def index():
    mode = get_connection_mode()
    if not mode:
        return redirect(url_for('triage_page'))
    if mode == 'tunnel':
        if is_setup_done():
            return redirect(url_for('tunnel_dashboard_page'))
        return redirect(url_for('tunnel_setup_page'))
    elif mode == 'caddy':
        if is_setup_done():
            return redirect(url_for('caddy_dashboard_page'))
        return redirect(url_for('caddy_setup_page'))
    else:  # nginx
        if is_setup_done():
            return redirect(url_for('domains_page'))
        return redirect(url_for('setup_page'))


@app.route('/triage')
def triage_page():
    return render_template('triage.html')


@app.route('/tunnel/setup')
def tunnel_setup_page():
    return render_template('tunnel_setup.html')


@app.route('/tunnel/dashboard')
def tunnel_dashboard_page():
    tunnel = TunnelConfig.query.order_by(TunnelConfig.id.desc()).first()
    return render_template('tunnel_dashboard.html', tunnel=tunnel)


@app.route('/caddy/setup')
def caddy_setup_page():
    return render_template('caddy_setup.html')


@app.route('/caddy/dashboard')
def caddy_dashboard_page():
    caddy_cfg = CaddyConfig.query.first()
    return render_template('caddy_dashboard.html', caddy_cfg=caddy_cfg)


@app.route('/setup')
def setup_page():
    if is_setup_done() and get_connection_mode() == 'nginx':
        return redirect(url_for('domains_page'))
    return render_template('setup.html')


@app.route('/domains')
def domains_page():
    if not is_setup_done():
        return redirect(url_for('index'))
    return render_template('domains.html')


@app.route('/dashboard/<int:domain_id>')
def dashboard_page(domain_id):
    if not is_setup_done():
        return redirect(url_for('index'))
    domain = Domain.query.get_or_404(domain_id)
    return render_template('dashboard.html', domain=domain)


# ─── Mode Selection API ───────────────────────────────────

@app.route('/api/mode', methods=['GET'])
def api_get_mode():
    mode = get_connection_mode()
    return jsonify({'success': True, 'mode': mode})


@app.route('/api/mode', methods=['POST'])
def api_set_mode():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '未提供資料'}), 400

    mode = data.get('mode', '').strip().lower()
    if mode not in ('tunnel', 'nginx', 'caddy'):
        return jsonify({'success': False, 'message': '無效的模式，請選擇 tunnel、nginx 或 caddy'}), 400

    GlobalConfig.set('connection_mode', mode)
    return jsonify({'success': True, 'mode': mode})


@app.route('/api/reset', methods=['POST'])
def api_reset():
    """Reset all settings and return to triage."""
    # Stop running services
    if CloudflareTunnelManager.is_running():
        CloudflareTunnelManager.stop_tunnel()
    if CaddyManager.is_running():
        CaddyManager.stop()

    GlobalConfig.set('connection_mode', '')
    GlobalConfig.set('setup_done', 'false')
    return jsonify({'success': True, 'message': '已重置，將返回模式選擇頁面'})


# ─── Tunnel API ────────────────────────────────────────────

@app.route('/api/tunnel/install-binary', methods=['POST'])
def api_tunnel_install_binary():
    """Download cloudflared binary."""
    if CloudflareTunnelManager.is_installed():
        return jsonify({'success': True, 'message': 'cloudflared 已安裝'})

    result = CloudflareTunnelManager.download_binary()
    return jsonify(result)


@app.route('/api/tunnel/setup', methods=['POST'])
def api_tunnel_setup():
    """Save tunnel config and start the tunnel."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '未提供資料'}), 400

    token = data.get('token', '').strip()
    local_port = data.get('local_port', 80)
    install_as_service = data.get('install_as_service', False)
    public_url = data.get('public_url', '').strip()

    if not token:
        return jsonify({'success': False, 'message': '請輸入 Cloudflare Tunnel Token'}), 400

    # Basic token validation
    if len(token) < 20:
        return jsonify({'success': False, 'message': 'Token 格式看起來有誤，請重新檢查複製'}), 400

    try:
        local_port = int(local_port)
        if not (1 <= local_port <= 65535):
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '埠號必須在 1-65535 之間'}), 400

    # Save or update tunnel config
    tunnel = TunnelConfig.query.first()
    if tunnel:
        tunnel.token = token
        tunnel.local_port = local_port
        tunnel.install_as_service = install_as_service
        tunnel.public_url = public_url
    else:
        tunnel = TunnelConfig(
            token=token,
            local_port=local_port,
            install_as_service=install_as_service,
            public_url=public_url,
        )
        db.session.add(tunnel)

    db.session.commit()

    # Start the tunnel
    if install_as_service:
        result = CloudflareTunnelManager.install_service(token)
    else:
        result = CloudflareTunnelManager.start_tunnel(token)

    if result['success']:
        GlobalConfig.set('connection_mode', 'tunnel')
        GlobalConfig.set('setup_done', 'true')

    return jsonify(result)


@app.route('/api/tunnel/status', methods=['GET'])
def api_tunnel_status():
    """Get tunnel status."""
    status = CloudflareTunnelManager.status()
    tunnel = TunnelConfig.query.first()

    return jsonify({
        'success': True,
        **status,
        'config': tunnel.to_dict() if tunnel else None,
    })


@app.route('/api/tunnel/start', methods=['POST'])
def api_tunnel_start():
    """Start the tunnel using saved config."""
    tunnel = TunnelConfig.query.first()
    if not tunnel:
        return jsonify({'success': False, 'message': '尚未設定 Tunnel，請先完成設定'}), 400

    if tunnel.install_as_service:
        result = CloudflareTunnelManager.install_service(tunnel.token)
    else:
        result = CloudflareTunnelManager.start_tunnel(tunnel.token)

    return jsonify(result)


@app.route('/api/tunnel/stop', methods=['POST'])
def api_tunnel_stop():
    """Stop the tunnel."""
    result = CloudflareTunnelManager.stop_tunnel()
    return jsonify(result)


@app.route('/api/tunnel/logs', methods=['GET'])
def api_tunnel_logs():
    """Get simplified tunnel logs."""
    last_n = request.args.get('n', 30, type=int)
    logs = CloudflareTunnelManager.get_logs(last_n)
    return jsonify({'success': True, 'logs': logs})


# ─── Setup API (Nginx mode) ───────────────────────────────

@app.route('/api/setup', methods=['POST'])
def api_setup():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    domains_data = data.get('domains', [])
    if not domains_data:
        return jsonify({'success': False, 'message': 'At least one domain is required'}), 400

    errors = []
    created = []

    for d in domains_data:
        domain_name = d.get('domain_name', '').strip().lower()
        public_ip = d.get('public_ip', '').strip()
        cf_token = d.get('cloudflare_api_token', '').strip()
        cf_zone = d.get('cloudflare_zone_id', '').strip()

        if not all([domain_name, public_ip, cf_token, cf_zone]):
            errors.append(f'Missing fields for domain: {domain_name or "(empty)"}')
            continue

        existing = Domain.query.filter_by(domain_name=domain_name).first()
        if existing:
            errors.append(f'Domain {domain_name} already exists')
            continue

        domain = Domain(
            domain_name=domain_name,
            public_ip=public_ip,
            cloudflare_api_token=cf_token,
            cloudflare_zone_id=cf_zone,
        )
        db.session.add(domain)
        created.append(domain_name)

    if created:
        db.session.commit()
        GlobalConfig.set('connection_mode', 'nginx')
        GlobalConfig.set('setup_done', 'true')

    return jsonify({
        'success': len(created) > 0,
        'created': created,
        'errors': errors,
    })


# ─── Domain API ────────────────────────────────────────────

@app.route('/api/domains', methods=['GET'])
def api_get_domains():
    domains = Domain.query.order_by(Domain.created_at.desc()).all()
    return jsonify({'success': True, 'domains': [d.to_dict() for d in domains]})


@app.route('/api/domains', methods=['POST'])
def api_add_domain():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    domain_name = data.get('domain_name', '').strip().lower()
    public_ip = data.get('public_ip', '').strip()
    cf_token = data.get('cloudflare_api_token', '').strip()
    cf_zone = data.get('cloudflare_zone_id', '').strip()

    if not all([domain_name, public_ip, cf_token, cf_zone]):
        return jsonify({'success': False, 'message': 'All fields are required'}), 400

    existing = Domain.query.filter_by(domain_name=domain_name).first()
    if existing:
        return jsonify({'success': False, 'message': f'Domain {domain_name} already exists'}), 409

    domain = Domain(
        domain_name=domain_name,
        public_ip=public_ip,
        cloudflare_api_token=cf_token,
        cloudflare_zone_id=cf_zone,
    )
    db.session.add(domain)
    db.session.commit()

    return jsonify({'success': True, 'domain': domain.to_dict()})


@app.route('/api/domains/<int:domain_id>', methods=['DELETE'])
def api_delete_domain(domain_id):
    domain = Domain.query.get_or_404(domain_id)
    
    # Remove generated config
    generator = NginxConfigGenerator(Config.GENERATED_CONFIGS_DIR)
    generator.remove_config(domain.domain_name)
    
    db.session.delete(domain)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Domain {domain.domain_name} deleted'})


@app.route('/api/domains/<int:domain_id>', methods=['PUT'])
def api_update_domain(domain_id):
    domain = Domain.query.get_or_404(domain_id)
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    if 'public_ip' in data:
        domain.public_ip = data['public_ip'].strip()
    if 'cloudflare_api_token' in data:
        domain.cloudflare_api_token = data['cloudflare_api_token'].strip()
    if 'cloudflare_zone_id' in data:
        domain.cloudflare_zone_id = data['cloudflare_zone_id'].strip()

    db.session.commit()
    return jsonify({'success': True, 'domain': domain.to_dict()})


# ─── Service API ───────────────────────────────────────────

@app.route('/api/services/<int:domain_id>', methods=['GET'])
def api_get_services(domain_id):
    Domain.query.get_or_404(domain_id)
    services = Service.query.filter_by(domain_id=domain_id).order_by(Service.created_at.desc()).all()
    return jsonify({'success': True, 'services': [s.to_dict() for s in services]})


@app.route('/api/services', methods=['POST'])
def api_add_service():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    domain_id = data.get('domain_id')
    internal_address = data.get('internal_address', '').strip()
    subdomain = data.get('subdomain', '').strip().lower()
    path_prefix = data.get('path_prefix', '').strip()
    description = data.get('description', '').strip()

    if not domain_id or not internal_address or not path_prefix:
        return jsonify({'success': False, 'message': 'Domain, internal address, and path prefix are required'}), 400

    Domain.query.get_or_404(domain_id)

    # Validate path_prefix
    if path_prefix == '/':
        return jsonify({'success': False, 'message': 'Path prefix cannot be "/" alone. Please specify a sub-path like "/api/" or "/app/"'}), 400

    # Normalize path
    if not path_prefix.startswith('/'):
        path_prefix = '/' + path_prefix
    if not path_prefix.endswith('/'):
        path_prefix = path_prefix + '/'

    # Check for duplicate
    existing = Service.query.filter_by(
        domain_id=domain_id, subdomain=subdomain, path_prefix=path_prefix
    ).first()
    if existing:
        return jsonify({'success': False, 'message': f'A service with this subdomain and path already exists'}), 409

    service = Service(
        domain_id=domain_id,
        internal_address=internal_address,
        subdomain=subdomain,
        path_prefix=path_prefix,
        description=description,
    )
    db.session.add(service)
    db.session.commit()

    return jsonify({'success': True, 'service': service.to_dict()})


@app.route('/api/services/<int:service_id>', methods=['PUT'])
def api_update_service(service_id):
    service = Service.query.get_or_404(service_id)
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    if 'internal_address' in data:
        service.internal_address = data['internal_address'].strip()
    if 'subdomain' in data:
        service.subdomain = data['subdomain'].strip().lower()
    if 'path_prefix' in data:
        path = data['path_prefix'].strip()
        if path == '/':
            return jsonify({'success': False, 'message': 'Path prefix cannot be "/"'}), 400
        if not path.startswith('/'):
            path = '/' + path
        if not path.endswith('/'):
            path = path + '/'
        service.path_prefix = path
    if 'description' in data:
        service.description = data['description'].strip()
    if 'enabled' in data:
        service.enabled = bool(data['enabled'])

    db.session.commit()
    return jsonify({'success': True, 'service': service.to_dict()})


@app.route('/api/services/<int:service_id>', methods=['DELETE'])
def api_delete_service(service_id):
    service = Service.query.get_or_404(service_id)
    db.session.delete(service)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Service deleted'})


# ─── Nginx Status / Control ────────────────────────────────

@app.route('/api/nginx/status', methods=['GET'])
def api_nginx_status():
    status = NginxProcess.status()
    return jsonify({'success': True, **status})


@app.route('/api/nginx/install', methods=['POST'])
def api_nginx_install():
    if NginxProcess.is_installed():
        return jsonify({'success': True, 'message': 'Nginx is already installed.'})
    try:
        NginxProcess.download_and_install()
        NginxProcess.write_master_config()
        return jsonify({'success': True, 'message': 'Nginx downloaded and installed.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/nginx/start', methods=['POST'])
def api_nginx_start():
    result = NginxProcess.start()
    return jsonify(result)


@app.route('/api/nginx/stop', methods=['POST'])
def api_nginx_stop():
    result = NginxProcess.stop()
    return jsonify(result)


# ─── Apply / Sync ─────────────────────────────────────────

@app.route('/api/apply/<int:domain_id>', methods=['POST'])
def api_apply(domain_id):
    domain = Domain.query.get_or_404(domain_id)
    services = Service.query.filter_by(domain_id=domain_id).all()

    results = {
        'nginx': {'success': False, 'files': [], 'errors': []},
        'cloudflare': {'success': False, 'results': [], 'errors': []},
    }

    # 0. Ensure nginx is installed
    if not NginxProcess.is_installed():
        try:
            NginxProcess.download_and_install()
            results['nginx']['errors'].append('Nginx was auto-installed.')
        except Exception as e:
            results['nginx']['errors'].append(f'Failed to install nginx: {str(e)}')
            return jsonify({'success': False, 'results': results})

    # 1. Generate nginx config
    generator = NginxConfigGenerator(Config.GENERATED_CONFIGS_DIR)
    enabled_services = [s for s in services if s.enabled]
    
    if enabled_services:
        gen_result = generator.generate_config(domain, enabled_services)
        results['nginx']['files'] = gen_result['files']
        results['nginx']['errors'].extend(gen_result['errors'])
        results['nginx']['success'] = len(gen_result['files']) > 0
    else:
        generator.remove_config(domain.domain_name)
        results['nginx']['success'] = True
        results['nginx']['files'] = []
        results['nginx']['errors'].append('No enabled services. Config file removed.')

    # 2. Test nginx config
    test_result = NginxProcess.test_config()
    if not test_result['success']:
        results['nginx']['errors'].append(f'Config test failed: {test_result["message"]}')
        results['nginx']['success'] = False
    
    # 3. Reload (or start) nginx
    if results['nginx']['success']:
        reload_result = NginxProcess.reload()
        if reload_result['success']:
            results['nginx']['errors'].append(reload_result['message'])
        else:
            results['nginx']['errors'].append(f'Nginx reload failed: {reload_result["message"]}')
            results['nginx']['success'] = False

    # 4. Sync Cloudflare DNS
    try:
        cf = CloudflareManager(domain.cloudflare_api_token, domain.cloudflare_zone_id)
        dns_results = cf.sync_services(domain.domain_name, domain.public_ip, enabled_services)
        results['cloudflare']['results'] = dns_results
        results['cloudflare']['success'] = all(r.get('success') for r in dns_results)
        results['cloudflare']['errors'] = [
            r['message'] for r in dns_results if not r.get('success')
        ]
    except Exception as e:
        results['cloudflare']['errors'].append(str(e))

    overall_success = results['nginx']['success'] and results['cloudflare']['success']

    return jsonify({
        'success': overall_success,
        'results': results,
    })


# ─── Caddy API ─────────────────────────────────────────────

@app.route('/api/caddy/install-binary', methods=['POST'])
def api_caddy_install_binary():
    """Download Caddy binary."""
    if CaddyManager.is_installed():
        return jsonify({'success': True, 'message': 'Caddy 已安裝'})
    result = CaddyManager.download_binary()
    return jsonify(result)


@app.route('/api/caddy/setup', methods=['POST'])
def api_caddy_setup():
    """Save Caddy service list, generate Caddyfile, and start Caddy."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '未提供資料'}), 400

    services = data.get('services', [])
    if not services:
        return jsonify({'success': False, 'message': '請至少新增一個服務'}), 400

    # Validate
    for svc in services:
        if not svc.get('domain') or not svc.get('target'):
            return jsonify({'success': False, 'message': '每個服務都必須填寫網域和目標位址'}), 400

    # Persist
    cfg = CaddyConfig.query.first()
    services_json = json.dumps(services)
    if cfg:
        cfg.services_json = services_json
    else:
        cfg = CaddyConfig(services_json=services_json)
        db.session.add(cfg)
    db.session.commit()

    # Generate Caddyfile
    CaddyManager.generate_caddyfile(services)

    # Install binary if not present
    if not CaddyManager.is_installed():
        dl = CaddyManager.download_binary()
        if not dl['success']:
            return jsonify(dl), 500

    # Start / reload
    if CaddyManager.is_running():
        result = CaddyManager.reload()
    else:
        result = CaddyManager.start()

    if result['success']:
        GlobalConfig.set('connection_mode', 'caddy')
        GlobalConfig.set('setup_done', 'true')

    return jsonify(result)


@app.route('/api/caddy/status', methods=['GET'])
def api_caddy_status():
    status = CaddyManager.status()
    cfg = CaddyConfig.query.first()
    return jsonify({'success': True, **status, 'config': cfg.to_dict() if cfg else None})


@app.route('/api/caddy/start', methods=['POST'])
def api_caddy_start():
    result = CaddyManager.start()
    return jsonify(result)


@app.route('/api/caddy/stop', methods=['POST'])
def api_caddy_stop():
    result = CaddyManager.stop()
    return jsonify(result)


@app.route('/api/caddy/reload', methods=['POST'])
def api_caddy_reload():
    result = CaddyManager.reload()
    return jsonify(result)


@app.route('/api/caddy/logs', methods=['GET'])
def api_caddy_logs():
    last_n = request.args.get('n', 30, type=int)
    logs = CaddyManager.get_logs(last_n)
    return jsonify({'success': True, 'logs': logs})


@app.route('/api/caddy/services', methods=['PUT'])
def api_caddy_update_services():
    """Update service list and hot-reload Caddy."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '未提供資料'}), 400

    services = data.get('services', [])
    cfg = CaddyConfig.query.first()
    if not cfg:
        return jsonify({'success': False, 'message': '尚未完成初始設定'}), 400

    cfg.services_json = json.dumps(services)
    db.session.commit()

    CaddyManager.generate_caddyfile(services)
    result = CaddyManager.reload()
    return jsonify(result)


# ─── EZ-Portal Auth Routes ─────────────────────────────────

@app.route('/portal/login')
def portal_login_page():
    next_url = request.args.get('next', '')
    if is_admin_logged_in():
        return redirect(url_for('portal_admin_page'))
    return render_template('portal_login.html', error=None, next_url=next_url)


@app.route('/portal/auth', methods=['POST'])
def portal_auth():
    """Handle login form submission."""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    next_url = request.form.get('next', '') or url_for('portal_admin_page')

    user = UserAccount.query.filter_by(username=username).first()
    if user and verify_password(password, user.password_hash):
        login_admin(user.id)
        return redirect(next_url)

    return render_template('portal_login.html',
                           error='使用者名稱或密碼錯誤',
                           next_url=next_url)


@app.route('/portal/logout', methods=['POST'])
def portal_logout():
    logout_admin()
    return redirect(url_for('portal_login_page'))


@app.route('/portal/admin')
@require_admin
def portal_admin_page():
    return render_template('portal_admin.html')


# ─── EZ-Portal API ─────────────────────────────────────────

@app.route('/api/portal/setup', methods=['POST'])
def api_portal_setup():
    """First-time setup: create the admin user."""
    if UserAccount.query.filter_by(is_admin=True).first():
        return jsonify({'success': False, 'message': '管理員已存在，請登入後管理'}), 409

    data = request.get_json() or {}
    username = data.get('username', 'admin').strip() or 'admin'
    password = data.get('password', '').strip()

    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': '密碼至少需要 6 個字元'}), 400

    user = UserAccount(
        username=username,
        password_hash=hash_password(password),
        is_admin=True,
    )
    db.session.add(user)
    db.session.commit()
    login_admin(user.id)
    return jsonify({'success': True, 'message': f'管理員帳號「{username}」建立完成！'})


@app.route('/api/portal/users', methods=['GET'])
@require_admin
def api_portal_list_users():
    users = UserAccount.query.order_by(UserAccount.created_at.desc()).all()
    return jsonify({'success': True, 'users': [u.to_dict() for u in users]})


@app.route('/api/portal/users', methods=['POST'])
@require_admin
def api_portal_add_user():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    is_admin = bool(data.get('is_admin', False))

    if not username or not password:
        return jsonify({'success': False, 'message': '使用者名稱和密碼為必填欄位'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'message': '密碼至少需要 6 個字元'}), 400
    if UserAccount.query.filter_by(username=username).first():
        return jsonify({'success': False, 'message': '該使用者名稱已存在'}), 409

    user = UserAccount(username=username, password_hash=hash_password(password), is_admin=is_admin)
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict(), 'message': f'帳號「{username}」已建立'})


@app.route('/api/portal/users/<int:user_id>', methods=['DELETE'])
@require_admin
def api_portal_delete_user(user_id):
    user = UserAccount.query.get_or_404(user_id)
    # Prevent self-deletion
    if session.get('ez_portal_admin') == user_id:
        return jsonify({'success': False, 'message': '無法刪除自己的帳號'}), 400
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True, 'message': f'帳號「{user.username}」已刪除'})


@app.route('/api/portal/change-password', methods=['POST'])
@require_admin
def api_portal_change_password():
    current_user_id = session.get('ez_portal_admin')
    user = UserAccount.query.get(current_user_id)
    if not user:
        return jsonify({'success': False, 'message': '無法找到當前使用者'}), 404

    data = request.get_json() or {}
    new_password = data.get('password', '')
    if not new_password or len(new_password) < 6:
        return jsonify({'success': False, 'message': '密碼至少需要 6 個字元'}), 400

    user.password_hash = hash_password(new_password)
    db.session.commit()
    return jsonify({'success': True, 'message': '密碼已更新'})


@app.route('/api/portal/services/<int:service_id>/auth', methods=['PUT'])
@require_admin
def api_portal_toggle_service_auth(service_id):
    """Toggle EZ-Portal protection on a specific service."""
    service = Service.query.get_or_404(service_id)
    data = request.get_json() or {}
    service.auth_enabled = bool(data.get('auth_enabled', not service.auth_enabled))
    db.session.commit()
    state = '已開啟' if service.auth_enabled else '已關閉'
    return jsonify({'success': True, 'auth_enabled': service.auth_enabled,
                    'message': f'EZ-Portal {state}'})


@app.route('/api/portal/status', methods=['GET'])
def api_portal_status():
    """Check if EZ-Portal has been configured (admin exists)."""
    has_admin = UserAccount.query.filter_by(is_admin=True).first() is not None
    return jsonify({
        'success': True,
        'configured': has_admin,
        'logged_in': is_admin_logged_in(),
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8181, debug=True)
