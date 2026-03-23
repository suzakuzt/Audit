from services.prompt_optimizer_service import build_prompt_fragments, run_prompt_test


def test_prompt_learning_ui_config(client) -> None:
    response = client.get('/api/v1/prompt-learning/ui-config')

    assert response.status_code == 200
    payload = response.json()
    assert 'prompt_texts' in payload
    assert 'fragments' in payload
    assert 'versions' in payload
    assert 'history' in payload
    assert 'evolution' in payload
    assert 'rule_pool' in payload['evolution']
    assert payload['fragments'][0]['id']


def test_prompt_learning_analyze_and_version_flow(client) -> None:
    fragments = build_prompt_fragments({'base': 'base prompt', 'classify': 'classify prompt', 'field_understanding': 'field prompt'})
    analysis = client.post('/api/v1/prompt-learning/analyze', json={
        'documents': [],
        'prompt_context': {'base': 'base prompt'},
        'fragments': fragments,
        'selected_fragment_ids': [item['id'] for item in fragments if item['enabled']],
        'test_case_ids': ['tc_contract_factory'],
        'document_type': '合同',
        'version_id': 'prompt-opt-v1',
    })
    assert analysis.status_code == 200
    analysis_payload = analysis.json()
    assert analysis_payload['evaluation_report']['metrics']['fieldRecall'] >= 0
    assert analysis_payload['optimization_suggestions']
    assert analysis_payload['candidate_patch']['operations']

    save = client.post('/api/v1/prompt-learning/save-version', json={
        'fragments': analysis_payload['candidate_fragments'],
        'base_version_id': 'prompt-opt-v1',
        'changed_fragments': analysis_payload['candidate_version']['changedFragments'],
        'change_summary': analysis_payload['candidate_patch']['summary'],
        'test_summary': analysis_payload['candidate_version']['testSummary'],
        'created_by': 'tester',
        'status': 'candidate',
    })
    assert save.status_code == 200
    save_payload = save.json()
    assert save_payload['saved']['versionId'].startswith('prompt-opt-v')
    assert save_payload['versions']

    rollback = client.post('/api/v1/prompt-learning/rollback', json={
        'version_id': save_payload['saved']['versionId'],
        'created_by': 'tester',
    })
    assert rollback.status_code == 200
    rollback_payload = rollback.json()
    assert rollback_payload['current']['versionId'] == save_payload['saved']['versionId']


def test_prompt_optimizer_service_uses_sample_cases() -> None:
    fragments = build_prompt_fragments({'base': 'base prompt', 'classify': 'classify prompt', 'field_understanding': 'field prompt'})
    result = run_prompt_test([], {'base': 'base prompt'}, {}, fragments=fragments, selected_fragment_ids=[item['id'] for item in fragments], test_case_ids=['tc_contract_factory'], document_type='合同', version_id='prompt-opt-v1')
    assert result['test_cases_used'][0]['id'] == 'tc_contract_factory'
    assert result['candidate_version']['status'] == 'candidate'


def test_prompt_learning_rule_patch_status_flow(client) -> None:
    evaluate = client.post(
        '/api/v1/document-foundation/evaluate',
        json={
            'experiment_record': {'run_dir': '', 'previous_run_dir': ''},
            'documents': [
                {
                    'filename': 'invoice.pdf',
                    'doc_type': '发票',
                    'raw_text_result': {'text': 'Invoice No: INV-001', 'metadata': {'source_kind': 'scan_ocr'}},
                    'alias_candidates': [{'standard_field': 'invoice_no', 'alias': 'Invoice No'}],
                    'standard_mappings': [],
                    'uncertain_fields': ['invoice_no'],
                    'manual_confirmation_rows': [
                        {'standard_field': 'invoice_no', 'ai_value': '', 'confirmed_value': 'INV-001'}
                    ],
                }
            ],
        },
    )

    assert evaluate.status_code == 200
    patch_id = evaluate.json()['evolution_summary']['recent_patches'][0]['id']

    promote = client.post('/api/v1/prompt-learning/rule-patches/status', json={'patch_id': patch_id, 'status': 'verified'})

    assert promote.status_code == 200
    assert promote.json()['updated']['status'] == 'verified'
