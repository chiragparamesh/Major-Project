import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../config/app_theme.dart';

class TrustedContactsScreen extends StatefulWidget {
  final String userId;

  const TrustedContactsScreen({super.key, required this.userId});

  @override
  State<TrustedContactsScreen> createState() => _TrustedContactsScreenState();
}

class _TrustedContactsScreenState extends State<TrustedContactsScreen> {
  List<dynamic> _trustedList = [];
  bool _isLoading = true;
  final _upiController = TextEditingController();
  final _nameController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _fetchPayees();
  }

  Future<void> _fetchPayees() async {
    setState(() => _isLoading = true);
    try {
      final list = await ApiService().getTrustedPayees(widget.userId);
      setState(() {
        _trustedList = list;
      });
    } catch (_) {
      // Offline fallback mock data
      setState(() {
        _trustedList = [
          {'id': 1, 'payee_upi': 'bob@okaxis', 'nickname': 'Bob (Family)', 'txn_count': 5},
          {'id': 2, 'payee_upi': 'alice@oksbi', 'nickname': 'Alice (Office)', 'txn_count': 3},
        ];
      });
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _addPayee() async {
    final upi = _upiController.text.trim();
    final name = _nameController.text.trim();
    if (!upi.contains('@')) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Enter a valid UPI address")),
      );
      return;
    }

    try {
      final res = await ApiService().addTrustedPayee(upi, name);
      if (res['success'] == true) {
        _upiController.clear();
        _nameController.clear();
        if (mounted) Navigator.pop(context);
        _fetchPayees();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(res['message'] ?? "Failed to add payee")),
        );
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Error: $e")),
      );
    }
  }

  Future<void> _deletePayee(int id) async {
    try {
      final res = await ApiService().deleteTrustedPayee(id);
      if (res['success'] == true) {
        _fetchPayees();
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Error deleting: $e")),
      );
    }
  }

  void _showAddDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.cardColor,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Text("Add Trusted Contact"),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _upiController,
              decoration: const InputDecoration(labelText: "UPI Handle (e.g. name@bank)"),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _nameController,
              decoration: const InputDecoration(labelText: "Nickname"),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Cancel"),
          ),
          ElevatedButton(
            onPressed: _addPayee,
            child: const Text("Add Payee"),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Trusted Contacts"),
        actions: [
          IconButton(
            icon: const Icon(Icons.add),
            onPressed: _showAddDialog,
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _trustedList.isEmpty
              ? const Center(child: Text("No trusted contacts saved. Add some to bypass security delay!"))
              : ListView.builder(
                  padding: const EdgeInsets.all(16.0),
                  itemCount: _trustedList.length,
                  itemBuilder: (context, index) {
                    final item = _trustedList[index];
                    return Card(
                      color: AppTheme.cardColor,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                      margin: const EdgeInsets.only(bottom: 12),
                      child: ListTile(
                        leading: const CircleAvatar(
                          backgroundColor: Colors.indigo,
                          child: Icon(Icons.person, color: Colors.white),
                        ),
                        title: Text(
                          item['nickname'] != null && item['nickname'].toString().isNotEmpty
                              ? item['nickname']
                              : item['payee_upi'],
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        subtitle: Text(item['payee_upi']),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              "${item['txn_count']} txns",
                              style: const TextStyle(color: Colors.white54, fontSize: 12),
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline, color: AppTheme.cautionColor),
                              onPressed: () => _deletePayee(item['id']),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
    );
  }
}
