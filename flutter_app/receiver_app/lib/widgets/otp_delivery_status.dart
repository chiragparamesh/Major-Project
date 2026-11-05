import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';

/// Per-channel OTP delivery status ({"email": "sent", "telegram": "not_linked"})
/// with a Resend button per channel (30 s cooldown, mirrors the server rule).
class OtpDeliveryStatus extends StatefulWidget {
  final Map<String, dynamic> delivery;
  final String purpose;
  final String? userId;
  final String? txnId;
  final bool allowResend;

  const OtpDeliveryStatus({
    super.key,
    required this.delivery,
    required this.purpose,
    this.userId,
    this.txnId,
    this.allowResend = true,
  });

  @override
  State<OtpDeliveryStatus> createState() => _OtpDeliveryStatusState();
}

class _OtpDeliveryStatusState extends State<OtpDeliveryStatus> {
  static const int cooldownSeconds = 30;
  late Map<String, String> _status;
  final Map<String, int> _cooldown = {};
  final Map<String, String> _error = {};
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _status = widget.delivery.map((k, v) => MapEntry(k, v.toString()));
    for (final ch in _status.keys) {
      _cooldown[ch] = _status[ch] == 'not_linked' ? 0 : cooldownSeconds;
    }
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() {
        _cooldown.updateAll((_, v) => v > 0 ? v - 1 : 0);
      });
    });
  }

  @override
  void didUpdateWidget(OtpDeliveryStatus old) {
    super.didUpdateWidget(old);
    if (old.delivery != widget.delivery) {
      _status = widget.delivery.map((k, v) => MapEntry(k, v.toString()));
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _resend(String channel) async {
    setState(() {
      _cooldown[channel] = cooldownSeconds;
      _status[channel] = 'pending';
      _error.remove(channel);
    });
    try {
      final res = await ApiService().resendOtp(
        purpose: widget.purpose,
        channel: channel,
        userId: widget.userId,
        txnId: widget.txnId,
      );
      final d = res['delivery'];
      if (!mounted) return;
      setState(() {
        _status[channel] = (d is Map && d[channel] != null) ? d[channel].toString() : (res['success'] == true ? 'sent' : 'failed');
        if (res['success'] != true) {
          _error[channel] = (res['message'] ?? 'HTTP ${res['http_status']}').toString();
          if (res['http_status'] != 429) _cooldown[channel] = 0;
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _status[channel] = 'failed';
        _error[channel] = 'network error';
        _cooldown[channel] = 0;
      });
    }
  }

  Color _color(String s) {
    switch (s) {
      case 'sent':
        return Colors.greenAccent;
      case 'pending':
        return Colors.lightBlueAccent;
      case 'dry_run':
      case 'not_linked':
        return Colors.orangeAccent;
      default:
        return Colors.redAccent;
    }
  }

  String _label(String s) => const {
        'sent': 'sent',
        'pending': 'sending…',
        'dry_run': 'sent (dry-run)',
        'not_linked': 'not linked',
        'failed': 'failed',
      }[s] ??
      s;

  @override
  Widget build(BuildContext context) {
    if (_status.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: ['email', 'telegram'].where(_status.containsKey).map((ch) {
        final left = _cooldown[ch] ?? 0;
        return Container(
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            border: Border.all(color: Colors.white24),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              Icon(ch == 'email' ? Icons.email_outlined : Icons.telegram, size: 18),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text.rich(TextSpan(children: [
                      TextSpan(text: ch == 'email' ? 'Email: ' : 'Telegram: '),
                      TextSpan(
                        text: _label(_status[ch]!),
                        style: TextStyle(color: _color(_status[ch]!), fontWeight: FontWeight.bold),
                      ),
                    ])),
                    if (_error[ch] != null)
                      Text(_error[ch]!, style: const TextStyle(fontSize: 11, color: Colors.redAccent)),
                  ],
                ),
              ),
              if (widget.allowResend)
                TextButton(
                  onPressed: left > 0 ? null : () => _resend(ch),
                  child: Text(left > 0 ? 'Resend in ${left}s' : 'Resend'),
                ),
            ],
          ),
        );
      }).toList(),
    );
  }
}
