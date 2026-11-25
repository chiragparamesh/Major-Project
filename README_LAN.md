# Run MLBFD for 4 laptops on the same network (free)

One laptop (the "server") runs MLBFD. The other 3 open it in a browser. No cloud, no cost.

## 1. On the server laptop (once)
1. Join the Wi-Fi/hotspot that all laptops will use.
2. Open **PowerShell as Administrator** and allow the port (Windows blocks incoming connections otherwise;
   a hotspot network is usually marked "Public", so this rule allows all profiles):
   ```
   New-NetFirewallRule -DisplayName "MLBFD 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Any
   ```
   (Remove later with: `Remove-NetFirewallRule -DisplayName "MLBFD 5000"`.)
3. Make sure `.env` has working Gmail (`python backend\otp_doctor.py --email-test` must PASS).

## 2. Every session
1. Double-click `start_mlbfd.bat` (or `python serve.py`). The banner prints:
   `SHARE ON SAME WI-FI: http://<server-ip>:5000/user/register`
2. Server laptop: use `http://localhost:5000` for users and `http://localhost:5000/admin` for the admin portal.
3. Other 3 laptops: open the printed `http://<server-ip>:5000/user/register` (same Wi-Fi). They cannot open `/admin`
   (admin is limited to the server laptop; this is intentional).
4. If the Wi-Fi gives the server a new IP next time, use the new address from the banner.

## 3. What each person needs
- Their own email address (receives the signup code) and a Telegram account on their phone
  (Start + Share Contact; the shared phone number must equal the number typed at signup).
- Signup limit: 3 accounts per laptop per day (anti-abuse rule). Payments only go to registered, ACTIVE users.

## 4. Troubleshooting
- Other laptops cannot connect: (a) firewall rule missing, (b) router/hotspot "client isolation" is on
  (college/guest Wi-Fi often blocks laptop-to-laptop; use a phone hotspot or a home router), (c) different Wi-Fi,
  (d) wrong IP (read the banner), (e) server not running.
  Quick test from another laptop: `http://<server-ip>:5000/user/login` must open the login page.
- Browser location is unavailable over plain http on a LAN; the app falls back to a default/manual location pin.
- Need HTTPS or access from other networks (free): `winget install --id Cloudflare.cloudflared`, then `start_mlbfd.bat`
  prints a public `https://....trycloudflare.com` link. Admin stays local-only unless `ADMIN_API_TOKEN` is used.
- After any `.env` change, stop and restart the server.

## Phones
Phones can use the Android app instead of a browser: see **README_PHONE_APP.md** (download the APK from the GitHub releases page, enter the laptop address, done).
