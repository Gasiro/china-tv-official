import datetime as dt
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import maintain as m

BASE = 'https://official.example/live.m3u8'
LIVE = '#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:1\n#EXTINF:2,\na.ts\n#EXTINF:2,\nb.ts\n'


class Tests(unittest.TestCase):
    def test_master_and_relative_segments(self):
        self.assertEqual(m.parse_manifest(LIVE, BASE)['urls'][0], 'https://official.example/a.ts')
        p = m.parse_manifest('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=123\nlow.m3u8', BASE)
        self.assertTrue(p['master'])

    def test_encryption_stops_before_key_fetch(self):
        for method in ('AES-128', 'SAMPLE-AES', 'SAMPLE-AES-CTR'):
            with self.assertRaises(m.CheckError) as ctx:
                m.parse_manifest(LIVE + f'#EXT-X-KEY:METHOD={method},URI="key"', BASE)
            self.assertEqual(ctx.exception.status, 'restricted')

    def test_session_key_is_rejected(self):
        with self.assertRaises(m.CheckError):
            m.parse_manifest('#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="key"\nvideo.m3u8', BASE)

    def test_none_key_is_allowed(self):
        self.assertFalse(m.parse_manifest(LIVE + '#EXT-X-KEY:METHOD=NONE', BASE)['master'])

    def test_html_and_vod_are_not_live(self):
        for text in ('<html>success</html>', LIVE + '#EXT-X-ENDLIST'):
            with self.assertRaises(m.CheckError):
                m.parse_manifest(text, BASE)

    def test_signed_urls_are_not_stripped(self):
        signed = BASE + '?auth_key=secret'
        with self.assertRaises(m.CheckError) as ctx:
            m.extract_hls(signed, r'https://[^"\s]+')
        self.assertEqual(ctx.exception.status, 'restricted')
        with self.assertRaises(m.CheckError):
            m.parse_manifest(LIVE.replace('a.ts', 'a.ts?token=secret'), BASE)

    def test_ambiguous_channels_are_not_guessed(self):
        with self.assertRaises(m.CheckError):
            m.extract_hls(BASE + ' https://official.example/other.m3u8', r'https://\S+')

    def test_host_suffix_cannot_escape_allowlist(self):
        for url in ('http://official.example/x', 'https://official.example.evil.test/x',
                    'https://user:password@official.example/x', 'https://127.0.0.1/x'):
            with self.assertRaises(m.CheckError):
                m.check_url(url, ['official.example'])

    def test_only_gb_available_in_m3u(self):
        rows = [dict(id='x', name='频道', group='组', country=country, status=status,
                     media={'url': BASE}) for country, status in [('GB','available'), ('US','available'), ('GB','restricted')]]
        text = m.m3u(rows, 'now')
        self.assertEqual(text.count('#EXTINF'), 1)
        self.assertIn('频道', text)

    def test_expired_uk_entries_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'reports').mkdir()
            old = {'valid_until':'2020-01-01T00:00:00+00:00', 'checked_at':'2019-12-31T00:00:00+00:00'}
            (root/'reports/uk.json').write_text(json.dumps(old))
            m.expire_uk(root, dt.datetime.now(dt.timezone.utc))
            self.assertNotIn('#EXTINF', (root/'public/uk.m3u').read_text())
            self.assertEqual(json.loads((root/'public/uk-status.json').read_text())['state'], 'expired')

    def test_query_redaction(self):
        self.assertNotIn('secret', m.clean_url(BASE + '?auth_key=secret'))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'media tools not installed')
    def test_decode_and_freshness_with_real_generated_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=25',
                '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-g', '50', '-c:a', 'aac', '-f', 'segment', '-segment_time', '2', str(Path(tmp)/'%d.ts')],
                capture_output=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            blobs = [(Path(tmp)/f'{i}.ts').read_bytes() for i in range(2)]
            class FakeNet:
                calls = 0
                advancing = True
                def get(self, url, domains, **kwargs):
                    if url.endswith('.ts'):
                        return blobs[0 if url.endswith('a.ts') else 1], url
                    self.calls += 1
                    text = LIVE.replace('SEQUENCE:1', 'SEQUENCE:2') if self.calls > 1 and self.advancing else LIVE
                    return text.encode(), url
            net = FakeNet()
            result = m.validate_hls(net, BASE, ['official.example'], sleep=lambda _: None)
            self.assertTrue(result['sample_decoded'])
            net = FakeNet()
            net.advancing = False
            with self.assertRaisesRegex(m.CheckError, '未推进'):
                m.validate_hls(net, BASE, ['official.example'], sleep=lambda _: None)


if __name__ == '__main__':
    unittest.main()
