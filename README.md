# Nginx Proxy Manager (Nordic Edition)

A minimalist, high-performance Nginx manager built with Flask and Python, featuring a modern Nordic UI and seamless Cloudflare DNS integration.

## Features

-   **Visual Management**: Manage Nginx proxy hosts via a clean, responsive web interface.
-   **Cloudflare Integration**: Automatically syncs DNS records (A/CNAME) with Cloudflare when you add domains.
-   **Docker Ready**: Zero-dependency deployment using Docker Compose.
-   **Auto-Configuration**: Generates optimized Nginx configurations with WebSocket support and path rewriting.
-   **Nordic UI**: Designed with a focus on simplicity, aesthetics, and usability.

## Prerequisites

-   **Docker** and **Docker Compose** installed on your machine.
-   A **Cloudflare** account (for API Token and Zone ID).

## Quick Start (Docker)

1.  **Clone the repository**:
    ```bash
    https://github.com/wenson0106/EZ-WebBridge.git
    cd EZ-WebBridge
    ```

2.  **Start the service**:
    ```bash
    docker-compose up -d --build
    ```

3.  **Access the Dashboard**:
    Open your browser and navigate to `http://localhost:8181`.

4.  **Initial Setup**:
    -   Enter your **Domain Name**.
    -   Enter your **Public IP**.
    -   Enter your **Cloudflare API Token** and **Zone ID**.

## Directory Structure

```
├── app.py                  # Main Flask application
├── config.py               # Application configuration
├── data/                   # SQLite database (persisted)
├── generated_configs/      # Nginx configuration files (persisted)
├── nginx_manager/          # Core logic (Nginx control, Cloudflare sync)
├── static/                 # CSS, JS, and Icons
├── templates/              # HTML templates
├── Dockerfile              # Docker image definition
└── docker-compose.yml      # Docker orchestration
```

## Configuration

-   **Port**: The web interface runs on port `8181` by default. You can change this in `docker-compose.yml`.
-   **Database**: Data is stored in `data/data.db`.
-   **Nginx Configs**: Generated configs are stored in `generated_configs/`.

## Manual Installation (Without Docker)

If you prefer to run it directly on Python:

1.  Install Python 3.9+.
2.  Install dependencies: `pip install -r requirements.txt`.
3.  Install Nginx (ensure it's in your PATH on Linux, or auto-installed by the app on Windows).
4.  Run the app: `python app.py`.
5.  Access at `http://localhost:8181`.

## License

MIT License. Free to use and modify.
