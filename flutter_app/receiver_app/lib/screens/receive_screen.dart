import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';
import '../config/app_theme.dart';

class ReceiveScreen extends StatefulWidget {
  final String upiId;

  const ReceiveScreen({super.key, required this.upiId});

  @override
  State<ReceiveScreen> createState() => _ReceiveScreenState();
}

class _ReceiveScreenState extends State<ReceiveScreen> {
  final _amountController = TextEditingController();
  final _noteController = TextEditingController();
  String _qrData = "";

  @override
  void initState() {
    super.initState();
    _generateQr();
  }

  void _generateQr() {
    final amt = _amountController.text.trim();
    final note = Uri.encodeComponent(_noteController.text.trim());
    
    // Standard UPI Link Format
    // upi://pay?pa=receiver@bank&pn=Merchant&am=100&cu=INR&tn=note
    String link = "upi://pay?pa=${widget.upiId}&pn=MLBFD%20Merchant&cu=INR";
    if (amt.isNotEmpty) {
      link += "&am=$amt";
    }
    if (note.isNotEmpty) {
      link += "&tn=$note";
    }
    
    setState(() {
      _qrData = link;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Receive Payment QR"),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Card(
              color: AppTheme.cardColor,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
              child: Padding(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  children: [
                    if (_qrData.isNotEmpty) ...[
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: QrImageView(
                          data: _qrData,
                          version: QrVersions.auto,
                          size: 220.0,
                          gapless: false,
                        ),
                      ),
                      const SizedBox(height: 16),
                      Text(
                        widget.upiId,
                        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        "Scan this QR to pay this Merchant account",
                        style: TextStyle(color: Colors.white38, fontSize: 13),
                        textAlign: TextAlign.center,
                      ),
                    ]
                  ],
                ),
              ),
            ),
            const SizedBox(height: 24),
            
            TextField(
              controller: _amountController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: "Request Amount (Optional)",
                hintText: "0.00",
              ),
              onChanged: (_) => _generateQr(),
            ),
            const SizedBox(height: 16),
            
            TextField(
              controller: _noteController,
              decoration: const InputDecoration(
                labelText: "Payment Note (Optional)",
                hintText: "e.g., Invoice 123",
              ),
              onChanged: (_) => _generateQr(),
            ),
          ],
        ),
      ),
    );
  }
}
