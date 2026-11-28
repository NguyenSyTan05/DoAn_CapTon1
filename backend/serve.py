"""Chạy Flask bằng Waitress (máy chủ WSGI đa luồng dùng được trên Windows).

    cd backend; python serve.py

Khác `python app.py`: không bật debug, 8 luồng xử lý đồng thời, ổn định khi chạy sau
Cloudflare Tunnel + Unified Gateway.
"""

import os

from waitress import serve

from app import app

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0" if os.getenv("ALLOW_LAN_ORIGINS") == "1" else "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    threads = int(os.getenv("FLASK_THREADS", "8"))
    serve(app, host=host, port=port, threads=threads)
