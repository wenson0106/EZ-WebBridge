import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'nginx-proxy-manager-secret-key')
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(BASE_DIR, "data", "data.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    GENERATED_CONFIGS_DIR = os.path.join(BASE_DIR, 'generated_configs')
