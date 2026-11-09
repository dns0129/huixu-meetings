import io
import json
import os
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image

import image_bridge


def sample_png():
    output = io.BytesIO()
    Image.new('RGB', (12, 20), 'navy').save(output, 'PNG')
    return output.getvalue()


class ImageProviderTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='meeting-image-test-')
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.meeting = {'title': '示例交流会', 'data': {'design': {
            'poster': {'width': 210, 'height': 297},
            'banner': {'width': 800, 'height': 2000},
        }}}

    def test_credentials_are_isolated_private_and_never_returned_by_status(self):
        image_bridge.save(self.data, 1, 'fast', {'api_key': 'fast-private-key'})
        image_bridge.save(self.data, 1, 'advanced', {'api_key': 'qwen-private-key', 'workspace_id': 'llm-test-1'})
        image_bridge.save(self.data, 2, 'fast', {'api_key': 'other-private-key'})
        visible = json.dumps(image_bridge.status(self.data, 1))
        self.assertNotIn('private-key', visible)
        self.assertTrue(image_bridge.status(self.data, 1)['advanced']['configured'])
        self.assertFalse(image_bridge.status(self.data, 2)['advanced']['configured'])
        self.assertEqual(os.stat(self.data / 'image-providers' / '1.json').st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.data / 'image-providers').st_mode & 0o777, 0o700)
        image_bridge.save(self.data, 1, 'advanced', {'api_key': '', 'workspace_id': 'llm-test-2'})
        self.assertEqual(image_bridge.credentials(self.data, 1, 'advanced')['api_key'], 'qwen-private-key')
        image_bridge.remove(self.data, 1, 'fast')
        self.assertFalse(image_bridge.status(self.data, 1)['fast']['configured'])
        self.assertTrue(image_bridge.status(self.data, 2)['fast']['configured'])

    def test_bad_workspace_is_rejected_and_does_not_change_saved_key(self):
        image_bridge.save(self.data, 1, 'advanced', {'api_key': 'qwen-private-key', 'workspace_id': 'llm-safe'})
        with self.assertRaises(ValueError):
            image_bridge.save(self.data, 1, 'advanced', {'api_key': 'new-private-key', 'workspace_id': 'evil.example.com'})
        self.assertEqual(image_bridge.credentials(self.data, 1, 'advanced')['api_key'], 'qwen-private-key')

    def test_fast_uses_seedream_api_once_and_preserves_portrait_ratio(self):
        image = sample_png()
        result_url = 'https://ark-content-generation-v2-cn-beijing.tos-cn-beijing.volces.com/test-image.png?signature=fake'
        response = json.dumps({'data': [{'url': result_url}]}).encode()
        with patch.object(image_bridge, '_request', side_effect=[response, (image, 200, {'content-length': str(len(image))})]) as request:
            result = image_bridge.generate(self.meeting, 'fast', {'api_key': 'fast-private-key'}, {'kind': 'banner', 'prompt': '蓝色渐变'})
        self.assertEqual(result, image)
        self.assertEqual(request.call_count, 2)
        sent = request.call_args_list[0].args[0]
        payload = json.loads(sent.data)
        self.assertEqual(sent.full_url, image_bridge.ARK_URL)
        self.assertEqual(sent.get_header('Authorization'), 'Bearer fast-private-key')
        self.assertEqual(payload['model'], 'doubao-seedream-5-0-flash-260915')
        self.assertEqual(payload['response_format'], 'url')
        self.assertIsNone(request.call_args_list[1].args[0].get_header('Authorization'))
        width, height = map(int, payload['size'].split('x'))
        self.assertGreater(height, width)
        self.assertAlmostEqual(width / height, 0.4, delta=0.02)
        self.assertGreaterEqual(width * height, 921600)

    def test_advanced_calls_workspace_specific_qwen_endpoint_and_downloads_image(self):
        image = sample_png()
        response = {'data': [{'url': 'https://dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com/image.png?token=fake'}]}
        with patch.object(image_bridge, '_request', side_effect=[json.dumps(response).encode(), (image, 200, {'content-length': str(len(image))})]) as request:
            result = image_bridge.generate(self.meeting, 'advanced', {'api_key': 'qwen-private-key', 'workspace_id': 'llm-test-1'}, {'kind': 'poster'})
        self.assertEqual(result, image)
        self.assertEqual(request.call_count, 2)
        generation = request.call_args_list[0].args[0]
        download = request.call_args_list[1].args[0]
        self.assertEqual(generation.full_url, 'https://llm-test-1.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/images/generations')
        self.assertEqual(json.loads(generation.data)['model'], 'qwen-image-3.0-pro')
        self.assertEqual(generation.get_header('Authorization'), 'Bearer qwen-private-key')
        self.assertIsNone(download.get_header('Authorization'))

    def test_advanced_retries_incomplete_download_without_regenerating(self):
        image = sample_png()
        response = {'data': [{'url': 'https://dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com/image.png?token=fake'}]}
        with patch.object(image_bridge, '_request', side_effect=[json.dumps(response).encode(), (b'incomplete', 200, {'content-length': '10'}), (image, 200, {'content-length': str(len(image))})]) as request:
            result = image_bridge.generate(self.meeting, 'advanced', {'api_key': 'qwen-private-key', 'workspace_id': 'llm-test-1'}, {'kind': 'poster'})
        self.assertEqual(result, image)
        methods = [call.args[0].get_method() for call in request.call_args_list]
        self.assertEqual(methods, ['POST', 'GET', 'GET'])

    def test_advanced_rejects_persistently_invalid_image_download(self):
        response = {'data': [{'url': 'https://dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com/image.png?token=fake'}]}
        with patch.object(image_bridge, '_request', side_effect=[json.dumps(response).encode(), (b'incomplete', 200, {'content-length': '10'}), (b'incomplete', 200, {'content-length': '10'})]) as request:
            with self.assertRaises(ValueError) as raised:
                image_bridge.generate(self.meeting, 'advanced', {'api_key': 'qwen-private-key', 'workspace_id': 'llm-test-1'}, {})
        self.assertIn('图片下载不完整', str(raised.exception))
        self.assertEqual(request.call_count, 3)

    def test_advanced_resumes_truncated_download_using_http_ranges(self):
        image = sample_png()
        total = len(image)
        response = {'data': [{'url': 'https://dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com/image.png?token=fake'}]}
        segments = [json.dumps(response).encode(),
                    (image[:20], 200, {'content-length': str(total)}),
                    (image[20:50], 206, {'content-length': str(total-20), 'content-range': f'bytes 20-{total-1}/{total}'}),
                    (image[50:], 206, {'content-length': str(total-50), 'content-range': f'bytes 50-{total-1}/{total}'})]
        with patch.object(image_bridge, '_request', side_effect=segments) as request:
            result = image_bridge.generate(self.meeting, 'advanced', {'api_key': 'qwen-private-key', 'workspace_id': 'llm-test-1'}, {})
        self.assertEqual(result, image)
        self.assertEqual([call.args[0].get_method() for call in request.call_args_list], ['POST', 'GET', 'GET', 'GET'])
        self.assertEqual(request.call_args_list[2].args[0].get_header('Range'), 'bytes=20-')
        self.assertEqual(request.call_args_list[3].args[0].get_header('Range'), 'bytes=50-')

    def test_rejects_non_provider_download_url_without_second_request(self):
        result = json.dumps({'data': [{'url': 'http://127.0.0.1:8765/api/session'}]}).encode()
        with patch.object(image_bridge, '_request', return_value=result) as request:
            with self.assertRaises(ValueError):
                image_bridge.generate(self.meeting, 'advanced', {'api_key': 'qwen-private-key', 'workspace_id': 'llm-safe'}, {})
        self.assertEqual(request.call_count, 1)

    def test_fast_rejects_download_from_untrusted_domain(self):
        result = json.dumps({'data': [{'url': 'https://example.com/private.png'}]}).encode()
        with patch.object(image_bridge, '_request', return_value=result) as request:
            with self.assertRaises(ValueError):
                image_bridge.generate(self.meeting, 'fast', {'api_key': 'fast-private-key'}, {})
        self.assertEqual(request.call_count, 1)

    def test_truncated_model_response_reports_failure_without_retrying(self):
        class Response:
            status = 200
            headers = {'content-length': '100'}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b'{}'
        class Opener:
            def open(self, request, timeout): return Response()
        with patch.object(image_bridge, 'build_opener', return_value=Opener()) as build:
            with self.assertRaises(ValueError) as raised:
                image_bridge._request(image_bridge.Request('https://example.com', data=b'{}'), 1000)
        self.assertIn('响应不完整', str(raised.exception))
        self.assertEqual(build.call_count, 1)

    def test_auth_error_does_not_echo_provider_response_or_key(self):
        class FailingOpener:
            def open(self, request, timeout):
                raise HTTPError(request.full_url, 401, 'private-token', {}, None)
        with patch.object(image_bridge, 'build_opener', return_value=FailingOpener()):
            with self.assertRaises(ValueError) as raised:
                image_bridge._request(image_bridge.Request('https://example.com'), 100)
        self.assertIn('认证失败', str(raised.exception))
        self.assertNotIn('private-token', str(raised.exception))

    def test_unopened_seedream_model_reports_required_activation(self):
        class FailingOpener:
            def open(self, request, timeout):
                body = io.BytesIO(b'{"error":{"code":"ModelNotOpen","message":"do not echo this"}}')
                raise HTTPError(request.full_url, 404, 'Not Found', {}, body)
        with patch.object(image_bridge, 'build_opener', return_value=FailingOpener()):
            with self.assertRaises(ValueError) as raised:
                image_bridge._request(image_bridge.Request(image_bridge.ARK_URL), 100)
        self.assertIn('模型尚未开通', str(raised.exception))
        self.assertNotIn('do not echo', str(raised.exception))

    def test_provider_https_uses_certificate_bundle_and_verifies_hostname(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b'{}'
        class Opener:
            def open(self, request, timeout): return Response()
        with patch.object(image_bridge, 'build_opener', return_value=Opener()) as build:
            self.assertEqual(image_bridge._request(image_bridge.Request('https://example.com'), 100), b'{}')
        handler = build.call_args.args[1]
        self.assertEqual(handler._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(handler._context.check_hostname)
        self.assertTrue(handler._context.get_ca_certs())


if __name__ == '__main__':
    unittest.main()
