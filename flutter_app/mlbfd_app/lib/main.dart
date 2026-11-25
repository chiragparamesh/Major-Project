import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// MLBFD phone app.
///
/// A thin shell around the MLBFD server's web app (signup, login, payments, PIN reset ...).
/// On first launch it asks for the server address printed by `start_mlbfd.bat`
/// ("SHARE ON SAME WI-FI: http://LAPTOP-IP:5000/user/register"), tests it, remembers it,
/// and opens the app. All screens live on the server, so server fixes reach every phone at once.
const _prefsKey = 'server_base_url';
const _bg = Color(0xFF0B0716);
const _brand = Color(0xFF7C3AED);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const MlbfdApp());
}

class MlbfdApp extends StatelessWidget {
  const MlbfdApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MLBFD',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(useMaterial3: true).copyWith(
        scaffoldBackgroundColor: _bg,
        colorScheme: const ColorScheme.dark(primary: _brand, surface: _bg),
      ),
      home: const _Launcher(),
    );
  }
}

/// Decides between the connect screen and the web app.
class _Launcher extends StatefulWidget {
  const _Launcher();

  @override
  State<_Launcher> createState() => _LauncherState();
}

class _LauncherState extends State<_Launcher> {
  String? _baseUrl;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() {
      _baseUrl = prefs.getString(_prefsKey);
      _loaded = true;
    });
  }

  Future<void> _saved(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, url);
    if (mounted) setState(() => _baseUrl = url);
  }

  Future<void> _changeServer() async {
    if (mounted) setState(() => _baseUrl = null);
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (_baseUrl == null) return ConnectScreen(onConnected: _saved);
    return WebScreen(baseUrl: _baseUrl!, onChangeServer: _changeServer);
  }
}

/// "10.0.0.5" -> "http://10.0.0.5:5000", "https://x.trycloudflare.com/" -> "https://x.trycloudflare.com".
String? normalizeServerAddress(String raw) {
  var t = raw.trim();
  if (t.isEmpty) return null;
  if (!t.contains('://')) t = 'http://$t';
  final u = Uri.tryParse(t);
  if (u == null || u.host.isEmpty || !(u.scheme == 'http' || u.scheme == 'https')) return null;
  final port = u.hasPort ? ':${u.port}' : (u.scheme == 'http' ? ':5000' : '');
  return '${u.scheme}://${u.host}$port';
}

/// Returns null when [base] answers like an MLBFD server, otherwise a human-readable problem.
Future<String?> checkServer(String base) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 6);
  try {
    final req = await client.getUrl(Uri.parse('$base/api/register/timing_token')).timeout(const Duration(seconds: 8));
    final res = await req.close().timeout(const Duration(seconds: 8));
    final body = await res.transform(utf8.decoder).join().timeout(const Duration(seconds: 8));
    if (res.statusCode == 200 && body.contains('timing_token')) return null;
    return 'Something answered at that address, but it is not the MLBFD server (HTTP ${res.statusCode}).';
  } on SocketException {
    return 'Cannot reach $base.\n'
        '• Is the phone on the same Wi-Fi/hotspot as the laptop?\n'
        '• Is the server running on the laptop (start_mlbfd.bat)?\n'
        '• Did the laptop\'s address change? Use the newest one printed by the server.\n'
        '• Windows Firewall must allow port 5000 on the laptop.';
  } on TimeoutException {
    return 'Timed out contacting $base. Check the Wi-Fi/hotspot, the address and the laptop firewall.';
  } on HandshakeException {
    return 'Secure connection failed. Use http:// for the laptop address, https:// only for tunnel links.';
  } catch (e) {
    return 'Could not connect: $e';
  } finally {
    client.close(force: true);
  }
}

class ConnectScreen extends StatefulWidget {
  final Future<void> Function(String baseUrl) onConnected;
  const ConnectScreen({super.key, required this.onConnected});

  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  final _controller = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _connect() async {
    final base = normalizeServerAddress(_controller.text);
    if (base == null) {
      setState(() => _error = 'Enter the laptop address, for example 192.168.43.1:5000');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final problem = await checkServer(base);
    if (!mounted) return;
    if (problem != null) {
      setState(() {
        _busy = false;
        _error = problem;
      });
      return;
    }
    await widget.onConnected(base);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const SizedBox(height: 24),
            const Icon(Icons.shield_outlined, size: 64, color: _brand),
            const SizedBox(height: 12),
            const Text('MLBFD', textAlign: TextAlign.center, style: TextStyle(fontSize: 30, fontWeight: FontWeight.bold)),
            const Text('Fraud-protected virtual payments', textAlign: TextAlign.center, style: TextStyle(color: Colors.white60)),
            const SizedBox(height: 32),
            const Text('Connect to the MLBFD server', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            const Text(
              'On the laptop that runs the server, start_mlbfd.bat prints a line like\n'
              'SHARE ON SAME WI-FI: http://10.157.41.235:5000/user/register\n'
              'Type that address here (the part after http://). This phone must be on the same Wi-Fi or hotspot.',
              style: TextStyle(color: Colors.white70, height: 1.4),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _controller,
              keyboardType: TextInputType.url,
              autocorrect: false,
              enableSuggestions: false,
              textInputAction: TextInputAction.go,
              onSubmitted: (_) => _busy ? null : _connect(),
              decoration: const InputDecoration(
                labelText: 'Server address',
                hintText: '10.157.41.235:5000',
                prefixIcon: Icon(Icons.wifi),
                border: OutlineInputBorder(),
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: Colors.red.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(8)),
                child: Text(_error!, style: const TextStyle(color: Colors.redAccent, height: 1.4)),
              ),
            ],
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _busy ? null : _connect,
              style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 14), backgroundColor: _brand),
              child: _busy
                  ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Connect'),
            ),
          ],
        ),
      ),
    );
  }
}

class WebScreen extends StatefulWidget {
  final String baseUrl;
  final Future<void> Function() onChangeServer;
  const WebScreen({super.key, required this.baseUrl, required this.onChangeServer});

  @override
  State<WebScreen> createState() => _WebScreenState();
}

class _WebScreenState extends State<WebScreen> {
  late final WebViewController _web;
  int _progress = 0;
  bool _failed = false;
  String _failure = '';

  Uri get _serverUri => Uri.parse(widget.baseUrl);

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(_bg)
      ..setNavigationDelegate(NavigationDelegate(
        onNavigationRequest: _onNavigation,
        onPageStarted: (_) => setState(() => _failed = false),
        onProgress: (p) => setState(() => _progress = p),
        onWebResourceError: (e) {
          if (e.isForMainFrame ?? false) {
            setState(() {
              _failed = true;
              _failure = e.description;
            });
          }
        },
      ))
      ..loadRequest(_serverUri.resolve('/user/login'));
  }

  /// Telegram links (the bot link on the signup page) open in the Telegram app; other sites in the browser.
  FutureOr<NavigationDecision> _onNavigation(NavigationRequest req) async {
    final uri = Uri.tryParse(req.url);
    if (uri == null) return NavigationDecision.navigate;
    final sameServer = uri.host == _serverUri.host && uri.port == _serverUri.port;
    if (sameServer || uri.scheme == 'about' || uri.scheme == 'data' || uri.scheme == 'blob') {
      return NavigationDecision.navigate;
    }
    if (req.isMainFrame) {
      try {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      } catch (_) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Could not open ${uri.host}. Is Telegram installed?')));
        }
      }
      return NavigationDecision.prevent;
    }
    return NavigationDecision.navigate; // sub-frames (embedded widgets)
  }

  Future<void> _onBack() async {
    if (await _web.canGoBack()) {
      await _web.goBack();
      return;
    }
    if (!mounted) return;
    final choice = await showDialog<String>(
      context: context,
      builder: (ctx) => SimpleDialog(
        title: const Text('MLBFD'),
        children: [
          SimpleDialogOption(onPressed: () => Navigator.pop(ctx, 'reload'), child: const Text('Reload page')),
          SimpleDialogOption(onPressed: () => Navigator.pop(ctx, 'server'), child: const Text('Change server address')),
          SimpleDialogOption(onPressed: () => Navigator.pop(ctx, 'exit'), child: const Text('Exit app')),
          SimpleDialogOption(onPressed: () => Navigator.pop(ctx, null), child: const Text('Cancel')),
        ],
      ),
    );
    if (choice == 'reload') {
      await _web.reload();
    } else if (choice == 'server') {
      await widget.onChangeServer();
    } else if (choice == 'exit') {
      SystemNavigator.pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _onBack();
      },
      child: Scaffold(
        body: SafeArea(
          child: Stack(
            children: [
              WebViewWidget(controller: _web),
              if (_progress < 100 && !_failed) LinearProgressIndicator(value: _progress / 100, minHeight: 2),
              if (_failed) _ErrorPanel(
                server: widget.baseUrl,
                detail: _failure,
                onRetry: () {
                  setState(() => _failed = false);
                  _web.loadRequest(_serverUri.resolve('/user/login'));
                },
                onChangeServer: widget.onChangeServer,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorPanel extends StatelessWidget {
  final String server;
  final String detail;
  final VoidCallback onRetry;
  final Future<void> Function() onChangeServer;
  const _ErrorPanel({required this.server, required this.detail, required this.onRetry, required this.onChangeServer});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: _bg,
      padding: const EdgeInsets.all(24),
      child: ListView(
        children: [
          const SizedBox(height: 40),
          const Icon(Icons.wifi_off, size: 56, color: Colors.orangeAccent),
          const SizedBox(height: 12),
          const Text('Cannot reach the MLBFD server', textAlign: TextAlign.center, style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Text(server, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white70)),
          const SizedBox(height: 16),
          const Text(
            '• Phone and laptop must be on the same Wi-Fi/hotspot.\n'
            '• The server must be running on the laptop.\n'
            '• If the hotspot restarted, the laptop address may have changed: tap "Change server" and enter the newest one.',
            style: TextStyle(color: Colors.white70, height: 1.5),
          ),
          if (detail.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('Technical detail: $detail', style: const TextStyle(color: Colors.white38, fontSize: 12)),
          ],
          const SizedBox(height: 20),
          FilledButton(onPressed: onRetry, style: FilledButton.styleFrom(backgroundColor: _brand), child: const Text('Try again')),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: onChangeServer, child: const Text('Change server')),
        ],
      ),
    );
  }
}
