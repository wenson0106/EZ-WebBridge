import os
import subprocess
from flask import Flask, render_template, request, jsonify, redirect, url_for
from config import Config
from models import db, GlobalConfig, Domain, Service
from nginx_manager.generator import NginxConfigGenerator
from nginx_manager.cloudflare import CloudflareManager
from nginx_manager.nginx_process import NginxProcess

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Ensure directories exist
os.makedirs(Config.GENERATED_CONFIGS_DIR, exist_ok=True)
os.makedirs(os.path.join(Config.BASE_DIR, 'data'), exist_ok=True)

with app.app_context():
    db.create_all()


# ─── Helpers ───────────────────────────────────────────────

def is_setup_done():
    return GlobalConfig.get('setup_done') == 'true'


# ─── Page Routes ───────────────────────────────────────────

@app.route('/')
def index():
    if not is_setup_done():
        return redirect(url_for('setup_page'))
    return redirect(url_for('domains_page'))


@app.route('/setup')
def setup_page():
    if is_setup_done():
        return redirect(url_for('domains_page'))
    return render_template('setup.html')


@app.route('/domains')
def domains_page():
    if not is_setup_done():
        return redirect(url_for('setup_page'))
    return render_template('domains.html')


@app.route('/dashboard/<int:domain_id>')
def dashboard_page(domain_id):
    if not is_setup_done():
        return redirect(url_for('setup_page'))
    domain = Domain.query.get_or_404(domain_id)
    return render_template('dashboard.html', domain=domain)


# ─── Setup API ─────────────────────────────────────────────

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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8181, debug=True)
