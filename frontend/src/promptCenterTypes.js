/**
 * @typedef {Object} PromptFragment
 * @property {string} id
 * @property {string} name
 * @property {string} type
 * @property {string} content
 * @property {boolean} enabled
 * @property {number} priority
 * @property {string} version
 * @property {number} lastTestScore
 * @property {number} hitCount
 * @property {string} updatedAt
 * @property {string} status
 * @property {boolean} [locked]
 * @property {boolean} [autoOptimizable]
 */

/** @typedef {{versionId:string, baseVersionId:string|null, changedFragments:string[], changeSummary:string, testSummary:Object, createdAt:string|null, createdBy:string, status:string, promptLength:number, fragments:PromptFragment[], isBuiltin?:boolean}} PromptVersion */
/** @typedef {{id:string, name:string, docType:string, sampleType:string, groundTruth:Object, input:Object}} TestCase */
/** @typedef {{runId:string, versionId:string, selectedFragmentIds:string[], selectedTestCaseIds:string[], documentType:string, metrics:Object, createdAt:string}} TestRun */
/** @typedef {{id:string, fragmentId:string, title:string, severity:string, problem:string, recommendation:string, reason:string, expectedImpactFields:string[], patchPreview:string}} OptimizationSuggestion */
/** @typedef {{patchId:string, baseVersionId:string, operations:Object[], summary:string, protectedFragmentIds:string[]}} PromptPatch */
/** @typedef {{versionId:string, fragmentIds:string[], metrics:Object, summary:Object, failedSamples:Object[], generatedAt:string}} EvaluationReport */

export function ensureFragments(items = []) {
  return Array.isArray(items) ? items.map((item) => ({ ...item })) : [];
}

export function ensureVersions(items = []) {
  return Array.isArray(items) ? items.map((item) => ({ ...item })) : [];
}

export function emptyReport() {
  return {
    versionId: 'prompt-opt-v1',
    fragmentIds: [],
    metrics: { fieldAccuracy: 0, fieldRecall: 0, docTypeAccuracy: 0, averageLatencyMs: 0, promptLength: 0, hitFields: 0, missedFields: 0, wrongFields: 0, gainDelta: 0 },
    summary: { documentCount: 0, testCaseCount: 0, passedDocuments: 0, failedDocuments: 0 },
    failedSamples: [],
    generatedAt: '',
  };
}

export function emptyPatch() {
  return { patchId: '', baseVersionId: 'prompt-opt-v1', operations: [], summary: '', protectedFragmentIds: [] };
}
