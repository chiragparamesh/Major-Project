import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';

/// First-launch (and settings) screen: the MLBFD server URL, e.g. the
/// https://<name>.trycloudflare.com link printed by start_mlbfd.bat.
class ServerUrlScreen extends StatefulWidget {
  final VoidCallback onSaved;
  const ServerUrlScreen({super.key, required this.onSaved});

  @override
  State<ServerUrlScreen> createState() => _ServerUrlScreenState();
}

class _ServerUrlScreenState extends State<ServerUrlScreen> {
  late final TextEditingController _url = TextEditingController(text: ApiConfig.baseUrl);
  bool _checking = false;
  String? _error;

  Future<void> _save() async {
    final url = _url.text.trim();
    final uri = Uri.tryParse(url);
    if (uri == null || !(uri.isScheme('https') || uri.isScheme('http')) || uri.host.isEmpty) {
      setState(() => _error = 'Enter a full URL, e.g. https://abc-def.trycloudflare.com');
      return;
    }
    setState(() {
      _checking = true;
      _error = null;
    });
    try {
      final r = await http.get(Uri.parse('${url.replaceAll(RegExp(r"/+$"), "")}/api/register/timing_token'))
          .timeout(const Duration(seconds: 10));
      if (r.statusCode != 200) throw Exception('HTTP ${r.statusCode}');
      await ApiConfig.setBaseUrl(url);
      widget.onSaved();
    } catch (e) {
      setState(() => _error = 'Server not reachable at that URL ($e)');
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('MLBFD Server')),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Enter the MLBFD server address (the public link printed by start_mlbfd.bat, '
                'or http://<laptop-LAN-IP>:5000 on the same Wi-Fi).'),
            const SizedBox(height: 16),
            TextField(
              controller: _url,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: InputDecoration(
                labelText: 'Server URL',
                hintText: 'https://abc-def.trycloudflare.com',
                errorText: _error,
                prefixIcon: const Icon(Icons.link),
              ),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _checking ? null : _save,
              child: Text(_checking ? 'Checking…' : 'Save and continue'),
            ),
          ],
        ),
      ),
    );
  }
}
