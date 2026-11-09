"""Account-scoped connections to the two image generation providers."""
from __future__ import annotations

import io
import json
import math
import os
import re
import socket
import ssl
import tempfile
import threading
import time
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

import certifi
from PIL import Image, UnidentifiedImageError
from materials import material_dimensions


MODELS = {
    'fast': 'doubao-seedream-5-0-flash-260915',
    'advanced': 'qwen-image-3.0-pro',
}
ARK_URL = 'https://ark.cn-beijing.volces.com/api/v3/images/generations'
_LOCK = threading.Lock()
_MAX_JSON = 48 * 1024 * 1024
_MAX_IMAGE = 30 * 1024 * 1024


def _path(data, uid):
    return Path(data) / 'image-providers' / f'{int(uid)}.json'


def _read(data, uid):
    try:
        value = json.loads(_path(data, uid).read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError('无法读取生图服务配置，请重新保存。') from None


def status(data, uid):
    config = _read(data, uid)
    fast = config.get('fast') if isinstance(config.get('fast'), dict) else {}
    advanced = config.get('advanced') if isinstance(config.get('advanced'), dict) else {}
    return {
        'fast': {'configured': bool(fast.get('api_key')), 'model': MODELS['fast']},
        'advanced': {
            'configured': bool(advanced.get('api_key') and advanced.get('workspace_id')),
            'model': MODELS['advanced'],
            'workspace_id': advanced.get('workspace_id', ''),
        },
    }


def _write(data, uid, config):
    path = _path(data, uid)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(prefix='.image-provider-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(config, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(data, uid, tier, values):
    if not isinstance(tier, str) or tier not in MODELS or not isinstance(values, dict):
        raise ValueError('生图服务配置不正确。')
    with _LOCK:
        config = _read(data, uid)
        old = config.get(tier) if isinstance(config.get(tier), dict) else {}
        key = str(values.get('api_key', '') or '').strip() or old.get('api_key', '')
        if not re.fullmatch(r'[\x21-\x7e]{8,512}', key):
            raise ValueError('请输入有效的 API Key，密钥不能包含空格。')
        entry = {'api_key': key}
        if tier == 'advanced':
            workspace = str(values.get('workspace_id', '') or '').strip()
            if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', workspace):
                raise ValueError('请输入有效的百炼业务空间 ID，例如 llm-xxxxxxxx。')
            entry['workspace_id'] = workspace.lower()
        config[tier] = entry
        _write(data, uid, config)
    return status(data, uid)


def remove(data, uid, tier):
    if not isinstance(tier, str) or tier not in MODELS:
        raise ValueError('不支持的生图服务。')
    with _LOCK:
        config = _read(data, uid)
        config.pop(tier, None)
        _write(data, uid, config)
    return status(data, uid)


def credentials(data, uid, tier):
    if not isinstance(tier, str) or tier not in MODELS:
        raise ValueError('请选择有效的生图档位。')
    config = _read(data, uid)
    entry = config.get(tier)
    if not isinstance(entry, dict) or not entry.get('api_key'):
        raise ValueError('请先在 AI 连接设置中配置该档位的 API Key。')
    if tier == 'advanced' and not entry.get('workspace_id'):
        raise ValueError('请先在 AI 连接设置中配置百炼业务空间 ID。')
    return dict(entry)


def _dimensions(meeting, kind):
    """Generate approximately 1-megapixel images in the material's aspect ratio."""
    try:
        width,height=material_dimensions(meeting.get('data', {}),kind)
        ratio=width/height
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError()
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 210 / 297
    ratio = min(4, max(0.25, ratio))
    width = min(2048, max(512, round(math.sqrt(1024 * 1024 * ratio) / 16) * 16))
    height = min(2048, max(512, round(math.sqrt(1024 * 1024 / ratio) / 16) * 16))
    return f'{width}x{height}'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(request, maximum, timeout=600, *, include_response=False):
    try:
        # Framework Python on macOS may have no system CA bundle.  Use the
        # maintained certificate bundle while retaining normal TLS verification.
        context = ssl.create_default_context(cafile=certifi.where())
        with build_opener(_NoRedirect, HTTPSHandler(context=context)).open(request, timeout=timeout) as response:
            try:
                content = response.read(maximum + 1)
            except IncompleteRead as exc:
                if not include_response:
                    raise ValueError('生图服务响应不完整，本次请求可能已产生费用；未自动重试。') from None
                content = exc.partial
            if include_response:
                status = response.status
                headers = {name: response.headers.get(name) for name in ('content-length', 'content-range')}
            else:
                headers = getattr(response, 'headers', None)
                length = headers.get('content-length') if headers else None
                if isinstance(length, str) and length.isdigit() and len(content) < int(length):
                    raise ValueError('生图服务响应不完整，本次请求可能已产生费用；未自动重试。')
        if len(content) > maximum:
            raise ValueError('生图服务返回的数据过大，本次请求可能已产生费用。')
        return (content, status, headers) if include_response else content
    except HTTPError as exc:
        if exc.code == 404 and request.full_url == ARK_URL:
            try:
                provider_error = json.loads(exc.read(65536)).get('error', {})
            except (OSError, ValueError, AttributeError):
                provider_error = {}
            if isinstance(provider_error, dict) and provider_error.get('code') == 'ModelNotOpen':
                raise ValueError('火山方舟模型尚未开通，请先完成实名认证并开通 Seedream 5.0 Flash。') from None
        if exc.code == 401:
            raise ValueError('生图服务认证失败，请检查该档位的 API Key。') from None
        if exc.code == 403:
            raise ValueError('生图服务拒绝请求，请检查模型权限、地域和账户状态。') from None
        if exc.code == 429:
            raise ValueError('生图服务额度或请求频率受限，请检查账户。') from None
        raise ValueError(f'生图服务请求失败（HTTP {exc.code}），请检查模型权限和配置。') from None
    except (TimeoutError, socket.timeout):
        raise ValueError('生图请求超时，本次请求可能已产生费用；未自动重试。') from None
    except (URLError, OSError):
        raise ValueError('无法连接生图服务，请检查网络；本次请求可能已产生费用。') from None


def _download_image(url, tier):
    provider = '百炼' if tier == 'advanced' else '火山方舟'
    if not isinstance(url, str):
        raise ValueError(f'{provider}未返回可用图片，本次请求可能已产生费用。')
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        trusted = (host.endswith('.aliyuncs.com') if tier == 'advanced' else host in {
            'ark-content-generation-v2-cn-beijing.tos-cn-beijing.volces.com',
            'ark-acg-cn-beijing.tos-cn-beijing.volces.com',
        })
        valid = (parsed.scheme == 'https' and trusted
                 and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f'{provider}返回了无法识别的图片地址，本次请求可能已产生费用。')
    # Only download the already-generated image again: never repeat the model request.
    # Some networks end a response early without reporting an error. Resume from
    # the last received byte and verify the range before appending each segment.
    content = bytearray()
    total = None
    invalid_complete = 0
    empty_attempts = 0
    deadline = time.monotonic() + 180
    for _ in range(24):
        if time.monotonic() >= deadline:
            break
        offset = len(content)
        headers = {'Accept': 'image/*'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        try:
            chunk, status, response_headers = _request(
                Request(url, headers=headers), _MAX_IMAGE,
                timeout=max(1, min(30, deadline - time.monotonic())), include_response=True)
        except ValueError as exc:
            if str(exc).startswith(('无法连接生图服务', '生图请求超时')):
                empty_attempts += 1
                if empty_attempts < 3:
                    continue
            raise
        if status == 206:
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response_headers.get('content-range') or '')
            if not match:
                break
            start, end, reported_total = map(int, match.groups())
            if (start != offset or end < start or end >= reported_total or reported_total > _MAX_IMAGE
                    or (total is not None and total != reported_total) or len(chunk) > end - start + 1):
                break
            total = reported_total
        elif status == 200:
            # Some hosts ignore Range. Treat their response as a fresh download.
            if offset:
                content.clear()
            length = response_headers.get('content-length')
            total = int(length) if isinstance(length, str) and length.isdigit() else None
            if total is not None and total > _MAX_IMAGE:
                break
        else:
            break
        if not chunk:
            empty_attempts += 1
            if empty_attempts >= 3:
                break
            continue
        empty_attempts = 0
        content.extend(chunk)
        if len(content) > _MAX_IMAGE or (total is not None and len(content) > total):
            break
        if total is not None and len(content) < total:
            continue
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.load()
            return bytes(content)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            invalid_complete += 1
            if invalid_complete >= 2:
                break
            content.clear()
            total = None
    raise ValueError(f'{provider}图片下载不完整，请检查网络；本次生图可能已产生费用。')


def _download_aliyun(url):
    return _download_image(url, 'advanced')


def generate(meeting, tier, entry, extra):
    kind = extra.get('kind') or 'poster'
    if kind not in ('poster', 'banner', 'card'):
        raise ValueError('该物料暂不支持生成背景。')
    idea = str(extra.get('prompt', '') or '').strip()[:1500] or '现代商务会议，专业、简洁、有层次的背景纹理与构图'
    title = str(meeting.get('title', '会议'))[:200]
    width,height=material_dimensions(meeting.get('data', {}),kind)
    prompt = (f'为会议物料生成背景图。会议主题：{title}。画面宽高比：{width:g}:{height:g}。视觉要求：{idea}。'
              '背景铺满画面，重要内容远离边缘，留出宽阔清晰的文字区域，不要绘制文字、数字、二维码或 Logo。')
    size = _dimensions(meeting, kind)
    if tier == 'fast':
        url = ARK_URL
        body = {'model': MODELS[tier], 'prompt': prompt, 'size': size,
                'response_format': 'url', 'output_format': 'png'}
    elif tier == 'advanced':
        workspace = entry.get('workspace_id', '')
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', workspace):
            raise ValueError('百炼业务空间 ID 不正确，请重新配置。')
        url = f'https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/images/generations'
        body = {'model': MODELS[tier], 'prompt': prompt, 'size': size, 'n': 1}
    else:
        raise ValueError('请选择有效的生图档位。')
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + entry['api_key']},
                      method='POST')
    try:
        response = json.loads(_request(request, _MAX_JSON))
        item = response['data'][0]
        if tier == 'fast':
            return _download_image(item['url'], 'fast')
        return _download_aliyun(item['url'])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ValueError('生图服务未返回有效图片，本次请求可能已产生费用。') from None
