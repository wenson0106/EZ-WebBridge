from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class GlobalConfig(db.Model):
    """Global configuration store (key-value pairs)."""
    __tablename__ = 'global_config'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)

    @staticmethod
    def get(key, default=None):
        config = GlobalConfig.query.filter_by(key=key).first()
        return config.value if config else default

    @staticmethod
    def set(key, value):
        config = GlobalConfig.query.filter_by(key=key).first()
        if config:
            config.value = value
        else:
            config = GlobalConfig(key=key, value=value)
            db.session.add(config)
        db.session.commit()


class Domain(db.Model):
    """A domain with its Cloudflare credentials and associated IP."""
    __tablename__ = 'domains'
    id = db.Column(db.Integer, primary_key=True)
    domain_name = db.Column(db.String(255), unique=True, nullable=False)
    public_ip = db.Column(db.String(45), nullable=False)
    cloudflare_api_token = db.Column(db.String(255), nullable=False)
    cloudflare_zone_id = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    services = db.relationship('Service', backref='domain', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'domain_name': self.domain_name,
            'public_ip': self.public_ip,
            'cloudflare_zone_id': self.cloudflare_zone_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'service_count': len(self.services),
        }


class Service(db.Model):
    """A proxy service mapping an internal address to an external path."""
    __tablename__ = 'services'
    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domains.id'), nullable=False)
    internal_address = db.Column(db.String(255), nullable=False)  # e.g. 192.168.50.243:5000
    subdomain = db.Column(db.String(255), nullable=True, default='')  # e.g. 'api' for api.example.com
    path_prefix = db.Column(db.String(255), nullable=False)  # e.g. '/website_name/'
    description = db.Column(db.String(500), nullable=True, default='')
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        domain = Domain.query.get(self.domain_id)
        domain_name = domain.domain_name if domain else ''
        
        if self.subdomain:
            full_domain = f"{self.subdomain}.{domain_name}"
        else:
            full_domain = domain_name

        external_url = f"https://{full_domain}{self.path_prefix}"

        return {
            'id': self.id,
            'domain_id': self.domain_id,
            'internal_address': self.internal_address,
            'subdomain': self.subdomain or '',
            'path_prefix': self.path_prefix,
            'description': self.description or '',
            'enabled': self.enabled,
            'external_url': external_url,
            'internal_url': f"http://{self.internal_address}",
            'full_domain': full_domain,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
