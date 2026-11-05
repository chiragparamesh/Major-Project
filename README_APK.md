# MLBFD Mobile Applications & APK Build Guide

This document describes the architecture, configuration, and build instructions for the **MLBFD Sender** and **MLBFD Receiver** Flutter mobile applications.

---

## 1. Environment & Prerequisites

Running `flutter doctor -v` provides the following diagnostics:
- **Flutter SDK**: `v3.41.6` (Channel stable, Dart `3.11.4`) located at `C:\src\flutter\flutter`
- **Android SDK**: `v34.0.0` located at `C:\Users\Chirag p\AppData\Local\Android\Sdk`
- **Windows Build Tools**: Visual Studio Build Tools 2026 installed

> [!WARNING]
> **Android SDK Path with Spaces**:
> The default SDK path `C:\Users\Chirag p\AppData\Local\Android\Sdk` contains a space in the username (`Chirag p`). Certain native Android Gradle/NDK toolchains may fail with spaces in paths.
>
> **Fix: a junction to the existing SDK** (no copy), from `cmd.exe`:
> ```
> mklink /J C:\AndroidSdk "C:\Users\Chirag p\AppData\Local\Android\Sdk"
> setx ANDROID_HOME C:\AndroidSdk
> flutter config --android-sdk C:\AndroidSdk
> ```
> Open a NEW terminal, then `flutter doctor -v` must show `Android SDK at C:\AndroidSdk`.
> Do not point ANDROID_HOME at a new empty folder (the old advice here did that).

> [!IMPORTANT]
> **JDK required.** `flutter build apk --release` (2026-10-31) failed with:
> `ERROR: JAVA_HOME is not set and no 'java' command could be found in your PATH.`
> No JDK or Android Studio JBR is installed on this machine. Install a free JDK 17 and set JAVA_HOME:
> ```
> winget install --id Microsoft.OpenJDK.17
> setx JAVA_HOME "C:\Program Files\Microsoft\jdk-17.0.13.11-hotspot"
> ```
> (use the folder winget actually created under `C:\Program Files\Microsoft\`), open a new terminal, then
> `cd flutter_app\sender_app && flutter build apk --release`.

---

## 2. Dynamic Server URL & Network Architecture

Because the MLBFD backend can be hosted locally (`http://<LAN_IP>:5000`) or exposed via Cloudflare Tunnel (`https://<subdomain>.trycloudflare.com`), the Flutter apps must not use a hardcoded IP.

### Server URL Configuration
1. On first launch both apps show **MLBFD Server**: enter the public link printed by
   `start_mlbfd.bat` (e.g. `https://abc-def.trycloudflare.com`) or `http://<laptop-LAN-IP>:5000`.
   The app checks `/api/register/timing_token` before saving. There is **no hard-coded
   fallback URL**; change it later with the server icon on the sign-in screen.
2. **Device Binding Header**:
   - Every network request automatically transmits the `X-Device-ID` header generated via UUID and stored in local device storage.
   - Known devices bypass OTP on login (30-day trust).

---

## 3. Dual-Channel Authentication Workflow

In accordance with MLBFD core security requirements:
1. **Registration**:
   - Step 1: User details, login PIN (6-digit), and separate payment PIN (6-digit).
   - Step 2: Email verification (6-digit code).
   - Step 3: Telegram bot link & contact verification (6-digit code).
2. **Step-Up Verification (REQUIRES_2FA)**:
   - When a transaction triggers fraud risk (score 60–79.99), the app prompts for **Dual OTPs** (Email code AND Telegram code).
   - Transfers execute atomically only upon entering both correct codes.

---

## 4. Building Release APKs

To compile release APKs from the terminal:

### MLBFD Sender App
```cmd
cd "D:\Major Project\MLBFD\flutter_app\sender_app"
flutter pub get
flutter build apk --release
```
*Output Artifact*: `build/app/outputs/flutter-apk/app-release.apk`

### MLBFD Receiver App
```cmd
cd "D:\Major Project\MLBFD\flutter_app\receiver_app"
flutter pub get
flutter build apk --release
```
*Output Artifact*: `build/app/outputs/flutter-apk/app-release.apk`

---

## 5. Installing on Physical Devices

1. Connect your Android phone via USB and enable **USB Debugging** in Developer Options.
2. Directly install from terminal:
   ```cmd
   flutter install
   ```
3. *Alternative*: Transfer `app-release.apk` to phone storage and tap to install (enable "Install unknown apps" permission).

---

## OTP flow in the apps (2026-10-31)
- **Sign up** (3 steps, same API as the web): details (6-digit login PIN and a different 6-digit
  payment PIN) -> email code -> Telegram: copy the shown `https://t.me/mlbfd_otp_bot?start=...`
  link, press **Start**, tap **Share Registered Contact**; the app polls `/api/telegram/status`
  and sends the Telegram code only after the link succeeds.
- **New-device login** and **REQUIRES_2FA payments** ask for BOTH codes (email and Telegram).
- Every OTP screen shows per-channel delivery (`sent` / `failed` / `not linked` / `sending...`)
  with a **Resend** button per channel (30 s cooldown).
- Cloudflare Turnstile cannot run inside the app: keep `TURNSTILE_SECRET_KEY` empty for app
  signups (honeypot + 3 s timing token still apply), or sign up on the web.
- Optional request signing: `flutter build apk --release --dart-define=MLBFD_CLIENT_SECRET=<value from .env>`.
  The APK never embeds the server's `MLBFD_SECRET_KEY`.

