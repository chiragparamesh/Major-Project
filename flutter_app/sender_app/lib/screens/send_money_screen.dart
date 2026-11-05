import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:qr_code_scanner/qr_code_scanner.dart';
import '../services/api_service.dart';
import '../config/app_theme.dart';
import '../widgets/risk_gauge.dart';
import 'otp_screen.dart';
import 'biometric_screen.dart';

class SendMoneyScreen extends StatefulWidget {
  final String senderUpi;

  const SendMoneyScreen({super.key, required this.senderUpi});

  @override
  State<SendMoneyScreen> createState() => _SendMoneyScreenState();
}

class _SendMoneyScreenState extends State<SendMoneyScreen> {
  final _formKey = GlobalKey<FormState>();
  final _receiverController = TextEditingController();
  final _amountController = TextEditingController();
  
  bool _isLoading = false;
  bool _isPreviewing = false;
  
  // Real-time risk preview outputs
  double _riskScore = 0.0;
  String _verdict = "SAFE";
  List<dynamic> _flags = [];
  double _ensembleConfidence = 1.00;
  
  double _latitude = 28.6139;
  double _longitude = 77.2090;
  String _deviceId = "mock-device-id-pixel9a";
  bool _biometricFailed = false;

  final GlobalKey _qrKey = GlobalKey(debugLabel: 'QR');
  QRViewController? _qrController;
  bool _isScanning = false;

  @override
  void initState() {
    super.initState();
    _fetchLocation();
  }

  Future<void> _fetchLocation() async {
    try {
      final pos = await Geolocator.getCurrentPosition(desiredAccuracy: LocationAccuracy.low);
      setState(() {
        _latitude = pos.latitude;
        _longitude = pos.longitude;
      });
    } catch (_) {}
  }

  @override
  void dispose() {
    _qrController?.dispose();
    super.dispose();
  }

  // Pre-transfer What-If Risk Score check
  Future<void> _previewRisk() async {
    if (!_formKey.currentState!.validate()) return;
    
    setState(() {
      _isLoading = true;
      _isPreviewing = false;
    });

    try {
      final amt = double.parse(_amountController.text.trim());
      final res = await ApiService().checkRiskScore(
        senderUpi: widget.senderUpi,
        receiverUpi: _receiverController.text.trim(),
        amount: amt,
        deviceId: _deviceId,
        lat: _latitude,
        lon: _longitude,
        biometricFailed: _biometricFailed,
      );

      setState(() {
        _riskScore = double.parse(res['risk_score']?.toString() ?? '0');
        _verdict = res['verdict'] ?? 'SAFE';
        _flags = res['flags'] ?? [];
        _ensembleConfidence = double.parse(res['ensemble_confidence']?.toString() ?? '1.0');
        _isPreviewing = true;
      });
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Risk check failed: $e")),
      );
    } finally {
      setState(() => _isLoading = false);
    }
  }

  // Final submit transaction
  Future<void> _submitTransfer() async {
    final amt = double.parse(_amountController.text.trim());
    
    // Check if amount > 25000 and requires biometric check
    if (amt > 25000) {
      final bioSuccess = await Navigator.push<bool>(
        context,
        MaterialPageRoute(builder: (_) => const BiometricScreen()),
      );
      if (bioSuccess != true) {
        setState(() {
          _biometricFailed = true;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Biometric verification failed. High risk penalty applied.")),
        );
        // Recalculate preview
        await _previewRisk();
        return;
      }
    }

    // Prompt for UPI PIN
    final String? pin = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        final pinController = TextEditingController();
        return AlertDialog(
          backgroundColor: AppTheme.cardColor,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
          title: const Row(
            children: [
              Icon(Icons.lock_outline, color: AppTheme.accentColor),
              SizedBox(width: 8),
              Text("Enter UPI PIN", style: TextStyle(fontFamily: 'Outfit')),
            ],
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text("Confirm transfer of ₹$amt to ${_receiverController.text.trim()}"),
              const SizedBox(height: 16),
              TextField(
                controller: pinController,
                obscureText: true,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: const InputDecoration(
                  labelText: "6-Digit Payment PIN",
                  prefixIcon: Icon(Icons.key),
                  counterText: "",
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, null),
              child: const Text("Cancel"),
            ),
            ElevatedButton(
              onPressed: () {
                if (pinController.text.length == 6) {
                  Navigator.pop(ctx, pinController.text);
                }
              },
              child: const Text("Submit"),
            ),
          ],
        );
      },
    );

    if (pin == null || pin.length != 6) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Transaction cancelled: UPI PIN required.")),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      final res = await ApiService().initiateTransfer(
        senderUpi: widget.senderUpi,
        receiverUpi: _receiverController.text.trim(),
        amount: amt,
        deviceId: _deviceId,
        lat: _latitude,
        lon: _longitude,
        pin: pin,
        biometricFailed: _biometricFailed,
      );

      final status = res['status'] ?? 'APPROVED';
      final txnId = res['txn_id'] ?? '';

      if (status == 'APPROVED' || status == 'APPROVED_WITH_WARNING') {
        if (mounted) {
          _showResultDialog(
            title: "Transfer Successful!",
            message: "Successfully sent ₹$amt to ${_receiverController.text.trim()}.",
            isSuccess: true,
            warnings: res['flags'] ?? [],
          );
        }
      } else if (status == 'REQUIRES_2FA') {
        if (mounted) {
          final otpVerifySuccess = await Navigator.push<bool>(
            context,
            MaterialPageRoute(
              builder: (_) => OtpScreen(
                txnId: txnId,
                delivery: Map<String, dynamic>.from(res['delivery'] ?? {}),
              ),
            ),
          );
          if (otpVerifySuccess == true) {
            _showResultDialog(
              title: "Transfer Successful!",
              message: "Successfully verified and sent ₹$amt to ${_receiverController.text.trim()}.",
              isSuccess: true,
            );
          }
        }
      } else {
        // Blocked
        if (mounted) {
          _showResultDialog(
            title: "Transaction Blocked",
            message: "This transaction was blocked due to extreme fraud risk indicators.",
            isSuccess: false,
            warnings: res['flags'] ?? [],
          );
        }
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Transaction submission failed: $e")),
      );
    } finally {
      setState(() => _isLoading = false);
    }
  }

  void _showResultDialog({
    required String title,
    required String message,
    required bool isSuccess,
    List<dynamic> warnings = const [],
  }) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.cardColor,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        title: Row(
          children: [
            Icon(
              isSuccess ? Icons.check_circle : Icons.cancel_rounded,
              color: isSuccess ? AppTheme.safeColor : AppTheme.cautionColor,
              size: 28,
            ),
            const SizedBox(width: 8),
            Text(title, style: const TextStyle(fontFamily: 'Outfit')),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(message),
            if (warnings.isNotEmpty) ...[
              const SizedBox(height: 16),
              const Text("Risk Factors Flagged:", style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: warnings.map((w) => Text("• $w", style: const TextStyle(color: Colors.amber, fontSize: 13))).toList(),
              ),
            ]
          ],
        ),
        actions: [
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx); // Close dialog
              Navigator.pop(context); // Go back home
            },
            child: const Text("Go to Home"),
          )
        ],
      ),
    );
  }

  void _startQrScanner() {
    setState(() {
      _isScanning = true;
    });
  }

  void _onQrViewCreated(QRViewController controller) {
    _qrController = controller;
    controller.scannedDataStream.listen((scanData) {
      final code = scanData.code;
      if (code != null && code.startsWith('upi://pay?')) {
        controller.pauseCamera();
        
        // Parse UPI query string manually
        final uri = Uri.parse(code);
        final payee = uri.queryParameters['pa'] ?? '';
        final amount = uri.queryParameters['am'] ?? '';
        
        setState(() {
          _receiverController.text = payee;
          if (amount.isNotEmpty) {
            _amountController.text = amount;
          }
          _isScanning = false;
        });
        _qrController?.dispose();
        _qrController = null;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_isScanning) {
      return Scaffold(
        appBar: AppBar(
          title: const Text("Scan UPI QR Code"),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () {
              setState(() => _isScanning = false);
              _qrController?.dispose();
              _qrController = null;
            },
          ),
        ),
        body: QRView(
          key: _qrKey,
          onQRViewCreated: _onQrViewCreated,
          overlay: QrScannerOverlayShape(
            borderColor: AppTheme.primaryColor,
            borderRadius: 10,
            borderLength: 30,
            borderWidth: 10,
            cutOutSize: 250,
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text("Transfer Money"),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Card(
                color: AppTheme.cardColor,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                child: Padding(
                  padding: const EdgeInsets.all(20.0),
                  child: Column(
                    children: [
                      TextFormField(
                        controller: _receiverController,
                        decoration: InputDecoration(
                          labelText: "Receiver UPI Handle",
                          hintText: "receiver@bank",
                          prefixIcon: const Icon(Icons.alternate_email),
                          suffixIcon: IconButton(
                            icon: const Icon(Icons.qr_code_scanner, color: AppTheme.accentColor),
                            onPressed: _startQrScanner,
                          ),
                        ),
                        validator: (val) {
                          if (val == null || val.trim().isEmpty) return "Receiver UPI ID is required";
                          if (!val.contains('@')) return "Enter a valid UPI ID (e.g. name@bank)";
                          return null;
                        },
                      ),
                      const SizedBox(height: 16),
                      
                      TextFormField(
                        controller: _amountController,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: "Transfer Amount (₹)",
                          hintText: "0.00",
                          prefixIcon: Icon(Icons.currency_rupee),
                        ),
                        validator: (val) {
                          if (val == null || val.trim().isEmpty) return "Amount is required";
                          final amt = double.tryParse(val);
                          if (amt == null || amt <= 0) return "Please enter a valid amount";
                          return null;
                        },
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 20),
              
              ElevatedButton.icon(
                onPressed: _isLoading ? null : _previewRisk,
                icon: const Icon(Icons.analytics_outlined),
                label: const Text("Perform What-If Risk Check"),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.accentColor,
                ),
              ),
              
              if (_isPreviewing) ...[
                const SizedBox(height: 24),
                Card(
                  color: const Color(0xFF1E293B),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
                  child: Padding(
                    padding: const EdgeInsets.all(24.0),
                    child: Column(
                      children: [
                        const Text(
                          "Explainable AI Risk Report",
                          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, fontFamily: 'Outfit'),
                        ),
                        const SizedBox(height: 16),
                        RiskGauge(score: _riskScore),
                        const SizedBox(height: 16),
                        Text(
                          "Ensemble Model Confidence: ${(_ensembleConfidence * 100).toStringAsFixed(1)}%",
                          style: const TextStyle(color: Colors.white54, fontSize: 13),
                        ),
                        const SizedBox(height: 12),
                        const Divider(color: Colors.white12),
                        const SizedBox(height: 12),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: Text(
                            "Audit Log Flags (${_flags.length}):",
                            style: const TextStyle(fontWeight: FontWeight.bold),
                          ),
                        ),
                        const SizedBox(height: 8),
                        _flags.isEmpty
                            ? const Align(
                                alignment: Alignment.centerLeft,
                                child: Text("No high-risk behaviors flagged.", style: TextStyle(color: Colors.white60)),
                              )
                            : Column(
                                children: _flags.map((f) => Padding(
                                  padding: const EdgeInsets.only(bottom: 6.0),
                                  child: Row(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      const Icon(Icons.circle, size: 8, color: AppTheme.cautionColor),
                                      const SizedBox(width: 8),
                                      Expanded(child: Text(f.toString(), style: const TextStyle(color: Colors.white70, fontSize: 13))),
                                    ],
                                  ),
                                )).toList(),
                              ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: _isLoading ? null : _submitTransfer,
                  child: const Text("Confirm and Authorize Payment"),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
