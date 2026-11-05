import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../config/app_theme.dart';
import 'package:intl/intl.dart';

class TransactionHistoryScreen extends StatefulWidget {
  final String userId;

  const TransactionHistoryScreen({super.key, required this.userId});

  @override
  State<TransactionHistoryScreen> createState() => _TransactionHistoryScreenState();
}

class _TransactionHistoryScreenState extends State<TransactionHistoryScreen> {
  List<dynamic> _txns = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _fetchHistory();
  }

  Future<void> _fetchHistory() async {
    setState(() => _isLoading = true);
    try {
      final txns = await ApiService().getTransactions(widget.userId);
      setState(() {
        _txns = txns;
      });
    } catch (_) {
      // Mock history in case backend is not fully loaded
      setState(() {
        _txns = [
          {
            'txn_id': 'TXN-1716300000000',
            'sender_upi': widget.userId,
            'receiver_upi': 'bob@okaxis',
            'amount': 250.00,
            'status': 'APPROVED',
            'risk_score': 8.50,
            'is_fraud': false,
            'created_at': DateTime.now().subtract(const Duration(hours: 2)).toIso8601String()
          },
          {
            'txn_id': 'TXN-1716290000000',
            'sender_upi': widget.userId,
            'receiver_upi': 'hacker@scam',
            'amount': 85000.00,
            'status': 'BLOCKED',
            'risk_score': 95.00,
            'is_fraud': true,
            'created_at': DateTime.now().subtract(const Duration(days: 1)).toIso8601String()
          }
        ];
      });
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Color _getStatusColor(String status) {
    switch (status) {
      case 'APPROVED':
        return AppTheme.safeColor;
      case 'APPROVED_WITH_WARNING':
        return AppTheme.warningColor;
      case 'REQUIRES_2FA':
        return AppTheme.cautionColor;
      default:
        return AppTheme.blockColor;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Transaction History"),
      ),
      body: RefreshIndicator(
        onRefresh: _fetchHistory,
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _txns.isEmpty
                ? const Center(child: Text("No transaction history recorded yet."))
                : ListView.builder(
                    padding: const EdgeInsets.all(16.0),
                    itemCount: _txns.length,
                    itemBuilder: (context, index) {
                      final t = _txns[index];
                      final statusColor = _getStatusColor(t['status']);
                      final createdDate = DateTime.parse(t['created_at']);
                      final dateStr = DateFormat('dd MMM yyyy, hh:mm a').format(createdDate);
                      
                      final isOutbound = t['sender_upi'] == widget.userId;
                      final isApproved = t['status'] == 'APPROVED' || t['status'] == 'APPROVED_WITH_WARNING';
                      
                      Color amountColor = Colors.white;
                      if (isApproved) {
                        amountColor = isOutbound ? Colors.white70 : AppTheme.safeColor;
                      } else if (t['status'] == 'BLOCKED') {
                        amountColor = AppTheme.blockColor;
                      }
                      
                      IconData iconData = Icons.payment_rounded;
                      if (t['status'] == 'BLOCKED') {
                        iconData = Icons.block_flipped;
                      } else if (!isOutbound) {
                        iconData = Icons.call_received_rounded;
                      }
                      
                      return Card(
                        color: AppTheme.cardColor,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                        margin: const EdgeInsets.only(bottom: 12),
                        child: InkWell(
                          borderRadius: BorderRadius.circular(16),
                          onTap: () => _showTxnDetails(t),
                          child: Padding(
                            padding: const EdgeInsets.all(16.0),
                            child: Row(
                              children: [
                                Container(
                                  padding: const EdgeInsets.all(12),
                                  decoration: BoxDecoration(
                                    color: statusColor.withOpacity(0.12),
                                    shape: BoxShape.circle,
                                  ),
                                  child: Icon(
                                    iconData,
                                    color: statusColor,
                                    size: 24,
                                  ),
                                ),
                                const SizedBox(width: 16),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        isOutbound ? "To: ${t['receiver_upi']}" : "From: ${t['sender_upi']}",
                                        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        dateStr,
                                        style: const TextStyle(color: Colors.white38, fontSize: 12),
                                      ),
                                    ],
                                  ),
                                ),
                                Column(
                                  crossAxisAlignment: CrossAxisAlignment.end,
                                  children: [
                                    Text(
                                      "${isOutbound ? '-' : '+'}${"₹${t['amount'].toString()}"}",
                                      style: TextStyle(
                                        fontSize: 16,
                                        fontWeight: FontWeight.bold,
                                        fontFamily: 'Outfit',
                                        color: amountColor,
                                      ),
                                    ),
                                    const SizedBox(height: 4),
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                      decoration: BoxDecoration(
                                        color: statusColor.withOpacity(0.15),
                                        borderRadius: BorderRadius.circular(8),
                                      ),
                                      child: Text(
                                        t['status'].toString().replaceAll('_', ' '),
                                        style: TextStyle(color: statusColor, fontSize: 10, fontWeight: FontWeight.bold),
                                      ),
                                    )
                                  ],
                                )
                              ],
                            ),
                          ),
                        ),
                      );
                    },
                  ),
      ),
    );
  }

  void _showTxnDetails(Map<String, dynamic> t) {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppTheme.cardColor,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: const BoxDecoration(color: Colors.white12, borderRadius: BorderRadius.all(Radius.circular(2))),
              ),
            ),
            const SizedBox(height: 18),
            Text(
              "Transaction Detail",
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, fontFamily: 'Outfit'),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text("Txn ID", style: TextStyle(color: Colors.white60)),
                Text(t['txn_id'], style: const TextStyle(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text("Sender UPI", style: TextStyle(color: Colors.white60)),
                Text(t['sender_upi'] ?? 'Unknown', style: const TextStyle(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text("Receiver UPI", style: TextStyle(color: Colors.white60)),
                Text(t['receiver_upi'], style: const TextStyle(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text("Amount", style: TextStyle(color: Colors.white60)),
                Text("₹${t['amount']}", style: const TextStyle(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text("Risk Score", style: TextStyle(color: Colors.white60)),
                Text("${t['risk_score']}%", style: const TextStyle(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text("Status", style: TextStyle(color: Colors.white60)),
                Text(
                  t['status'].toString().replaceAll('_', ' '),
                  style: TextStyle(fontWeight: FontWeight.bold, color: _getStatusColor(t['status'])),
                ),
              ],
            ),
            const SizedBox(height: 28),
            ElevatedButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("Dismiss"),
            )
          ],
        ),
      ),
    );
  }
}
