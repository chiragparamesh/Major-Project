# MLBFD Self-Hosting & Cloudflare Tunnel Guide

This guide explains how to host the MLBFD (Machine Learning Based Fraud Detection) server on your Windows laptop using Waitress WSGI and expose it securely to the internet via Cloudflare Tunnel (zero public port forwarding, end-to-end HTTPS).

---

## 1. Prerequisites

1. **Python 3.11 Virtual Environment**:
   - Located at `backend/.venv` (already configured with all dependencies including Waitress, Flask, and ML models).
2. **Cloudflare Tunnel (`cloudflared`)**:
   - Fast installation via Windows Package Manager:
     ```cmd
     winget install --id Cloudflare.cloudflared
     ```
   - *Alternative*: Download `cloudflared-windows-amd64.exe` directly from [Cloudflare Releases](https://github.com/cloudflare/cloudflared/releases), rename to `cloudflared.exe`, and place it in your Windows `PATH` (e.g., `C:\Windows\System32` or your user folder).

---

## 2. Quick Start (One-Click)

Run the batch launcher located in the repository root:

```cmd
start_mlbfd.bat
```

### What this script does:
1. Detects `backend\.venv\Scripts\python.exe`.
2. Checks if `cloudflared` is installed:
   - If present, opens a dedicated Cloudflare Tunnel console window exposing `http://localhost:5000` to a free temporary `https://*.trycloudflare.com` URL.
   - If missing, displays instructions to install via `winget`.
3. Validates security keys and enforces SQLite WAL mode.
4. Starts the multi-threaded Waitress WSGI server (8 worker threads) listening on `0.0.0.0:5000`.

---

## 3. Server Endpoints

Once started, the following interfaces are available:

| Interface | URL | Description |
| :--- | :--- | :--- |
| **User Dashboard** | `http://localhost:5000/` | End-user transfer portal & balance monitor |
| **User Login** | `http://localhost:5000/user/login` | Dual-PIN user login with rate-limiting |
| **User Registration** | `http://localhost:5000/user/register` | 3-step registration wizard with dual OTP |
| **Admin Dashboard** | `http://localhost:5000/admin` | System statistics, transactions list, ML metrics |
| **Fraud Alerts Queue** | `http://localhost:5000/admin/alerts` | Flagged transactions with interactive SHAP bar chart |
| **REST API Base** | `http://localhost:5000/api` | Secure payment and risk assessment endpoints |

---

## 4. Connecting to Cloudflare Tunnel

When `cloudflared` starts, inspect the Cloudflare Tunnel console window for a line similar to:

```text
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
|  https://random-subdomain.trycloudflare.com                                                |
+--------------------------------------------------------------------------------------------+
```

You can share this HTTPS link or configure Flutter mobile apps to point to `https://random-subdomain.trycloudflare.com/api`.

### Cloudflare Turnstile Configuration
If using Cloudflare Turnstile bot protection for public registration:
1. Go to Cloudflare Dashboard -> **Turnstile**.
2. Add your `*.trycloudflare.com` domain to the allowed hostnames list.
3. Update `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` in `.env`.

---

## 5. Laptop Power & Sleep Optimization

To prevent your laptop from dropping network connections or sleeping while hosting:

1. **When plugged in**:
   - Open **Settings** -> **System** -> **Power & battery**.
   - Under **Screen and sleep**, set *When plugged in, put my device to sleep after*: **Never**.
2. **Closing the laptop lid**:
   - Press `Win + R`, run `control powercfg.cpl`.
   - Click **Choose what closing the lid does** on the left menu.
   - Under **When plugged in**, change **When I close the lid** to: **Do nothing**.
3. **Network adapter stability**:
   - Ensure "Allow the computer to turn off this device to save power" is unchecked in Device Manager under Wi-Fi/Ethernet properties.

---

## 6. Architecture & Concurrency Notes

- **WSGI Server**: Waitress WSGI running 8 concurrent worker threads.
- **Database Engine**: SQLite with Write-Ahead Logging (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`) enabling safe concurrent reads and non-blocking transactional writes.
- **Rate Limiting**: In-memory IP and endpoint rate limiters protecting against denial of service, credential stuffing, and replay attacks.

