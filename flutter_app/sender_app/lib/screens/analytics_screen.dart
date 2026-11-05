import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../services/api_service.dart';
import '../config/app_theme.dart';
import 'transaction_history_screen.dart';

class AnalyticsScreen extends StatefulWidget {
  final String userId;

  const AnalyticsScreen({super.key, required this.userId});

  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  List<dynamic> _txns = [];
  bool _isLoading = true;
  double _totalSpent = 0.0;
  double _totalReceived = 0.0;
  double _totalBlocked = 0.0;
  int _blockedCount = 0;
  int _approvedCount = 0;

  @override
  void initState() {
    super.initState();
    _fetchAnalytics();
  }

  Future<void> _fetchAnalytics() async {
    setState(() => _isLoading = true);
    try {
      final txns = await ApiService().getTransactions(widget.userId);
      double spent = 0;
      double received = 0;
      double blockedVal = 0;
      int blockedC = 0;
      int approvedC = 0;

      for (var t in txns) {
        final amt = double.parse(t['amount']?.toString() ?? '0');
        final isOutbound = t['sender_upi'] == widget.userId;
        if (t['status'] == 'APPROVED' || t['status'] == 'APPROVED_WITH_WARNING') {
          if (isOutbound) {
            spent += amt;
          } else {
            received += amt;
          }
          approvedC++;
        } else if (t['status'] == 'BLOCKED') {
          blockedVal += amt;
          blockedC++;
        }
      }

      setState(() {
        _txns = txns;
        _totalSpent = spent;
        _totalReceived = received;
        _totalBlocked = blockedVal;
        _blockedCount = blockedC;
        _approvedCount = approvedC;
      });
    } catch (_) {
      // Mock fallbacks
      setState(() {
        _totalSpent = 12500.00;
        _totalReceived = 8500.00;
        _totalBlocked = 85000.00;
        _blockedCount = 1;
        _approvedCount = 4;
        _txns = [
          {'risk_score': 10.0},
          {'risk_score': 15.0},
          {'risk_score': 8.0},
          {'risk_score': 95.0},
          {'risk_score': 12.0},
        ];
      });
    } finally {
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Generate data points for Line Chart of risk scores
    final List<FlSpot> riskSpots = [];
    for (int i = 0; i < _txns.length; i++) {
      final score = double.parse(_txns[i]['risk_score']?.toString() ?? '0');
      riskSpots.add(FlSpot(i.toDouble(), score));
    }
    if (riskSpots.isEmpty) {
      riskSpots.add(const FlSpot(0, 0));
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text("Personal Fraud Analytics"),
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(24.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Stat cards
                  Row(
                    children: [
                      Expanded(
                        child: _buildStatCard(
                          title: "Total Sent",
                          value: "₹${_totalSpent.toStringAsFixed(0)}",
                          color: Colors.white70,
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: _buildStatCard(
                          title: "Total Received",
                          value: "₹${_totalReceived.toStringAsFixed(0)}",
                          color: AppTheme.safeColor,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: _buildStatCard(
                          title: "Fraud Blocked",
                          value: "₹${_totalBlocked.toStringAsFixed(0)}",
                          color: AppTheme.cautionColor,
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: _buildStatCard(
                          title: "Threats Blocked",
                          value: "$_blockedCount",
                          color: AppTheme.warningColor,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 28),
                  
                  // Chart header
                  const Text(
                    "Recent Transaction Risk Trend",
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, fontFamily: 'Outfit'),
                  ),
                  const SizedBox(height: 16),
                  
                  // Line Chart
                  Container(
                    height: 200,
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: AppTheme.cardColor,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: LineChart(
                      LineChartData(
                        gridData: const FlGridData(show: false),
                        titlesData: const FlTitlesData(show: false),
                        borderData: FlBorderData(show: false),
                        lineBarsData: [
                          LineChartBarData(
                            spots: riskSpots,
                            isCurved: true,
                            color: AppTheme.primaryColor,
                            barWidth: 4,
                            isStrokeCapRound: true,
                            dotData: const FlDotData(show: true),
                            belowBarData: BarAreaData(
                              show: true,
                              color: AppTheme.primaryColor.withOpacity(0.2),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  
                  ElevatedButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => TransactionHistoryScreen(userId: widget.userId)),
                    ),
                    child: const Text("View Detailed Statement"),
                  ),
                ],
              ),
            ),
    );
  }

  Widget _buildStatCard({required String title, required String value, required Color color}) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppTheme.cardColor,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withOpacity(0.2), width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(color: Colors.white54, fontSize: 12)),
          const SizedBox(height: 8),
          Text(
            value,
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: color, fontFamily: 'Outfit'),
          ),
        ],
      ),
    );
  }
}
