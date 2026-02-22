# EZ-WebBridge

**一鍵架設本機服務對外連線的全能工具**，支援三種連線模式 + 免費 SSL，Nordic 設計風格的現代化 Web UI。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11-blue)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)

---

## ✨ 功能

| 功能 | 說明 |
|------|------|
| 🌩️ **Cloudflare Tunnel 模式** | 無需固定 IP、無需路由器設定，直接穿透 NAT |
| ⚡ **Caddy 直連模式** | 有固定 IP 的輕量方案，自動申請 Let's Encrypt SSL |
| 🖥️ **Nginx 直連模式** | 固定 IP 的進階控制，完整自訂 Proxy 規則 |
| 🔐 **EZ-Portal 身分驗證** | 為任意服務一鍵加上登入保護層，無需修改原應用程式 |
| 🔔 **Wake-on-LAN** | 遠端喚醒區網內的其他機器 |

---

## 🚀 快速開始（Docker）

### 一般部署（資料持久化）

```bash
git clone https://github.com/wenson0106/EZ-WebBridge.git
cd EZ-WebBridge
docker compose up -d --build
```

開啟瀏覽器：`http://localhost:8181`

### 快速測試（不 mount 資料夾）

```bash
docker build -t ez-webbridge:test .
docker run -d --name ez-test -p 8181:8181 -p 80:80 ez-webbridge:test
```

> ⚠️ 測試模式下容器停止後資料會消失，僅供功能驗證使用。

---

## 📋 系統需求

| 項目 | 最低需求 |
|------|----------|
| Docker | 24.x+ |
| Docker Compose | v2.x+ |
| 作業系統 | Windows / Linux / macOS |
| RAM | 512 MB |

**不使用 Docker**（直接跑 Python）：需要 Python 3.11+、Nginx（Linux）

---

## 🔧 不使用 Docker（手動安裝）

```bash
git clone https://github.com/wenson0106/EZ-WebBridge.git
cd EZ-WebBridge

pip install -r requirements.txt
python app.py
```

開啟 `http://localhost:8181`（Nginx 需另外安裝並確保在 PATH 中）

---

## 🗂️ 專案結構

```
EZ-WebBridge/
├── app.py                    # Flask 主應用程式
├── config.py                 # 設定（PORT、路徑、SECRET_KEY）
├── models.py                 # SQLAlchemy 資料模型
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
│
├── core/                     # 核心功能模組
│   ├── auth.py               # EZ-Portal 身分驗證（scrypt 雜湊）
│   ├── caddy.py              # Caddy Binary 管理與 Caddyfile 產生
│   ├── cf_tunnel.py          # Cloudflare Tunnel 管理
│   ├── detector.py           # 作業系統偵測
│   └── wol.py                # Wake-on-LAN
│
├── nginx_manager/            # Nginx 控制層
├── static/                   # CSS、JS、圖示
├── templates/                # Jinja2 HTML 模板
│   ├── triage.html           # 模式選擇頁
│   ├── caddy_setup.html      # Caddy 設定精靈
│   ├── caddy_dashboard.html  # Caddy 儀表板
│   ├── tunnel_setup.html     # Cloudflare Tunnel 設定
│   ├── tunnel_dashboard.html # Tunnel 儀表板
│   ├── portal_login.html     # EZ-Portal 登入頁
│   └── portal_admin.html     # EZ-Portal 帳號管理
│
└── data/                     # SQLite 資料庫（持久化）
```

---

## 📖 使用說明

### 1. 選擇連線模式

首次開啟 `http://localhost:8181` 會進入模式選擇頁，根據你的情況選擇：

| 情況 | 建議模式 |
|------|----------|
| 沒有固定 IP / 不想動路由器 | Cloudflare Tunnel |
| 有固定 IP，想要最輕量設定 | Caddy（自動 HTTPS） |
| 有固定 IP，需要進階控制 | Nginx |

### 2. EZ-Portal — 快速保護任意服務

初始化管理員帳號（第一次）：

```bash
curl -X POST http://localhost:8181/api/portal/setup \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"你的密碼"}'
```

之後前往 `http://localhost:8181/portal/admin` 管理帳號，並為需要保護的服務開啟 EZ-Portal。

---

## 🐳 Docker Compose 說明

```yaml
services:
  ez-webbridge:
    build: .
    ports:
      - "80:80"       # Nginx / Caddy Proxy
      - "8181:8181"   # Web UI
    volumes:
      - ./data:/app/data   # 資料庫持久化
    environment:
      - TZ=Asia/Taipei
```

**Port 說明：**
- `8181` — EZ-WebBridge Web UI
- `80` — HTTP Proxy（Nginx / Caddy 反向代理）
- `443` — HTTPS（Caddy 模式下自動開啟）

---

## 🛠️ 常用指令

```bash
# 啟動
docker compose up -d

# 查看 Log
docker compose logs -f

# 停止
docker compose down

# 重新 Build（更新程式碼後）
docker compose up -d --build

# 進入容器除錯
docker exec -it <container_name> bash
```

---

## 📄 License

MIT License — 自由使用與修改。
