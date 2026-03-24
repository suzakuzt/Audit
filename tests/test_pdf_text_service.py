from services.pdf_text_service import OCRRunConfig, extract_pdf_text


def test_extract_pdf_text_prefers_remote_paddle_ocr_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service._extract_with_pdfplumber', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_pypdf', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_api_token', 'token-123')
    monkeypatch.setattr('services.pdf_text_service._extract_with_paddle_remote_ocr', lambda content: ('Contract No: R 251/2025\nExporter: BFC-USA LLC\nClient: Example Buyer', 1, {'ocr_model': 'paddleocr-vl-remote', 'ocr_api_called': True}))

    result = extract_pdf_text('scan.pdf', b'%PDF', OCRRunConfig(enabled=True, engine_preference='paddle_only'))

    assert result.is_text_valid is True
    assert result.text == 'Contract No: R 251/2025\nExporter: BFC-USA LLC\nClient: Example Buyer'
    assert result.metadata.get('ocr_engine') == 'paddleocr'
    assert result.metadata.get('source_kind') == 'scan_ocr'
    assert result.extraction_method.endswith('paddleocr')
    assert result.metadata.get('ocr_api_called') is True


def test_extract_pdf_text_requires_remote_paddle_configuration(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service._extract_with_pdfplumber', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_pypdf', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_api_token', '')

    result = extract_pdf_text('scan.pdf', b'%PDF', OCRRunConfig(enabled=True, engine_preference='paddle_only'))

    assert result.metadata.get('ocr_status') == 'failed'
    assert any('Remote PaddleOCR is required' in warning for warning in result.warnings)

def test_extract_pdf_text_uses_remote_paddle_api_when_configured(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service._extract_with_pdfplumber', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_pypdf', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_api_token', 'token-123')

    def fake_remote(content):
        return (
            '# Parsed\n\nContract No: R 251/2025\nExporter: BFC-USA LLC',
            1,
            {
                'ocr_model': 'paddleocr-vl-remote',
                'ocr_transport': 'http',
                'ocr_api_called': True,
            },
        )

    monkeypatch.setattr('services.pdf_text_service._extract_with_paddle_remote_ocr', fake_remote)

    result = extract_pdf_text('scan.pdf', b'%PDF', OCRRunConfig(enabled=True, engine_preference='paddle_only'))

    assert result.is_text_valid is True
    assert result.metadata.get('ocr_engine') == 'paddleocr'
    assert result.metadata.get('ocr_model') == 'paddleocr-vl-remote'
    assert result.metadata.get('ocr_transport') == 'http'
    assert result.extraction_method.endswith('paddleocr')
    assert result.metadata.get('ocr_api_called') is True


def test_extract_pdf_text_remote_paddle_exposes_preview_images(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service._extract_with_pdfplumber', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_pypdf', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_api_token', 'token-123')

    def fake_remote(content):
        return (
            '# Parsed\n\nContract No: R 251/2025',
            1,
            {
                'ocr_model': 'paddleocr-vl-remote',
                'ocr_transport': 'http',
                'ocr_preview_images': [
                    {
                        'page_number': 1,
                        'image_data_url': 'https://example.com/page-1.jpg',
                        'page_width': 0,
                        'page_height': 0,
                        'words': [],
                    }
                ],
            },
        )

    monkeypatch.setattr('services.pdf_text_service._extract_with_paddle_remote_ocr', fake_remote)

    result = extract_pdf_text('scan.pdf', b'%PDF', OCRRunConfig(enabled=True, engine_preference='paddle_only'))

    assert result.metadata.get('ocr_preview_images')[0]['image_data_url'] == 'https://example.com/page-1.jpg'


def test_extract_with_paddle_remote_ocr_exposes_http_metadata(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_api_token', 'token-123')
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_job_url', 'https://example.com/api/v2/ocr/jobs')

    class FakeSubmitResponse:
        status_code = 200
        text = '{"data":{"jobId":"job-123"}}'
        headers = {'x-request-id': 'req-123'}

        @staticmethod
        def json():
            return {'data': {'jobId': 'job-123'}}

    class FakeQueryResponse:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return {
                'data': {
                    'state': 'done',
                    'extractProgress': {
                        'totalPages': 1,
                        'extractedPages': 1,
                        'startTime': '2026-03-24 14:44:32',
                        'endTime': '2026-03-24 14:44:38',
                    },
                    'resultUrl': {'jsonUrl': 'https://example.com/result.jsonl'},
                }
            }

        def raise_for_status(self):
            return None

    class FakeJsonlResponse:
        status_code = 200
        text = '{"result":{"layoutParsingResults":[{"markdown":{"text":"# Parsed text","images":{}},"outputImages":{},"prunedResult":{"width":100,"height":200,"parsing_res_list":[]}}]}}'

        def raise_for_status(self):
            return None

    monkeypatch.setattr('services.pdf_text_service.requests.post', lambda *args, **kwargs: FakeSubmitResponse())
    monkeypatch.setattr('services.pdf_text_service.requests.get', lambda url, **kwargs: FakeJsonlResponse() if url.endswith('result.jsonl') else FakeQueryResponse())
    monkeypatch.setattr('services.pdf_text_service.time.sleep', lambda seconds: None)

    from services.pdf_text_service import _extract_with_paddle_remote_ocr

    _, page_count, metadata = _extract_with_paddle_remote_ocr(b'%PDF-1.4')

    assert page_count == 1
    assert metadata['ocr_api_called'] is True
    assert metadata['ocr_api_status_code'] == 200
    assert metadata['ocr_api_request_id'] == 'req-123'
    assert metadata['ocr_api_log_id'] == 'job-123'
    assert metadata['ocr_api_job_id'] == 'job-123'
    assert metadata['ocr_api_url'] == 'https://example.com/api/v2/ocr/jobs'
    assert metadata['ocr_api_mode'] == 'aistudio_async_jobs'

def test_extract_pdf_text_forces_remote_ocr_for_all_documents_when_configured(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service._extract_with_pdfplumber', lambda content: ('Native PDF text that is already long enough for direct extraction.', 1, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_pypdf', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service.settings.force_remote_ocr_for_all_documents', True)
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_api_token', 'token-123')

    def fake_remote(content):
        return (
            '# Remote Parsed\n\nContract No: R 251/2025\nExporter: BFC-USA LLC',
            1,
            {
                'ocr_model': 'paddleocr-vl-remote',
                'ocr_transport': 'http',
                'ocr_api_called': True,
            },
        )

    monkeypatch.setattr('services.pdf_text_service._extract_with_paddle_remote_ocr', fake_remote)

    result = extract_pdf_text('digital.pdf', b'%PDF', OCRRunConfig(enabled=False, force_ocr=False, engine_preference='paddle_only'))

    assert result.metadata.get('remote_ocr_forced') is True
    assert result.metadata.get('ocr_status') == 'applied'
    assert result.metadata.get('ocr_engine') == 'paddleocr'
    assert result.metadata.get('ocr_api_called') is True
    assert 'Native PDF text that is already long enough for direct extraction.' in result.text
    assert '# Remote Parsed' in result.text
