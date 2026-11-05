import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../config/app_theme.dart';
import 'home_screen.dart'; // for double formatting extension

class BalanceScreen extends StatefulWidget {
  final String userId;

  const BalanceScreen({super.key, required this.userId});

  @override
  State<BalanceScreen> createState() => _BalanceScreenState();
}

class _BalanceScreenState extends State<BalanceScreen> {
  double _balance = 0.0;
  List<dynamic> _txns = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _fetchBalanceAndStats();
  }

  Future<void> _fetchBalanceAndStats() async {
    setState(() => _isLoading = true);
    try {
      final balance = await ApiService().getBalance(widget.userId);
      final txns = await ApiService().getTransactions(widget.userId);
      setState(() {
        _balance = balance;
        _txns = txns;
      });
    } catch (_) {
      // Mock data in case backend is offline
      setState(() {
        _balance = 100000.00;
        _txns = [];
      });
    } finally {
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Calculate stats
    final approvedTxns = _txns.where((t) => t['status'] == 'APPROVED').toList();
    final double totalVolume = approvedTxns.fold(0.0, (sum, t) => sum + double.parse(t['amount'].toString()));
    final double avgAmount = approvedTxns.isEmpty ? 0.0 : totalVolume / approvedTxns.length;
    final blockedTxnsCount = _txns.where((t) => t['status'] == 'BLOCKED').length;

    return Scaffold(
      appBar: AppBar(
        title: const Text("Account Balance & Stats"),
      ),
      body: RefreshIndicator(
        onRefresh: _fetchBalanceAndStats,
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : SingleChildScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Balance Card
                    Card(
                      color: AppTheme.cardColor,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
                      child: Padding(
                        padding: const EdgeInsets.all(24.0),
                        child: Column(
                          children: [
                            const Text(
                              "Current Virtual Balance",
                              style: TextStyle(color: Colors.white54, fontSize: 14),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              "₹${_balance.toLocaleString()}",
                              style: const TextStyle(
                                fontSize: 36,
                                fontWeight: FontWeight.bold,
                                color: AppTheme.primaryColor,
                                fontFamily: 'Outfit',
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              widget.userId,
                              style: const TextStyle(color: Colors.white30, fontSize: 13),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),

                    const Text(
                      "Inbound Analytics",
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, fontFamily: 'Outfit'),
                    ),
                    const SizedBox(height: 16),

                    Row(
                      children: [
                        Expanded(
                          child: _buildStatCard(
                            label: "Total Received",
                            value: "₹${totalVolume.toLocaleString()}",
                            icon: Icons.monetization_on_outlined,
                            iconColor: AppTheme.primaryColor,
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: _buildStatCard(
                            label: "Transactions",
                            value: "${approvedTxns.length}",
                            icon: Icons.receipt_outlined,
                            iconColor: AppTheme.accentColor,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    Row(
                      children: [
                        Expanded(
                          child: _buildStatCard(
                            label: "Average Inbound",
                            value: "₹${avgAmount.toLocaleString()}",
                            icon: Icons.analytics_outlined,
                            iconColor: Colors.purpleAccent,
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: _buildStatCard(
                            label: "Blocked Fraud",
                            value: "$blockedTxnsCount Attempts",
                            icon: Icons.gpp_bad_outlined,
                            iconColor: AppTheme.cautionColor,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
      ),
    );
  }

  Widget _buildStatCard({
    required String label,
    required String value,
    required IconData icon,
    required Color iconColor,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppTheme.cardColor,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: iconColor, size: 28),
          const SizedBox(height: 12),
          Text(
            value,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, fontFamily: 'Outfit'),
          ),
          const SizedBox(height: 4),
          Text(
            label,
            style: const TextStyle(fontSize: 12, color: Colors.white54),
          ),
        ],
      ),
    );
  }
}
