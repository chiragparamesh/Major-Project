import 'package:shared_preferences/shared_preferences.dart';

class ApiConfig {
  // No hard-coded server: the user enters the tunnel / LAN URL on first launch.
  static String _baseUrl = '';

  static String get baseUrl => _baseUrl;
  static bool get hasBaseUrl => _baseUrl.isNotEmpty;

  static Future<void> init() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString('server_url');
      if (saved != null && saved.trim().isNotEmpty) {
        _baseUrl = saved.trim();
        if (_baseUrl.endsWith('/')) {
          _baseUrl = _baseUrl.substring(0, _baseUrl.length - 1);
        }
      }
    } catch (e) {
      // SharedPreferences unavailable: the app will ask for the server URL again.
      _baseUrl = '';
    }
  }

  static Future<void> setBaseUrl(String url) async {
    var cleaned = url.trim();
    if (cleaned.endsWith('/')) {
      cleaned = cleaned.substring(0, cleaned.length - 1);
    }
    _baseUrl = cleaned;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('server_url', _baseUrl);
    } catch (_) {}
  }

  static Future<String> getDeviceId() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      var devId = prefs.getString('device_id');
      if (devId == null || devId.isEmpty) {
        devId = 'device-flutter-${DateTime.now().millisecondsSinceEpoch}';
        await prefs.setString('device_id', devId);
      }
      return devId;
    } catch (_) {
      return 'device-flutter-default';
    }
  }

  static String get registerStartUrl => '$baseUrl/api/register/start';
  static String get registerSendTelegramOtpUrl => '$baseUrl/api/register/send_telegram_otp';
  static String telegramStatusUrl(String userId) => '$baseUrl/api/telegram/status?user_id=${Uri.encodeQueryComponent(userId)}';
  static String get otpResendUrl => '$baseUrl/api/otp/resend';
  static String get authLoginUrl => '$baseUrl/api/login';
  static String get authLoginVerifyUrl => '$baseUrl/api/login/verify';
  static String get registerVerifyEmailUrl => '$baseUrl/api/register/verify_email';
  static String get registerVerifyTelegramUrl => '$baseUrl/api/register/verify_telegram';
  static String get logoutUrl => '$baseUrl/api/logout';
  static String get refreshUrl => '$baseUrl/api/refresh';
  static String get predictUrl => '$baseUrl/api/predict-secure';
  static String get transferUrl => '$baseUrl/api/transfer';
  static String balanceUrl(String userId) => '$baseUrl/api/balance/$userId';
  static String transactionsUrl(String userId) => '$baseUrl/api/transactions/$userId';
  static String get sendOtpUrl => '$baseUrl/api/otp/send';
  static String get verifyOtpUrl => '$baseUrl/api/otp/verify';
  static String get lookupPayeeUrl => '$baseUrl/api/lookup_payee';
  static String websiteCheckUrl(String domain) => '$baseUrl/api/website-check/$domain';
  static String get addTrustedPayeeUrl => '$baseUrl/api/trusted-payees/add';
  static String getTrustedPayeesUrl(String userId) => '$baseUrl/api/trusted-payees/$userId';
  static String deleteTrustedPayeeUrl(int id) => '$baseUrl/api/trusted-payees/$id';
  static String get reportScamUrl => '$baseUrl/api/report-scam';
  static String get feedbackUrl => '$baseUrl/api/feedback';
}
