import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';
import '../config/app_theme.dart';

class BiometricScreen extends StatefulWidget {
  const BiometricScreen({super.key});

  @override
  State<BiometricScreen> createState() => _BiometricScreenState();
}

class _BiometricScreenState extends State<BiometricScreen> {
  final LocalAuthentication _auth = LocalAuthentication();
  bool _isAuthenticating = false;

  Future<void> _authenticate() async {
    setState(() => _isAuthenticating = true);
    try {
      final isAvailable = await _auth.canCheckBiometrics || await _auth.isDeviceSupported();
      
      if (!isAvailable) {
        // Fallback simulator for desktop/devices with no biometric hardware
        _simulateDialog();
        return;
      }
      
      final authenticated = await _auth.authenticate(
        localizedReason: 'Please authenticate to complete transaction of amount > ₹25,000',
        biometricOnly: true,
        persistAcrossBackgrounding: true,
      );
      
      if (mounted) {
        Navigator.pop(context, authenticated);
      }
    } catch (_) {
      _simulateDialog();
    } finally {
      if (mounted) setState(() => _isAuthenticating = false);
    }
  }

  void _simulateDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.cardColor,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Text("Biometric Simulation"),
        content: const Text("Select outcome for mock biometric verification:"),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              Navigator.pop(context, false); // Failed outcome
            },
            child: const Text("FAIL VERIFICATION", style: TextStyle(color: AppTheme.cautionColor)),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              Navigator.pop(context, true); // Success outcome
            },
            child: const Text("PASS VERIFICATION"),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Biometric Check"),
      ),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Icon(
              Icons.fingerprint_rounded,
              size: 100,
              color: AppTheme.primaryColor,
            ),
            const SizedBox(height: 24),
            const Text(
              "Biometric Authorization Required",
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.bold,
                fontFamily: 'Outfit',
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              "Transactions exceeding ₹25,000 must verify identity via biometric scanner to check for compromised session.",
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.white60, fontSize: 14),
            ),
            const SizedBox(height: 48),
            ElevatedButton(
              onPressed: _isAuthenticating ? null : _authenticate,
              child: const Text("Touch Sensor / Authenticate"),
            ),
          ],
        ),
      ),
    );
  }
}
