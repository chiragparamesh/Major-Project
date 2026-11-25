# MLBFD Phone App (Android APK)

The app is a thin shell around the MLBFD server running on your laptop. It asks for the laptop's address once,
then opens the full MLBFD web app (sign up, login, send money, PIN reset, history ...). Because every screen lives
on the server, a server fix reaches every phone immediately; you do not need to reinstall the app.

## 1. Get the APK
GitHub: https://github.com/chiragparamesh/Major-Project/releases (download `mlbfd-app.apk` from the newest release).

Install on the phone: open the file, allow "Install unknown apps" for your browser/file manager when Android asks,
tap Install. (It is signed with a standard debug key, so Play Protect may show a warning; choose "Install anyway".)

## 2. One-time setup on the server laptop
1. Windows Firewall must allow port 5000 (administrator PowerShell, once):
   `New-NetFirewallRule -DisplayName "MLBFD 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Any`
2. `.env` must have working email (Gmail app password) and the Telegram bot token. Check with
   `backend\.venv\Scripts\python backend\otp_doctor.py --email-test`.
3. Keep the laptop awake and plugged in: `powercfg /change standby-timeout-ac 0` and `powercfg /change standby-timeout-dc 0`.

## 3. Every session
1. Turn on the hotspot on the host phone and connect the laptop and every other phone to it.
   **Keep mobile data ON on the hotspot phone**: the laptop needs internet to send email and Telegram codes, and
   the app's icons, fonts and map load from the internet.
2. On the laptop start `start_mlbfd.bat`. In the black window find the line
   `SHARE ON SAME WI-FI:  http://<laptop-ip>:5000/user/register`.
   **The laptop's address can change every time the hotspot restarts**, so read it again each session.
3. On each phone open the MLBFD app. First time: type the address (`10.x.x.x:5000`), tap Connect. The app tests the
   connection and remembers it. If the address changed later: Back button, then "Change server address".
4. Sign up: email code, then press the Telegram link (opens Telegram), Start, Share Contact, enter the Telegram code.
5. The admin portal stays on the laptop only: `http://localhost:5000/admin`.

## 4. What each user needs
- Their own email address and Telegram account (the shared contact must match the phone number used at signup).
- At least two registered accounts to try payments; payments only go to registered, active users.
- A limit of 3 signups per device per day.

## 5. Troubleshooting
| Symptom | Fix |
|---|---|
| "Cannot reach the MLBFD server" | same hotspot? server running? use the newest address from the server window; firewall rule present |
| Works on laptop, not on phone | hotspot "client isolation"/AP isolation on, or the phone is on mobile data instead of the hotspot Wi-Fi |
| Codes never arrive | `otp_doctor.py --email-test`; user must press Start in the bot first; restart the server after changing `.env` |
| Icons or map missing | hotspot phone has no mobile data |
| Telegram link does nothing | install Telegram, or copy the link into the Telegram app |
| Page looks stale after a server update | back button, "Reload page" |

## 6. Build it yourself
```
cd flutter_app\mlbfd_app
flutter build apk --release
```
Output: `build\app\outputs\flutter-apk\app-release.apk`. Needs JDK 17 and the Android SDK (see README_APK.md for the
SDK-path-with-spaces junction). The manifest allows plain `http` (required for a laptop on a hotspot) and the
INTERNET permission.

### Build problems seen on this laptop (and the fixes)
| Error | Cause and fix |
|---|---|
| `JAVA_HOME is not set` | install JDK 17 and set `JAVA_HOME` |
| `java.io.IOException: Unable to establish loopback connection` | the Windows user folder has a space (`C:\Users\Chirag p`), which breaks Java's internal pipe. Build with a plain temp folder (create it first): `$env:TEMP="D:\mlbfd_build_tmp"; $env:TMP=$env:TEMP; $env:JAVA_TOOL_OPTIONS="-Djdk.net.unixdomain.tmpdir=D:\mlbfd_build_tmp"` |
| `sdkmanager did not install NDK 28.2.13676358` | install it once: `sdkmanager --sdk_root=<sdk> "ndk;28.2.13676358"` (about 2 GB) |
| build very slow / out of memory | close other programs; `android/gradle.properties` caps Gradle at 1.5 GB |

The older native Flutter apps (`flutter_app/sender_app`, `flutter_app/receiver_app`) remain in the repo but have
not been run on a device; this web-shell app is the supported phone app.
