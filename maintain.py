#!/usr/bin/env python3
"""Conservative official-source audit; never decrypt, sign, or copy credentials."""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parent
UTC = dt.timezone.utc
VERSION_URL = 'https://api.live.cntv.cn/livestatic/zs/livestatic_config/pcweb/version.json'


class CheckError(Exception):
    def __init__(self, reason, status='unverified'):
        super().__init__(reason)
        self.status = status


def clean_url(url):
    """Do not publish query strings, fragments, or credentials in audit logs."""
    p = urlsplit(url)
    return f'{p.scheme}://{p.hostname or ""}{p.path}'


def check_url(url, domains):
    p = urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        raise CheckError('仅支持无凭据的标准 HTTPS URL')
    if not any(p.hostname == d or (p.hostname or '').endswith('.' + d) for d in domains):
        raise CheckError('目标主机未经过来源审核')
    # Query-bearing media is deliberately excluded, even if a query is benign.
    return url


class Network:
    def __init__(self):
        self.cache = {}

    def get(self, url, domains, limit=4_000_000, cache=False):
        check_url(url, domains)
        if cache and url in self.cache:
            return self.cache[url]
        original = url
        for _ in range(5):
            check_url(url, domains)
            with tempfile.TemporaryDirectory() as tmp:
                body, headers = Path(tmp)/'body', Path(tmp)/'headers'
                args = ['curl', '--silent', '--show-error', '--compressed',
                        '--proto', '=https', '--connect-timeout', '8', '--max-time', '20',
                        '--max-filesize', str(limit), '--dump-header', str(headers),
                        '--output', str(body), '--write-out', '%{http_code}', url]
                proc = subprocess.run(args, capture_output=True, timeout=25)
                if proc.returncode:
                    reasons = {6: 'DNS 解析失败', 28: '连接超时', 60: 'TLS 证书校验失败', 63: '响应超过大小限制'}
                    raise CheckError(reasons.get(proc.returncode, f'网络读取失败（curl {proc.returncode}）'))
                status = int(proc.stdout or b'0')
                hs = headers.read_text(errors='replace')
                if status in (301, 302, 303, 307, 308):
                    loc = re.findall(r'^location:\s*(.+)$', hs, re.I | re.M)
                    if not loc:
                        raise CheckError('重定向未提供目标')
                    url = urljoin(url, loc[-1].strip())
                    continue
                if status != 200:
                    raise CheckError(f'HTTP {status}（不能仅据此判断地域限制）',
                                     'restricted' if status in (401, 403, 451) else 'unverified')
                data = body.read_bytes()
                if len(data) > limit:
                    raise CheckError('响应超过大小限制')
                result = (data, url)
                if cache:
                    self.cache[original] = result
                return result
        raise CheckError('重定向过多')


def evidence(net, url, domains):
    body, final = net.get(url, domains, cache=True)
    return body.decode('utf-8-sig', errors='replace'), {
        'url': clean_url(url), 'final_url': clean_url(final),
        'http_status': 200, 'sha256': hashlib.sha256(body).hexdigest()}


def extract_hls(text, pattern):
    normalized = html.unescape(text.replace('\\/', '/').replace('\\u002F', '/').replace('\\u0026', '&'))
    matches = list(dict.fromkeys(re.findall(pattern, normalized)))
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise CheckError('未发现唯一且与频道匹配的公开 HLS；需要人工复核')
    url = matches[0]
    if urlsplit(url).query or urlsplit(url).fragment:
        raise CheckError('官方地址带查询参数/签名；不复制到公开订阅', 'restricted')
    return url


def parse_manifest(text, base):
    text = text.lstrip('\ufeff').strip()
    if not text.startswith('#EXTM3U'):
        raise CheckError('响应不是 HLS 清单')
    for line in text.splitlines():
        if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')):
            if not re.search(r'(?:^|[:,])METHOD=NONE(?:,|$)', line):
                raise CheckError('HLS 声明加密；本项目不获取密钥或解密', 'restricted')
    if '#EXT-X-ENDLIST' in text:
        raise CheckError('清单已结束，不作为直播')
    if '#EXT-X-BYTERANGE' in text or '#EXT-X-MAP' in text:
        raise CheckError('分段字节范围或 fMP4 初始化段尚未支持，保留未验证')
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    urls = [urljoin(base, x) for x in lines if not x.startswith('#')]
    if not urls:
        raise CheckError('清单没有媒体地址')
    for url in urls:
        if urlsplit(url).query or urlsplit(url).fragment:
            raise CheckError('子清单或分段含查询参数；不尝试绕过', 'restricted')
    master = any(x.startswith('#EXT-X-STREAM-INF:') for x in lines)
    if not master and not any(x.startswith('#EXTINF:') for x in lines):
        raise CheckError('未识别的 HLS 媒体清单')
    # Separate audio renditions need a separate validator, so do not certify them yet.
    if any(x.startswith('#EXT-X-MEDIA:') and 'TYPE=AUDIO' in x for x in lines):
        raise CheckError('独立音轨尚未验证')
    seq = re.search(r'^#EXT-X-MEDIA-SEQUENCE:(\d+)', text, re.M)
    target = re.search(r'^#EXT-X-TARGETDURATION:(\d+)', text, re.M)
    return {'master': master, 'urls': urls, 'sequence': int(seq[1]) if seq else None,
            'target': int(target[1]) if target else 6}


def validate_hls(net, url, domains, sleep=time.sleep):
    original = url
    for _ in range(4):
        check_url(url, domains)
        data, final = net.get(url, domains)
        parsed = parse_manifest(data.decode('utf-8-sig', errors='replace'), final)
        if not parsed['master']:
            url = final
            break
        url = parsed['urls'][0]
    else:
        raise CheckError('主清单嵌套过深')
    # Fetch two full, bounded media segments without Cookies/Referer/token rewriting.
    if len(parsed['urls']) < 2:
        raise CheckError('直播分段不足')
    media = []
    for segment in parsed['urls'][-2:]:
        blob, _ = net.get(segment, domains, limit=16_000_000)
        if len(blob) < 1024 or blob[:1] != b'G':
            raise CheckError('未识别为 MPEG-TS 分段')
        media.append(blob)
    if not shutil.which('ffprobe') or not shutil.which('ffmpeg'):
        raise CheckError('缺少 ffprobe/ffmpeg，无法验证音视频解码')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'sample.ts'
        path.write_bytes(media[0])
        p = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file',
                            '-show_streams', '-of', 'json', str(path)], capture_output=True, timeout=20)
        if p.returncode:
            raise CheckError('媒体解析失败')
        streams = json.loads(p.stdout).get('streams', [])
        kinds = {x.get('codec_type') for x in streams}
        if not {'video', 'audio'} <= kinds:
            raise CheckError('未同时检测到视频和音频')
        video = next(x for x in streams if x.get('codec_type') == 'video')
        if video.get('codec_name') not in ('h264', 'hevc'):
            raise CheckError('视频编码未纳入 APTV 候选兼容范围')
        # Each TS may reset its continuity counters. Do not concatenate raw TS files.
        for blob in media:
            path.write_bytes(blob)
            p = subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-protocol_whitelist', 'file,pipe',
                                '-i', str(path), '-t', '2', '-f', 'null', '-'], capture_output=True, timeout=25)
            if p.returncode:
                raise CheckError('音视频样本解码失败')
    if parsed['target'] > 20:
        raise CheckError('直播刷新间隔过长，未完成推进验证')
    sleep(max(2, parsed['target'] + 2))
    data, final = net.get(url, domains)
    again = parse_manifest(data.decode('utf-8-sig', errors='replace'), final)
    sequence_advanced = (parsed['sequence'] is not None and again['sequence'] is not None
                         and again['sequence'] > parsed['sequence'])
    if not sequence_advanced and again['urls'] == parsed['urls']:
        raise CheckError('清单未推进；可能是停播、缓存或更新较慢')
    return {'url': original, 'video_codec': video.get('codec_name'),
            'width': video.get('width'), 'height': video.get('height'),
            'sample_decoded': True, 'playlist_advanced': True,
            'aptv_playback': '未在 APTV 中人工验证'}


def audit(channel, net, country):
    result = {'id': channel['id'], 'name': channel['name'], 'group': channel['group'],
              'official_page': channel['official_page'], 'status': 'unverified',
              'evidence': [], 'country': country, 'aptv_playback': '未验证'}
    try:
        page, ev = evidence(net, channel['official_page'], channel['domains'])
        result['evidence'].append(ev)
        result['page_accessible'] = True
        mode = channel['resolver']
        if mode == 'cctv_config':
            text, ev = evidence(net, VERSION_URL, channel['domains'])
            result['evidence'].append(ev)
            configs = json.loads(text).get('emconfig', {})
            if configs and all(x.get('encrypted') is True for x in configs.values()):
                raise CheckError('官方 PC 配置标记 encrypted=true；停止于配置层，不代表已证明本频道视频为 DRM', 'restricted')
            raise CheckError('官方配置已变化，需要人工复核频道解析器')
        if mode == 'guard':
            text, ev = evidence(net, channel['evidence_url'], channel['domains'])
            result['evidence'].append(ev)
            if all(x in text for x in channel['markers']):
                raise CheckError(channel['restriction'], 'restricted')
            raise CheckError('既有鉴权证据已变化，需要重新检查官方播放器')
        if mode == 'manual':
            raise CheckError(channel['note'])
        text = page
        if channel.get('evidence_url'):
            text, ev = evidence(net, channel['evidence_url'], channel['domains'])
            result['evidence'].append(ev)
        url = extract_hls(text, channel['url_pattern'])
        result['candidate_url'] = clean_url(url)
        result['media'] = validate_hls(net, url, channel['domains'])
        if country != 'GB':
            raise CheckError('媒体在此出口通过检查，但不是英国出口；不写入英国订阅')
        result.update(status='available', reason='英国出口：清单、分段、音视频解码和直播推进检查通过')
    except CheckError as exc:
        result.update(status=exc.status, reason=str(exc))
    except (ValueError, KeyError, subprocess.TimeoutExpired, OSError) as exc:
        result.update(status='unverified', reason=f'检查异常（{type(exc).__name__}）；未通过验证')
    return result


def m3u(rows, stamp):
    output = ['#EXTM3U', '# Generated: ' + stamp, '# Only verified GB clear live streams; no entries means none passed.']
    for row in rows:
        if row['status'] != 'available' or row.get('country') != 'GB':
            continue
        def safe(value):
            return str(value).replace('"', '').replace('\r', '').replace('\n', '')
        output.extend([f'#EXTINF:-1 tvg-id="{safe(row["id"])}" group-title="{safe(row["group"])}",{safe(row["name"])}',
                       row['media']['url']])
    return '\n'.join(output) + '\n'


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def expire_uk(root, now):
    report = root/'reports/uk.json'
    if not report.exists():
        atomic_write(root/'public/uk.m3u', m3u([], now.isoformat()))
        return
    old = json.loads(report.read_text())
    if dt.datetime.fromisoformat(old['valid_until']) < now:
        atomic_write(root/'public/uk.m3u', m3u([], now.isoformat()))
        atomic_write(root/'public/uk-status.json', json.dumps({
            'state': 'expired', 'reason': '英国检测超过 24 小时，播放条目已清空',
            'last_uk_check': old['checked_at']}, ensure_ascii=False, indent=2) + '\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--scope', choices=['uk', 'cloud'], default='uk')
    p.add_argument('--channels', type=Path, default=ROOT/'channels.json')
    p.add_argument('--output', type=Path, default=ROOT)
    args = p.parse_args()
    now = dt.datetime.now(UTC)
    net = Network()
    country = 'UNKNOWN'
    try:
        data, _ = net.get('https://www.cloudflare.com/cdn-cgi/trace', ['cloudflare.com'])
        found = re.search(rb'^loc=([A-Z]{2})$', data, re.M)
        if found:
            country = found[1].decode()
    except CheckError:
        pass
    channels = json.loads(args.channels.read_text())['channels']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda c: audit(c, net, country), channels))
    stamp = now.isoformat()
    report = {'checked_at': stamp, 'country': country, 'scope': args.scope,
              'geo_method': 'Cloudflare country code only; no IP retained',
              'valid_until': (now + dt.timedelta(hours=24)).isoformat(),
              'counts': {s: sum(x['status'] == s for x in rows) for s in ('available', 'restricted', 'unverified')},
              'channels': rows}
    atomic_write(args.output/f'reports/{args.scope}.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    labels = {'available': '可用（技术检查通过）', 'restricted': '受限', 'unverified': '未验证'}
    lines = ['# 官方直播检查报告', '', f'检测时间（UTC）：{stamp}；网络出口：{country}', '',
             '“可用”指本次英国出口技术检查通过；不是长期保证或第三方播放授权证明。APTV 人工播放另列。', '',
             '| 频道 | 状态 | 结果 |', '| --- | --- | --- |']
    lines += [f'| [{r["name"]}]({r["official_page"]}) | {labels[r["status"]]} | {r["reason"].replace("|", "/")} |' for r in rows]
    atomic_write(args.output/f'reports/{args.scope}.md', '\n'.join(lines) + '\n')
    if args.scope == 'uk' and country == 'GB':
        atomic_write(args.output/'public/uk.m3u', m3u(rows, stamp))
        atomic_write(args.output/'public/uk-status.json', json.dumps({
            'state': 'verified_run', 'country': country, 'checked_at': stamp,
            'valid_until': report['valid_until'], 'counts': report['counts']}, ensure_ascii=False, indent=2) + '\n')
    elif args.scope == 'uk':
        atomic_write(args.output/'public/uk.m3u', m3u([], stamp))
        atomic_write(args.output/'public/uk-status.json', json.dumps({
            'state': 'location_unverified', 'country': country, 'checked_at': stamp}, indent=2) + '\n')
    else:
        expire_uk(args.output, now)
    print(json.dumps({'country': country, **report['counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
