import 'package:flutter/material.dart';
import 'config/api_config.dart';
import 'config/app_theme.dart';
import 'screens/registration_screen.dart';
import 'screens/server_url_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Load the saved server URL before any request (it was never loaded before).
  await ApiConfig.init();
  runApp(const MyApp());
}

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  bool _editServer = !ApiConfig.hasBaseUrl;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MLBFD Sender',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      home: _editServer
          ? ServerUrlScreen(onSaved: () => setState(() => _editServer = false))
          : RegistrationScreen(onChangeServer: () => setState(() => _editServer = true)),
    );
  }
}
