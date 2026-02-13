import requests


class CloudflareManager:
    """Manages DNS records via Cloudflare API v4."""

    BASE_URL = 'https://api.cloudflare.com/client/v4'

    def __init__(self, api_token, zone_id):
        self.api_token = api_token
        self.zone_id = zone_id
        self.headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json',
        }

    def _request(self, method, endpoint, data=None):
        url = f"{self.BASE_URL}{endpoint}"
        try:
            resp = requests.request(method, url, headers=self.headers, json=data, timeout=30)
            result = resp.json()
            return result
        except requests.RequestException as e:
            return {'success': False, 'errors': [{'message': str(e)}]}

    def list_dns_records(self, record_type='A', name=None):
        """List DNS records, optionally filtered by type and name."""
        params = f"?type={record_type}"
        if name:
            params += f"&name={name}"
        return self._request('GET', f'/zones/{self.zone_id}/dns_records{params}')

    def get_record_by_name(self, name, record_type='A'):
        """Find a specific DNS record by full name."""
        result = self.list_dns_records(record_type=record_type, name=name)
        if result.get('success') and result.get('result'):
            for rec in result['result']:
                if rec['name'] == name:
                    return rec
        return None

    def create_dns_record(self, name, content, record_type='A', proxied=True, ttl=1):
        """Create a new DNS A record."""
        data = {
            'type': record_type,
            'name': name,
            'content': content,
            'ttl': ttl,
            'proxied': proxied,
        }
        return self._request('POST', f'/zones/{self.zone_id}/dns_records', data)

    def update_dns_record(self, record_id, name, content, record_type='A', proxied=True, ttl=1):
        """Update an existing DNS record."""
        data = {
            'type': record_type,
            'name': name,
            'content': content,
            'ttl': ttl,
            'proxied': proxied,
        }
        return self._request('PUT', f'/zones/{self.zone_id}/dns_records/{record_id}', data)

    def delete_dns_record(self, record_id):
        """Delete a DNS record."""
        return self._request('DELETE', f'/zones/{self.zone_id}/dns_records/{record_id}')

    def ensure_dns_record(self, name, ip_address, proxied=True):
        """Create or update a DNS A record to point to the given IP.
        
        Returns a dict with 'success', 'action' ('created'/'updated'/'unchanged'), and 'message'.
        """
        existing = self.get_record_by_name(name)

        if existing:
            if existing['content'] == ip_address and existing['proxied'] == proxied:
                return {
                    'success': True,
                    'action': 'unchanged',
                    'message': f'DNS record for {name} already points to {ip_address}',
                }
            result = self.update_dns_record(
                existing['id'], name, ip_address, proxied=proxied
            )
            if result.get('success'):
                return {
                    'success': True,
                    'action': 'updated',
                    'message': f'Updated DNS record for {name} → {ip_address}',
                }
            else:
                errors = result.get('errors', [])
                msg = errors[0].get('message', 'Unknown error') if errors else 'Unknown error'
                return {'success': False, 'action': 'error', 'message': msg}
        else:
            result = self.create_dns_record(name, ip_address, proxied=proxied)
            if result.get('success'):
                return {
                    'success': True,
                    'action': 'created',
                    'message': f'Created DNS record for {name} → {ip_address}',
                }
            else:
                errors = result.get('errors', [])
                msg = errors[0].get('message', 'Unknown error') if errors else 'Unknown error'
                return {'success': False, 'action': 'error', 'message': msg}

    def sync_services(self, domain_name, public_ip, services):
        """Sync DNS records for all services under a domain.
        
        Args:
            domain_name: The base domain (e.g. example.com)
            public_ip: The public IP to point records to
            services: List of Service objects
            
        Returns:
            List of result dicts for each DNS operation.
        """
        results = []

        # Collect all needed DNS names
        needed_names = set()
        needed_names.add(domain_name)  # Always ensure root domain

        for svc in services:
            if not svc.enabled:
                continue
            if svc.subdomain:
                full_name = f"{svc.subdomain}.{domain_name}"
            else:
                full_name = domain_name
            needed_names.add(full_name)

        # Ensure each needed DNS record exists
        for name in sorted(needed_names):
            result = self.ensure_dns_record(name, public_ip)
            result['dns_name'] = name
            results.append(result)

        return results

    def verify_token(self):
        """Verify that the API token is valid."""
        result = self._request('GET', '/user/tokens/verify')
        return result.get('success', False)
