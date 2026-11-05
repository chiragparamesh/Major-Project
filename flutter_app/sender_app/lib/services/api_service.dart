import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:crypto/crypto.dart';
import '../config/api_config.dart';

class ApiService {
  final _storage = const FlutterSecureStorage();
  // Never embed a server secret in the APK; pass --dart-define=MLBFD_CLIENT_SECRET=... to sign requests.
  static const String _sharedSecret = String.fromEnvironment(
    'MLBFD_CLIENT_SECRET',
    defaultValue: '',
  );

  // Auth helper: get stored access token
  Future<String?> getAccessToken() async {
    return await _storage.read(key: 'access_token');
  }

  // Auth helper: get stored refresh token
  Future<String?> getRefreshToken() async {
    return await _storage.read(key: 'refresh_token');
  }

  // Auth helper: save tokens
  Future<void> saveTokens(String access, String refresh) async {
    await _storage.write(key: 'access_token', value: access);
    await _storage.write(key: 'refresh_token', value: refresh);
  }

  // Auth helper: clear tokens
  Future<void> clearTokens() async {
    await _storage.delete(key: 'access_token');
    await _storage.delete(key: 'refresh_token');
  }

  // Compute HMAC signature for payload
  Map<String, String> _getSecurityHeaders(String bodyData) {
    if (_sharedSecret.isEmpty) {
      // Signing is optional on the server (JWT is the authentication); send no signature.
      return {'Content-Type': 'application/json'};
    }
    final timestamp = (DateTime.now().millisecondsSinceEpoch ~/ 1000).toString();
    final message = bodyData + timestamp;
    final keyBytes = utf8.encode(_sharedSecret);
    final messageBytes = utf8.encode(message);
    
    final hmac = Hmac(sha256, keyBytes);
    final signature = hmac.convert(messageBytes).toString();
    
    return {
      'X-Signature': signature,
      'X-Timestamp': timestamp,
      'Content-Type': 'application/json',
    };
  }

  // Wrapper for HTTP POST with authentication and HMAC
  Future<http.Response> postSecure(String url, Map<String, dynamic> body) async {
    final bodyStr = jsonEncode(body);
    final headers = _getSecurityHeaders(bodyStr);
    
    // Attach Device ID header
    headers['X-Device-ID'] = await ApiConfig.getDeviceId();

    // Add Bearer Auth if token is available
    final token = await getAccessToken();
    if (token != null) {
      headers['Authorization'] = 'Bearer $token';
    }
    
    try {
      var response = await http.post(
        Uri.parse(url),
        headers: headers,
        body: bodyStr,
      );
      
      // Auto-refresh token if 401 and we have a refresh token
      if (response.statusCode == 401 && !url.contains('/refresh')) {
        final refreshed = await refreshToken();
        if (refreshed) {
          final newToken = await getAccessToken();
          headers['Authorization'] = 'Bearer $newToken';
          response = await http.post(
            Uri.parse(url),
            headers: headers,
            body: bodyStr,
          );
        }
      }
      return response;
    } catch (e) {
      throw SocketException("Network error on POST secure: $e");
    }
  }

  // Wrapper for HTTP GET with authentication
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
      var response = await http.get(
        Uri.parse(url),
        headers: headers,
      );
      
      // Auto-refresh token if 401
      if (response.statusCode == 401) {
        final refreshed = await refreshToken();
        if (refreshed) {
          final newToken = await getAccessToken();
          headers['Authorization'] = 'Bearer $newToken';
          response = await http.get(
            Uri.parse(url),
            headers: headers,
          );
        }
      }
      return response;
    } catch (e) {
      throw SocketException("Network error on GET secure: $e");
    }
  }

  // Invalidate and refresh token
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

  // API Call: Invalidate token
  Future<void> logout() async {
    try {
      await postSecure(ApiConfig.logoutUrl, {});
    } catch (_) {}
    await clearTokens();
  }

  // API Call: Get User balance
  Future<double> getBalance(String userId) async {
    final response = await getSecure(ApiConfig.balanceUrl(userId));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return double.parse(data['balance'].toString());
    }
    throw Exception("Failed to fetch balance");
  }

  // API Call: Fetch User transaction history
  Future<List<dynamic>> getTransactions(String userId) async {
    final response = await getSecure(ApiConfig.transactionsUrl(userId));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['transactions'];
    }
    throw Exception("Failed to fetch transactions");
  }

  // API Call: Pre-transfer check (What-If preview)
  Future<Map<String, dynamic>> checkRiskScore({
    required String senderUpi,
    required String receiverUpi,
    required double amount,
    required String deviceId,
    required double lat,
    required double lon,
    bool biometricFailed = false,
    String qrCode = '',
    String mccCode = '0000',
  }) async {
    final payload = {
      'sender_upi': senderUpi,
      'receiver_upi': receiverUpi,
      'amount': amount,
      'device_id': deviceId,
      'latitude': lat,
      'longitude': lon,
      'biometric_failed': biometricFailed,
      'qr_code': qrCode,
      'mcc_code': mccCode,
    };
    
    final response = await postSecure(ApiConfig.predictUrl, payload);
    return jsonDecode(response.body);
  }

  // API Call: Submit transfer transaction
  Future<Map<String, dynamic>> initiateTransfer({
    required String senderUpi,
    required String receiverUpi,
    required double amount,
    required String deviceId,
    required double lat,
    required double lon,
    required String pin,
    bool biometricFailed = false,
    String qrCode = '',
    String merchantName = '',
    String mccCode = '0000',
  }) async {
    final payload = {
      'sender_upi': senderUpi,
      'receiver_upi': receiverUpi,
      'amount': amount,
      'device_id': deviceId,
      'latitude': lat,
      'longitude': lon,
      'pin': pin,
      'biometric_failed': biometricFailed,
      'qr_code': qrCode,
      'merchant_name': merchantName,
      'mcc_code': mccCode,
    };
    
    final response = await postSecure(ApiConfig.transferUrl, payload);
    return jsonDecode(response.body);
  }

  // API Call: Verify OTP
  // API Call: Step-up dual OTP verification (Email + Telegram)
  Future<Map<String, dynamic>> verifyDualOtp({
    required String txnId,
    required String emailCode,
    required String telegramCode,
  }) async {
    final payload = {
      'txn_id': txnId,
      'email_code': emailCode,
      'telegram_code': telegramCode,
      'otp': emailCode,
    };
    final response = await postSecure(ApiConfig.verifyOtpUrl, payload);
    return jsonDecode(response.body);
  }

  // API Call: Website trust score check
  Future<Map<String, dynamic>> checkWebsiteTrust(String domain) async {
    final response = await getSecure(ApiConfig.websiteCheckUrl(domain));
    return jsonDecode(response.body);
  }

  // API Call: Fetch trusted payees
  Future<List<dynamic>> getTrustedPayees(String userId) async {
    final response = await getSecure(ApiConfig.getTrustedPayeesUrl(userId));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['trusted_payees'];
    }
    throw Exception("Failed to fetch trusted payees");
  }

  // API Call: Add trusted payee
  Future<Map<String, dynamic>> addTrustedPayee(String payeeUpi, String nickname) async {
    final payload = {
      'payee_upi': payeeUpi,
      'nickname': nickname,
    };
    final response = await postSecure(ApiConfig.addTrustedPayeeUrl, payload);
    return jsonDecode(response.body);
  }

  // API Call: Remove trusted payee
  Future<Map<String, dynamic>> deleteTrustedPayee(int payeeId) async {
    final response = await http.delete(
      Uri.parse(ApiConfig.deleteTrustedPayeeUrl(payeeId)),
      headers: {
        'Authorization': 'Bearer ${await getAccessToken()}',
        'Content-Type': 'application/json',
      },
    );
    return jsonDecode(response.body);
  }

  // API Call: Report scam UPI
  Future<Map<String, dynamic>> reportScamUpi(String upiId, String description) async {
    final payload = {
      'scam_upi': upiId,
      'description': description,
    };
    final response = await postSecure(ApiConfig.reportScamUrl, payload);
    return jsonDecode(response.body);
  }

  // API Call: Submit feedback
  Future<Map<String, dynamic>> submitFeedback({
    required String txnId,
    required bool isFraud,
    required bool predictedFraud,
    required String feedbackText,
  }) async {
    final payload = {
      'txn_id': txnId,
      'is_fraud': isFraud,
      'predicted_fraud': predictedFraud,
      'feedback_text': feedbackText,
    };
    final response = await postSecure(ApiConfig.feedbackUrl, payload);
    return jsonDecode(response.body);
  }
}
