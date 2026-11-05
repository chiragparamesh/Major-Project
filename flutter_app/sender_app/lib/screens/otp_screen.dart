import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../services/api_service.dart';
import '../widgets/otp_delivery_status.dart';

/// Fraud step-up (REQUIRES_2FA): both the email and the Telegram code are required.
class OtpScreen extends StatefulWidget {
  final String txnId;
  final Map<String, dynamic> delivery;

  const OtpScreen({super.key, required this.txnId, this.delivery = const {}});

  @override
  State<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends State<OtpScreen> {
  final _emailCode = TextEditingController();
  final _telegramCode = TextEditingController();
  bool _isLoading = false;

  Future<void> _verify() async {
    final e = _emailCode.text.trim();
    final t = _telegramCode.text.trim();
    if (!RegExp(r'^\d{6}$').hasMatch(e) || !RegExp(r'^\d{6}$').hasMatch(t)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Enter both 6-digit codes (email and Telegram).')),
      );
      return;
    }
    setState(() => _isLoading = true);
    try {
      final res = await ApiService().verifyDualOtp(txnId: widget.txnId, emailCode: e, telegramCode: t);
      if (!mounted) return;
      if (res['success'] == true) {
        Navigator.pop(context, true);
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(res['message'] ?? 'Verification failed')),
        );
      }
    } catch (err) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $err')));
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Widget _codeField(TextEditingController c, String label, IconData icon) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: TextField(
          controller: c,
          keyboardType: TextInputType.number,
          maxLength: 6,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 22, letterSpacing: 6),
          decoration: InputDecoration(labelText: label, counterText: '', prefixIcon: Icon(icon)),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Confirm payment (2 codes)')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text('This payment was flagged for extra verification. Codes were sent to your '
              'registered email and Telegram. They are valid for 5 minutes, 3 attempts.'),
          const SizedBox(height: 12),
          OtpDeliveryStatus(delivery: widget.delivery, purpose: 'TRANSACTION', txnId: widget.txnId),
          _codeField(_emailCode, 'Email code', Icons.email_outlined),
          _codeField(_telegramCode, 'Telegram code', Icons.telegram),
          const SizedBox(height: 12),
          ElevatedButton(
            onPressed: _isLoading ? null : _verify,
            child: Text(_isLoading ? 'Verifying…' : 'Verify and pay'),
          ),
        ],
      ),
    );
  }
}
