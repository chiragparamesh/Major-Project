import 'package:flutter_test/flutter_test.dart';
import 'package:mlbfd_app/main.dart';

void main() {
  group('normalizeServerAddress', () {
    test('adds http and the default port to a bare IP', () {
      expect(normalizeServerAddress('10.157.41.235'), 'http://10.157.41.235:5000');
    });
    test('keeps an explicit port', () {
      expect(normalizeServerAddress('192.168.43.1:5050'), 'http://192.168.43.1:5050');
    });
    test('accepts the full link printed by the server and drops the path', () {
      expect(normalizeServerAddress('http://10.157.41.235:5000/user/register'), 'http://10.157.41.235:5000');
    });
    test('tunnel https links keep https and get no port', () {
      expect(normalizeServerAddress('https://abc-def.trycloudflare.com/'), 'https://abc-def.trycloudflare.com');
    });
    test('trims spaces', () {
      expect(normalizeServerAddress('  10.0.0.5:5000  '), 'http://10.0.0.5:5000');
    });
    test('rejects empty or unusable input', () {
      expect(normalizeServerAddress(''), isNull);
      expect(normalizeServerAddress('   '), isNull);
      expect(normalizeServerAddress('ftp://10.0.0.5'), isNull);
    });
  });
}
