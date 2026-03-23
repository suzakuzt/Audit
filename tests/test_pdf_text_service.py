from services.pdf_text_service import OCRRunConfig, _ocr_engines_in_order, extract_pdf_text


def test_ocr_engine_order_defaults_to_paddle_only() -> None:
    assert _ocr_engines_in_order('') == ['paddleocr']
    assert _ocr_engines_in_order('paddle_only') == ['paddleocr']
    assert _ocr_engines_in_order('paddle_first') == ['paddleocr', 'llm_ocr']


def test_extract_pdf_text_prefers_paddle_ocr_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service._extract_with_pdfplumber', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_pypdf', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_paddle_ocr', lambda content, ocr_config: ('Contract No: R 251/2025\nExporter: BFC-USA LLC\nClient: Example Buyer', 1, {'ocr_model': 'paddleocr'}))
    monkeypatch.setattr('services.pdf_text_service._extract_with_llm_ocr', lambda content, ocr_config: ('', 0, {'ocr_model': 'llm_ocr'}))

    result = extract_pdf_text('scan.pdf', b'%PDF', OCRRunConfig(enabled=True, engine_preference='paddle_only'))

    assert result.is_text_valid is True
    assert result.text == 'Contract No: R 251/2025\nExporter: BFC-USA LLC\nClient: Example Buyer'
    assert result.metadata.get('ocr_engine') == 'paddleocr'
    assert result.metadata.get('source_kind') == 'scan_ocr'
    assert result.extraction_method.endswith('paddleocr')


def test_extract_pdf_text_falls_back_to_llm_ocr_when_paddle_fails(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service._extract_with_pdfplumber', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_pypdf', lambda content: ('', 0, None))

    def raise_paddle(content, ocr_config):
        raise RuntimeError('paddle missing model')

    monkeypatch.setattr('services.pdf_text_service._extract_with_paddle_ocr', raise_paddle)
    monkeypatch.setattr('services.pdf_text_service._extract_with_llm_ocr', lambda content, ocr_config: ('OCR TEXT\nContract No: R 251/2025\nExporter: BFC-USA LLC', 1, {'ocr_model': 'deepseek-chat'}))

    result = extract_pdf_text('scan.pdf', b'%PDF', OCRRunConfig(enabled=True, engine_preference='paddle_first'))

    assert result.is_text_valid is True
    assert result.text == 'OCR TEXT\nContract No: R 251/2025\nExporter: BFC-USA LLC'
    assert result.metadata.get('ocr_engine') == 'llm_ocr'
    assert result.extraction_method.endswith('llm_ocr')

def test_extract_pdf_text_uses_remote_paddle_api_when_configured(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service._extract_with_pdfplumber', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_pypdf', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_api_url', 'https://example.com/layout-parsing')
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_api_token', 'token-123')

    def fake_remote(content):
        return ('# Parsed\n\nContract No: R 251/2025\nExporter: BFC-USA LLC', 1, {'ocr_model': 'paddleocr-vl-remote', 'ocr_transport': 'http'})

    monkeypatch.setattr('services.pdf_text_service._extract_with_paddle_remote_ocr', fake_remote)

    result = extract_pdf_text('scan.pdf', b'%PDF', OCRRunConfig(enabled=True, engine_preference='paddle_only'))

    assert result.is_text_valid is True
    assert result.metadata.get('ocr_engine') == 'paddleocr'
    assert result.metadata.get('ocr_model') == 'paddleocr-vl-remote'
    assert result.metadata.get('ocr_transport') == 'http'
    assert result.extraction_method.endswith('paddleocr')


def test_extract_pdf_text_remote_paddle_exposes_preview_images(monkeypatch) -> None:
    monkeypatch.setattr('services.pdf_text_service._extract_with_pdfplumber', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service._extract_with_pypdf', lambda content: ('', 0, None))
    monkeypatch.setattr('services.pdf_text_service.settings.paddle_ocr_api_url', 'https://example.com/layout-parsing')
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
