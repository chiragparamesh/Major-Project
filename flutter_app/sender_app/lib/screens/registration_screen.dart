import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../config/api_config.dart';
import '../services/api_service.dart';
import '../widgets/otp_delivery_status.dart';
import 'home_screen.dart';

/// Login (trusted device / new-device dual OTP) and the 3-step signup:
/// details -> email code -> Telegram link (Start + Share Contact) -> Telegram code.
class RegistrationScreen extends StatefulWidget {
  final VoidCallback? onChangeServer;
  const RegistrationScreen({super.key, this.onChangeServer});

  @override
  State<RegistrationScreen> createState() => _RegistrationScreenState();
}

enum _Stage { login, loginOtp, details, emailCode, telegram }

class _RegistrationScreenState extends State<RegistrationScreen> {
  final _api = ApiService();
  _Stage _stage = _Stage.login;
  bool _busy = false;
  String? _error;

  // login
  final _loginId = TextEditingController();
  final _loginPin = TextEditingController();
  // signup details
  final _fullName = TextEditingController();
  final _userId = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _loginPinNew = TextEditingController();
  final _paymentPinNew = TextEditingController();
  final _secQuestion = TextEditingController(text: 'What city were you born in?');
  final _secAnswer = TextEditingController();
  bool _consent = false;
  // codes
  final _emailCode = TextEditingController();
  final _telegramCode = TextEditingController();

  String _pendingUserId = '';
  String _telegramLink = '';
  String _tgStatus = 'Waiting for Start + Share Contact…';
  bool _tgCodeSent = false;
  Map<String, dynamic> _delivery = {};
  String? _timingToken;
  Timer? _poll;
  double? _lat;
  double? _lon;

  @override
  void initState() {
    super.initState();
    _checkStoredSession();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _checkStoredSession() async {
    final prefs = await SharedPreferences.getInstance();
    final user = prefs.getString('logged_in_user');
    final token = await _api.getAccessToken();
    if (user != null && token != null && mounted) {
      _goHome(user);
    }
  }

  Future<void> _goHome(String userId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('logged_in_user', userId);
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => HomeScreen(userId: userId)));
  }

  void _fail(Map<String, dynamic> res, String fallback) {
    setState(() => _error = 'HTTP ${res['http_status'] ?? '?'}: ${res['message'] ?? fallback}');
  }

  Future<void> _run(Future<void> Function() body) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await body();
    } catch (e) {
      setState(() => _error = 'Connection failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ---------------- login ----------------
  Future<void> _login() => _run(() async {
        final id = _loginId.text.trim();
        final res = await _api.login(id, _loginPin.text.trim());
        if (res['status'] == 'LOGGED_IN') {
          await _goHome(res['user_id'] ?? id);
        } else if (res['status'] == 'OTP_REQUIRED') {
          setState(() {
            _pendingUserId = (res['user_id'] ?? id).toString();
            _delivery = Map<String, dynamic>.from(res['delivery'] ?? {});
            _stage = _Stage.loginOtp;
          });
        } else {
          _fail(res, 'Login failed');
        }
      });

  Future<void> _loginVerify() => _run(() async {
        final res = await _api.loginVerify(_pendingUserId, _emailCode.text.trim(), _telegramCode.text.trim());
        if (res['access_token'] != null) {
          await _goHome(_pendingUserId);
        } else {
          _fail(res, 'Invalid codes');
        }
      });

  // ---------------- signup ----------------
  Future<void> _openSignup() async {
    setState(() {
      _stage = _Stage.details;
      _error = null;
    });
    try {
      final r = await http.get(Uri.parse('${ApiConfig.baseUrl}/api/register/timing_token'));
      _timingToken = (jsonDecode(r.body) as Map)['timing_token'] as String?;
    } catch (_) {
      _timingToken = null;
    }
    try {
      var p = await Geolocator.checkPermission();
      if (p == LocationPermission.denied) p = await Geolocator.requestPermission();
      if (p == LocationPermission.always || p == LocationPermission.whileInUse) {
        final pos = await Geolocator.getCurrentPosition();
        _lat = pos.latitude;
        _lon = pos.longitude;
      }
    } catch (_) {
      // Home location is optional; geofencing is skipped without it.
    }
  }

  String? _pinError(String pin, String name) {
    if (!RegExp(r'^\d{6}$').hasMatch(pin)) return '$name must be exactly 6 digits';
    return null;
  }

  Future<void> _registerStart() => _run(() async {
        final lp = _loginPinNew.text.trim();
        final pp = _paymentPinNew.text.trim();
        final err = _pinError(lp, 'Login PIN') ?? _pinError(pp, 'Payment PIN') ??
            (lp == pp ? 'Login PIN and Payment PIN must differ' : null) ??
            (_consent ? null : 'Please accept the privacy consent');
        if (err != null) {
          setState(() => _error = err);
          return;
        }
        final id = _userId.text.trim();
        final res = await _api.registerStart({
          'full_name': _fullName.text.trim(),
          'user_id': id,
          'phone': _phone.text.trim(),
          'email': _email.text.trim(),
          'login_pin': lp,
          'payment_pin': pp,
          'security_question': _secQuestion.text.trim(),
          'security_answer': _secAnswer.text.trim(),
          'consent': true,
          'website': '', // honeypot
          if (_timingToken != null) 'form_timing_token': _timingToken,
          if (_lat != null) 'home_latitude': _lat,
          if (_lon != null) 'home_longitude': _lon,
        });
        if (res['success'] == true) {
          setState(() {
            _pendingUserId = (res['user_id'] ?? id).toString();
            _telegramLink = (res['telegram_link'] ?? '').toString();
            _delivery = {'email': (res['delivery']?['email'] ?? 'sent').toString()};
            _stage = _Stage.emailCode;
          });
        } else {
          _fail(res, 'Registration failed');
        }
      });

  Future<void> _verifyEmail() => _run(() async {
        final res = await _api.verifyEmail(_pendingUserId, _emailCode.text.trim());
        if (res['success'] == true) {
          setState(() {
            _stage = _Stage.telegram;
            _delivery = {};
          });
          _startTelegramPoll();
        } else {
          _fail(res, 'Invalid email code');
        }
      });

  void _startTelegramPoll() {
    _poll?.cancel();
    final started = DateTime.now();
    _poll = Timer.periodic(const Duration(seconds: 3), (t) async {
      if (DateTime.now().difference(started).inMinutes >= 10) {
        t.cancel();
        if (mounted) setState(() => _tgStatus = 'Still not linked. Open the link again, press Start, then Share Contact.');
        return;
      }
      try {
        final st = await _api.telegramStatus(_pendingUserId);
        if (!mounted) return;
        if (st['telegram_verified'] == true) {
          t.cancel();
          setState(() => _tgStatus = 'Telegram linked and contact verified.');
          if (!_tgCodeSent) await _sendTelegramCode();
        } else if (st['telegram_linked'] == true) {
          setState(() => _tgStatus = 'Start received. Now tap "Share Registered Contact" in Telegram.');
        }
      } catch (_) {
        // keep polling
      }
    });
  }

  Future<void> _sendTelegramCode() => _run(() async {
        final res = await _api.sendTelegramOtp(_pendingUserId);
        setState(() => _delivery = Map<String, dynamic>.from(res['delivery'] ?? {}));
        if (res['success'] == true) {
          _tgCodeSent = true;
        } else {
          _fail(res, 'Telegram code not sent');
        }
      });

  Future<void> _verifyTelegram() => _run(() async {
        final res = await _api.verifyTelegram(_pendingUserId, _telegramCode.text.trim());
        if (res['status'] == 'ACTIVE' && res['access_token'] != null) {
          await _goHome(_pendingUserId);
        } else if (res['success'] == true) {
          setState(() => _error = 'Telegram verified; email code still required.');
        } else {
          _fail(res, 'Invalid Telegram code');
        }
      });

  // ---------------- UI ----------------
  Widget _field(TextEditingController c, String label,
      {bool obscure = false, TextInputType? type, int? maxLength, IconData? icon}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: TextField(
        controller: c,
        obscureText: obscure,
        keyboardType: type,
        maxLength: maxLength,
        inputFormatters: type == TextInputType.number ? [FilteringTextInputFormatter.digitsOnly] : null,
        decoration: InputDecoration(labelText: label, counterText: '', prefixIcon: icon != null ? Icon(icon) : null),
      ),
    );
  }

  Widget _primary(String text, VoidCallback onPressed) => Padding(
        padding: const EdgeInsets.only(top: 12),
        child: ElevatedButton(onPressed: _busy ? null : onPressed, child: Text(_busy ? 'Please wait…' : text)),
      );

  List<Widget> _loginView() => [
        _field(_loginId, 'User ID, UPI ID or phone', icon: Icons.person),
        _field(_loginPin, 'Login PIN (6 digits)', obscure: true, type: TextInputType.number, maxLength: 6, icon: Icons.lock),
        _primary('Sign in', _login),
        TextButton(onPressed: _busy ? null : _openSignup, child: const Text('New here? Create an account')),
      ];

  List<Widget> _loginOtpView() => [
        const Text('New device: enter the codes sent to your email and Telegram.'),
        const SizedBox(height: 8),
        OtpDeliveryStatus(delivery: _delivery, purpose: 'LOGIN_NEW_DEVICE', userId: _pendingUserId),
        _field(_emailCode, 'Email code', type: TextInputType.number, maxLength: 6, icon: Icons.email_outlined),
        _field(_telegramCode, 'Telegram code', type: TextInputType.number, maxLength: 6, icon: Icons.telegram),
        _primary('Verify and sign in', _loginVerify),
      ];

  List<Widget> _detailsView() => [
        _field(_fullName, 'Full name', icon: Icons.badge),
        _field(_userId, 'User ID (letters, digits, _)', icon: Icons.person),
        _field(_phone, 'Phone (+91XXXXXXXXXX)', type: TextInputType.phone, icon: Icons.phone),
        _field(_email, 'Email', type: TextInputType.emailAddress, icon: Icons.email),
        _field(_loginPinNew, 'Login PIN (6 digits)', obscure: true, type: TextInputType.number, maxLength: 6, icon: Icons.lock),
        _field(_paymentPinNew, 'Payment PIN (6 digits, different)', obscure: true, type: TextInputType.number, maxLength: 6, icon: Icons.key),
        _field(_secQuestion, 'Security question', icon: Icons.help_outline),
        _field(_secAnswer, 'Security answer', icon: Icons.question_answer),
        CheckboxListTile(
          value: _consent,
          onChanged: (v) => setState(() => _consent = v ?? false),
          title: const Text('I consent to MLBFD storing my encrypted phone/email for fraud detection.'),
          controlAffinity: ListTileControlAffinity.leading,
        ),
        _primary('Continue: send email code', _registerStart),
        TextButton(onPressed: _busy ? null : () => setState(() => _stage = _Stage.login), child: const Text('Back to sign in')),
      ];

  List<Widget> _emailView() => [
        Text('Step 2 of 3: we sent a 6-digit code to ${_email.text.trim()}.'),
        const SizedBox(height: 8),
        OtpDeliveryStatus(delivery: _delivery, purpose: 'SIGNUP', userId: _pendingUserId),
        _field(_emailCode, 'Email code', type: TextInputType.number, maxLength: 6, icon: Icons.email_outlined),
        _primary('Verify email', _verifyEmail),
      ];

  List<Widget> _telegramView() => [
        const Text('Step 3 of 3: link the MLBFD Telegram bot.'),
        const SizedBox(height: 8),
        const Text('1. Open this link in Telegram (tap Copy, paste in your browser or Telegram):\n'
            '2. Press START.\n'
            '3. Tap "Share Registered Contact" (the phone number you registered).\n'
            '4. This screen detects the link and sends your Telegram code.'),
        const SizedBox(height: 8),
        SelectableText(_telegramLink.isEmpty ? '(link unavailable)' : _telegramLink,
            style: const TextStyle(fontWeight: FontWeight.bold)),
        TextButton.icon(
          onPressed: _telegramLink.isEmpty ? null : () => Clipboard.setData(ClipboardData(text: _telegramLink)),
          icon: const Icon(Icons.copy),
          label: const Text('Copy link'),
        ),
        Text(_tgStatus),
        const SizedBox(height: 8),
        if (_delivery.isNotEmpty) OtpDeliveryStatus(delivery: _delivery, purpose: 'SIGNUP', userId: _pendingUserId),
        _field(_telegramCode, 'Telegram code', type: TextInputType.number, maxLength: 6, icon: Icons.telegram),
        _primary('Activate account', _verifyTelegram),
      ];

  @override
  Widget build(BuildContext context) {
    final body = switch (_stage) {
      _Stage.login => _loginView(),
      _Stage.loginOtp => _loginOtpView(),
      _Stage.details => _detailsView(),
      _Stage.emailCode => _emailView(),
      _Stage.telegram => _telegramView(),
    };
    return Scaffold(
      appBar: AppBar(
        title: Text(_stage == _Stage.login || _stage == _Stage.loginOtp ? 'MLBFD Sign in' : 'MLBFD Sign up'),
        actions: [
          if (widget.onChangeServer != null)
            IconButton(icon: const Icon(Icons.dns), tooltip: 'Server URL', onPressed: widget.onChangeServer),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            if (_error != null)
              Container(
                padding: const EdgeInsets.all(10),
                margin: const EdgeInsets.only(bottom: 8),
                color: Colors.red.withValues(alpha: 0.15),
                child: Text(_error!, style: const TextStyle(color: Colors.redAccent)),
              ),
            ...body,
          ],
        ),
      ),
    );
  }
}
