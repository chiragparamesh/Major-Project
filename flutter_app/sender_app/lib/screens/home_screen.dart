import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/api_service.dart';
import '../config/app_theme.dart';
import 'registration_screen.dart';
import 'send_money_screen.dart';
import 'trusted_contacts_screen.dart';
import 'analytics_screen.dart';
import 'qr_generator_screen.dart';
import 'transaction_history_screen.dart';

class HomeScreen extends StatefulWidget {
  final String userId;

  const HomeScreen({super.key, required this.userId});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  double _balance = 0.0;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _fetchBalance();
  }

  Future<void> _fetchBalance() async {
    setState(() => _isLoading = true);
    try {
      final balance = await ApiService().getBalance(widget.userId);
      setState(() {
        _balance = balance;
      });
    } catch (_) {
      // If server is not ready or fails, fallback to standard balance display
      setState(() {
        _balance = 100000.00;
      });
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('logged_in_user');
    await ApiService().logout();
    if (mounted) {
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const RegistrationScreen()),
      );
    }
  }

  void _showReportScamDialog() {
    final upiController = TextEditingController();
    final descController = TextEditingController();
    bool sub = false;
    
    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: AppTheme.cardColor,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          title: const Text("Report Scam UPI ID", style: TextStyle(fontFamily: 'Outfit')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: upiController,
                decoration: const InputDecoration(labelText: "Scam UPI ID (e.g. crook@upi)"),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: descController,
                decoration: const InputDecoration(labelText: "Description (Optional)"),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text("Cancel", style: TextStyle(color: Colors.white60)),
            ),
            ElevatedButton(
              onPressed: sub ? null : () async {
                final scamUpi = upiController.text.trim();
                if (!scamUpi.contains('@')) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text("Please enter a valid UPI address")),
                  );
                  return;
                }
                setDialogState(() => sub = true);
                try {
                  final res = await ApiService().reportScamUpi(scamUpi, descController.text.trim());
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(res['message'] ?? "Report filed successfully")),
                    );
                    Navigator.pop(context);
                  }
                } catch (e) {
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text("Error reporting scam: $e")),
                    );
                  }
                } finally {
                  setDialogState(() => sub = false);
                }
              },
              child: const Text("Report"),
            )
          ],
        ),
      ),
    );
  }

  void _showWebsiteCheckDialog() {
    final domainController = TextEditingController();
    bool running = false;
    
    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: AppTheme.cardColor,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          title: const Text("Check Website Trust (WTS)", style: TextStyle(fontFamily: 'Outfit')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: domainController,
                decoration: const InputDecoration(
                  labelText: "Domain Name",
                  hintText: "e.g., support-helpdesk.in",
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text("Cancel", style: TextStyle(color: Colors.white60)),
            ),
            ElevatedButton(
              onPressed: running ? null : () async {
                final domain = domainController.text.trim().toLowerCase();
                if (domain.isEmpty) return;
                setDialogState(() => running = true);
                try {
                  final res = await ApiService().checkWebsiteTrust(domain);
                  if (mounted) {
                    Navigator.pop(context);
                    _showWtsResultDialog(domain, res);
                  }
                } catch (e) {
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text("Error checking website: $e")),
                    );
                  }
                } finally {
                  setDialogState(() => running = false);
                }
              },
              child: const Text("Analyze"),
            )
          ],
        ),
      ),
    );
  }

  void _showWtsResultDialog(String domain, Map<String, dynamic> result) {
    final score = double.parse(result['trust_score']?.toString() ?? '0');
    final verdict = result['verdict'] ?? 'UNKNOWN';
    final List<dynamic> reasons = result['reasons'] ?? [];
    
    Color scoreColor = AppTheme.safeColor;
    if (score > 30) scoreColor = AppTheme.warningColor;
    if (score > 60) scoreColor = AppTheme.cautionColor;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.cardColor,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text("WTS Result: $domain", style: const TextStyle(fontFamily: 'Outfit')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: scoreColor.withOpacity(0.1),
                ),
                child: Text(
                  "${score.toStringAsFixed(0)}%",
                  style: TextStyle(fontSize: 32, fontWeight: FontWeight.bold, color: scoreColor),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Center(
              child: Text(
                "VERDICT: $verdict",
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: scoreColor),
              ),
            ),
            const SizedBox(height: 16),
            const Text("Risk Markers Found:", style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            reasons.isEmpty
                ? const Text("No risk indicators. Site appears fully legitimate.", style: TextStyle(color: Colors.white60))
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: reasons.map((r) => Padding(
                      padding: const EdgeInsets.only(bottom: 6.0),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.warning_amber_rounded, color: Colors.amber, size: 16),
                          const SizedBox(width: 8),
                          Expanded(child: Text(r.toString(), style: const TextStyle(fontSize: 13, color: Colors.white70))),
                        ],
                      ),
                    )).toList(),
                  ),
          ],
        ),
        actions: [
          ElevatedButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("OK"),
          )
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("MLBFD Dashboard"),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _fetchBalance,
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: _logout,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _fetchBalance,
        child: SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(20.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // User Card (Balance display)
              Container(
                padding: const EdgeInsets.all(24),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [AppTheme.primaryColor, AppTheme.accentColor],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(24),
                  boxShadow: [
                    BoxShadow(
                      color: AppTheme.primaryColor.withOpacity(0.3),
                      blurRadius: 15,
                      spreadRadius: 2,
                    )
                  ],
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      "Welcome, ${widget.userId}",
                      style: const TextStyle(
                        fontSize: 16,
                        color: Colors.white70,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 16),
                    const Text(
                      "Virtual Training Balance",
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.white54,
                        letterSpacing: 0.5,
                      ),
                    ),
                    const SizedBox(height: 4),
                    _isLoading
                        ? const SizedBox(
                            height: 38,
                            width: 38,
                            child: CircularProgressIndicator(color: Colors.white),
                          )
                        : Text(
                            "₹${_balance.toLocaleString()}",
                            style: const TextStyle(
                              fontSize: 32,
                              fontWeight: FontWeight.bold,
                              color: Colors.white,
                              fontFamily: 'Outfit',
                            ),
                          ),
                  ],
                ),
              ),
              const SizedBox(height: 28),
              
              // Menu Options grid
              const Text(
                "Security Core Actions",
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  fontFamily: 'Outfit',
                ),
              ),
              const SizedBox(height: 16),
              
              GridView.count(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisCount: 2,
                childAspectRatio: 1.3,
                crossAxisSpacing: 16,
                mainAxisSpacing: 16,
                children: [
                  _buildMenuCard(
                    context: context,
                    icon: Icons.send_rounded,
                    label: "Send Money",
                    color: AppTheme.primaryColor,
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => SendMoneyScreen(senderUpi: widget.userId)),
                    ).then((_) => _fetchBalance()),
                  ),
                  _buildMenuCard(
                    context: context,
                    icon: Icons.qr_code_2_rounded,
                    label: "Receive QR",
                    color: AppTheme.accentColor,
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => QrGeneratorScreen(upiId: widget.userId)),
                    ),
                  ),
                  _buildMenuCard(
                    context: context,
                    icon: Icons.contact_phone_rounded,
                    label: "Trusted Contacts",
                    color: AppTheme.safeColor,
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => TrustedContactsScreen(userId: widget.userId)),
                    ),
                  ),
                  _buildMenuCard(
                    context: context,
                    icon: Icons.security_rounded,
                    label: "WTS Domain Check",
                    color: Colors.purpleAccent,
                    onTap: _showWebsiteCheckDialog,
                  ),
                  _buildMenuCard(
                    context: context,
                    icon: Icons.report_gmailerrorred_rounded,
                    label: "Report Scam",
                    color: AppTheme.cautionColor,
                    onTap: _showReportScamDialog,
                  ),
                  _buildMenuCard(
                    context: context,
                    icon: Icons.bar_chart_rounded,
                    label: "Analytics & History",
                    color: AppTheme.warningColor,
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => AnalyticsScreen(userId: widget.userId)),
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

  Widget _buildMenuCard({
    required BuildContext context,
    required IconData icon,
    required String label,
    required Color color,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppTheme.cardColor,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(
            color: color.withOpacity(0.2),
            width: 1,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: color.withOpacity(0.15),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(icon, color: color, size: 24),
            ),
            Text(
              label,
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.bold,
                color: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// Simple Helper to format numbers locally
extension DoubleFormatting on double {
  String toLocaleString() {
    return toStringAsFixed(2).replaceAllMapped(
      RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'),
      (Match m) => '${m[1]},',
    );
  }
}
