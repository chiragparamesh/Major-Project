import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../config/api_config.dart';

class ApiService {
  final _storage = const FlutterSecureStorage();

  Future<String?> getAccessToken() async {
    return await _storage.read(key: 'access_token');
  }

  Future<String?> getRefreshToken() async {
    return await _storage.read(key: 'refresh_token');
  }

  Future<void> saveTokens(String access, String refresh) async {
    await _storage.write(key: 'access_token', value: access);
    await _storage.write(key: 'refresh_token', value: refresh);
  }

  Future<void> clearTokens() async {
    await _storage.delete(key: 'access_token');
    await _storage.delete(key: 'refresh_token');
  }

  Future<http.Response> getSecure(String url) async {
    final headers = {
      'Content-Type': 'application/json',
      'X-Device-ID': await ApiConfig.getDeviceId(),
    };
    
    final token = await getAccessToken();
    if (token != null) {
      headers['Authorization'] = 'Bearer $token';
    }
    
    try {
      var response = await http.get(Uri.parse(url), headers: headers);
      if (response.statusCode == 401) {
        final refreshed = await refreshToken();
        if (refreshed) {
          final newToken = await getAccessToken();
          headers['Authorization'] = 'Bearer $newToken';
          response = await http.get(Uri.parse(url), headers: headers);
        }
      }
      return response;
    } catch (e) {
      throw SocketException("Network error on GET: $e");
    }
  }

  Future<bool> refreshToken() async {
    final refresh = await getRefreshToken();
    if (refresh == null) return false;
    
    final headers = {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $refresh',
    };
    
    try {
      final response = await http.post(
        Uri.parse(ApiConfig.refreshUrl),
        headers: headers,
      );
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['success'] == true) {
          await _storage.write(key: 'access_token', value: data['access_token']);
          return true;
        }
      }
    } catch (_) {}
    return false;
  }

  Future<Map<String, String>> _jsonHeaders() async => {
        'Content-Type': 'application/json',
        'X-Device-ID': await ApiConfig.getDeviceId(),
      };

  Map<String, dynamic> _decode(http.Response r) {
    try {
      final d = jsonDecode(r.body);
      if (d is Map<String, dynamic>) {
        d['http_status'] = r.statusCode;
        return d;
      }
    } catch (_) {}
    return {'success': false, 'http_status': r.statusCode, 'message': 'HTTP ${r.statusCode}: unexpected server reply'};
  }

  Future<Map<String, dynamic>> _post(String url, Map<String, dynamic> body, {bool auth = false}) async {
    final headers = await _jsonHeaders();
    if (auth) {
      final t = await getAccessToken();
      if (t != null) headers['Authorization'] = 'Bearer $t';
    }
    final r = await http.post(Uri.parse(url), headers: headers, body: jsonEncode(body))
        .timeout(const Duration(seconds: 30));
    return _decode(r);
  }

  // ---- Signup (dual verification: email first, Telegram after linking) ----
  Future<Map<String, dynamic>> registerStart(Map<String, dynamic> details) =>
      _post(ApiConfig.registerStartUrl, details);

  Future<Map<String, dynamic>> verifyEmail(String userId, String code) =>
      _post(ApiConfig.registerVerifyEmailUrl, {'user_id': userId, 'code': code});

  Future<Map<String, dynamic>> telegramStatus(String userId) async {
    final r = await http.get(Uri.parse(ApiConfig.telegramStatusUrl(userId))).timeout(const Duration(seconds: 15));
    return _decode(r);
  }

  Future<Map<String, dynamic>> sendTelegramOtp(String userId) =>
      _post(ApiConfig.registerSendTelegramOtpUrl, {'user_id': userId});

  Future<Map<String, dynamic>> verifyTelegram(String userId, String code) async {
    final d = await _post(ApiConfig.registerVerifyTelegramUrl, {'user_id': userId, 'code': code});
    if (d['access_token'] is String && d['refresh_token'] is String) {
      await saveTokens(d['access_token'], d['refresh_token']);
    }
    return d;
  }

  // ---- Login (trusted device -> tokens; new device -> OTP_REQUIRED + dual codes) ----
  Future<Map<String, dynamic>> login(String userId, String loginPin) async {
    final d = await _post(ApiConfig.authLoginUrl, {
      'user_id': userId,
      'login_pin': loginPin,
      'device_id': await ApiConfig.getDeviceId(),
    });
    if (d['access_token'] is String && d['refresh_token'] is String) {
      await saveTokens(d['access_token'], d['refresh_token']);
    }
    return d;
  }

  Future<Map<String, dynamic>> loginVerify(String userId, String emailCode, String telegramCode) async {
    final d = await _post(ApiConfig.authLoginVerifyUrl, {
      'user_id': userId,
      'device_id': await ApiConfig.getDeviceId(),
      'email_code': emailCode,
      'telegram_code': telegramCode,
    });
    if (d['access_token'] is String && d['refresh_token'] is String) {
      await saveTokens(d['access_token'], d['refresh_token']);
    }
    return d;
  }

  // ---- Per-channel resend (30 s cooldown enforced by the server) ----
  Future<Map<String, dynamic>> resendOtp({
    required String purpose,
    required String channel,
    String? userId,
    String? txnId,
  }) =>
      _post(ApiConfig.otpResendUrl, {
        'purpose': purpose,
        'channel': channel,
        if (userId != null) 'user_id': userId,
        if (txnId != null) 'txn_id': txnId,
      }, auth: true);

  Future<double> getBalance(String userId) async {
    final response = await getSecure(ApiConfig.balanceUrl(userId));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return double.parse(data['balance'].toString());
    }
    throw Exception("Failed to fetch balance");
  }

  Future<List<dynamic>> getTransactions(String userId) async {
    final response = await getSecure(ApiConfig.transactionsUrl(userId));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['transactions'];
    }
    throw Exception("Failed to fetch transactions");
  }
}
