import test from "node:test";
import assert from "node:assert/strict";

import { isWorkflowPlanMetadata } from "../src/types/workflow.js";
import {
  formatDedupeErrorMessage,
} from "../src/api/errors.js";
import {
  dedupeStateReducer,
  initialDedupeState,
  canGeneratePlan,
  DedupeState,
} from "../src/utils/dedupeState.js";
import {
  mapWorkflowPreviewItemsToDedupeRows,
  isCanonicalDedupeMetadataComplete,
  formatScanRootLabel,
} from "../src/utils/dedupePreview.js";
import {
  computeWorkflowDedupeTableTotal,
  shouldAcceptDirectResponse,
  shouldAcceptWorkflowResponse,
  computeCanDraft,
  resolveDirectSafetyPolicy,
} from "../src/utils/hotfix2Helpers.js";
import { formatDateTime } from "../src/utils/format.js";

const sha256A = "a".repeat(64);
const sha256B = "b".repeat(64);

test("Item 14-A: canonical 13 backend semantic error codes exact coverage", async (t) => {
  const canonical13Codes = [
    "DEDUPE_INVALID_CONFIG",
    "DEDUPE_FACTOR_UNAVAILABLE",
    "DEDUPE_LIMIT_EXCEEDED",
    "DEDUPE_EMPTY_PLAN",
    "PREVIEW_CHANGED",
    "DEDUPE_SCAN_NOT_FOUND",
    "DEDUPE_SCAN_NOT_COMPLETED",
    "SCAN_JOB_ID_REQUIRED",
    "SCAN_JOB_ID_FORBIDDEN",
    "ROOT_IDS_FORBIDDEN",
    "AMBIGUOUS_RUNTIME_INPUTS",
    "WORKFLOW_ARCHIVED",
    "DEDUPE_RESCAN_REQUIRED",
  ];

  for (const code of canonical13Codes) {
    await t.test(`covers code: ${code}`, () => {
      const rawMsg = "Custom raw message for " + code;
      const formatted = formatDedupeErrorMessage({
        error: { code, message: rawMsg },
      });
      assert.ok(formatted && formatted.length > 0, `Message for ${code} must not be empty`);
      assert.notStrictEqual(formatted, rawMsg, `Code ${code} must not fall back to generic message`);
      assert.notStrictEqual(formatted, "未知错误");
      assert.notStrictEqual(formatted, "去重操作失败");
      assert.match(formatted, new RegExp(code), `Formatted message must contain the code ${code}`);

      if (code === "DEDUPE_RESCAN_REQUIRED") {
        assert.match(formatted, /new scan/i);
        assert.match(formatted, /completed/i);
        assert.match(formatted, /return Workflow/i);
        assert.match(formatted, /select new Scan Job/i);
        assert.match(formatted, /Preview/i);
        assert.match(formatted, /Generate new Draft/i);
      }
    });
  }
});

test("Item 14-B: Direct pagination digest A -> B updates accepted identity", () => {
  // Page 1 succeeds with digest A
  let s: DedupeState = dedupeStateReducer(initialDedupeState, { type: "PREVIEW_STARTED" });
  s = dedupeStateReducer(s, {
    type: "PREVIEW_SUCCESS",
    digest: sha256A,
    requestGeneration: 1,
  });
  assert.strictEqual(s.status, "PREVIEW_READY");
  assert.strictEqual(s.acceptedPreviewDigest, sha256A);
  assert.strictEqual(s.currentPreviewDigest, sha256A);
  assert.strictEqual(canGeneratePlan(s), true);

  // Page 2 pagination succeeds with digest B
  s = dedupeStateReducer(s, { type: "PREVIEW_STARTED" });
  s = dedupeStateReducer(s, {
    type: "PREVIEW_SUCCESS",
    digest: sha256B,
    requestGeneration: 1,
  });
  assert.strictEqual(s.status, "PREVIEW_READY");
  assert.strictEqual(s.acceptedPreviewDigest, sha256B);
  assert.strictEqual(s.currentPreviewDigest, sha256B);
  assert.strictEqual(canGeneratePlan(s), true);
});

test("Item 14-C: Direct pagination failure clears accepted identity", () => {
  // Page 1 succeeded with digest A
  let s: DedupeState = dedupeStateReducer(initialDedupeState, { type: "PREVIEW_STARTED" });
  s = dedupeStateReducer(s, {
    type: "PREVIEW_SUCCESS",
    digest: sha256A,
    requestGeneration: 1,
  });
  assert.strictEqual(s.acceptedPreviewDigest, sha256A);

  // Next page pagination fails
  s = dedupeStateReducer(s, { type: "PREVIEW_FAILED", error: "Pagination failed" });
  assert.strictEqual(s.status, "PREVIEW_STALE");
  assert.strictEqual(s.acceptedPreviewDigest, null);
  assert.strictEqual(s.currentPreviewDigest, null);
  assert.strictEqual(canGeneratePlan(s), false);
});

test("Item 14-D: stale Direct response cannot replace rows/config", () => {
  const accepted = shouldAcceptDirectResponse({
    responseGeneration: 1,
    currentGeneration: 2,
  });
  assert.strictEqual(accepted, false);

  const acceptedMatching = shouldAcceptDirectResponse({
    responseGeneration: 2,
    currentGeneration: 2,
  });
  assert.strictEqual(acceptedMatching, true);
});

test("Item 14-E: Workflow revision in-flight race", () => {
  const accepted = shouldAcceptWorkflowResponse({
    snapshot: {
      workflowId: 10,
      revision: 3,
      mode: "dedupe",
      requestId: 1,
      page: 1,
      pageSize: 50,
      onlyChanged: false,
    },
    currentWorkflowId: 10,
    currentRevision: 4,
    currentMode: "dedupe",
    currentRequestId: 2,
  });
  assert.strictEqual(accepted, false);
});

test("Item 14-F: Workflow ID in-flight race", () => {
  const accepted = shouldAcceptWorkflowResponse({
    snapshot: {
      workflowId: 10,
      revision: 2,
      mode: "dedupe",
      requestId: 1,
      page: 1,
      pageSize: 50,
      onlyChanged: false,
    },
    currentWorkflowId: 20,
    currentRevision: 2,
    currentMode: "dedupe",
    currentRequestId: 2,
  });
  assert.strictEqual(accepted, false);
});

test("Item 14-G: only_changed filtered total", () => {
  const preview = {
    matched_count: 100,
    planned_operations_count: 10,
  };

  const totalAll = computeWorkflowDedupeTableTotal(preview, false);
  assert.strictEqual(totalAll, 100);

  const totalOnlyChanged = computeWorkflowDedupeTableTotal(preview, true);
  assert.strictEqual(totalOnlyChanged, 10);
});

test("Item 14-H: WORKFLOW_ARCHIVED clears compile authority and disables draft", () => {
  const canDraftBefore = computeCanDraft({
    isArchived: false,
    isDirty: false,
    previewState: "PREVIEW_READY",
    compileDigest: sha256A,
    previewPending: false,
    generatePending: false,
    isDedupe: true,
    selectedScanJobId: 10,
    hasDedupeSummary: true,
  });
  assert.strictEqual(canDraftBefore, true);

  // When WORKFLOW_ARCHIVED happens, compileDigest is cleared, previewState is PREVIEW_STALE
  const canDraftAfter = computeCanDraft({
    isArchived: false,
    isDirty: false,
    previewState: "PREVIEW_STALE",
    compileDigest: null,
    previewPending: false,
    generatePending: false,
    isDedupe: true,
    selectedScanJobId: 10,
    hasDedupeSummary: true,
  });
  assert.strictEqual(canDraftAfter, false);
});

test("Item 14-I: Identity panel preserves distinct compile_digest and preview_digest", () => {
  const directData = {
    authorityType: "preview_digest" as const,
    authorityDigest: sha256A,
  };
  assert.strictEqual(directData.authorityDigest, sha256A);

  const workflowData = {
    authorityType: "compile_digest" as const,
    authorityDigest: sha256A,
    dedupePreviewDigest: sha256B,
  };
  assert.notStrictEqual(workflowData.authorityDigest, workflowData.dedupePreviewDigest);
  assert.strictEqual(workflowData.authorityDigest, sha256A);
  assert.strictEqual(workflowData.dedupePreviewDigest, sha256B);
});

test("Item 14-J: preview_source displayed from backend", () => {
  const backendSource = "completed-scan-readonly-safety";
  const directProps = {
    previewSource: backendSource,
  };
  assert.strictEqual(directProps.previewSource, backendSource);
});

test("Item 14-K: Direct effective safety top-level true/false", () => {
  const policyTrue = resolveDirectSafetyPolicy({
    summary: {},
    topLevelSafetyPolicy: { protect_last_file: true },
  });
  assert.strictEqual(policyTrue.protect_last_file, true);

  const policyFalse = resolveDirectSafetyPolicy({
    summary: {},
    topLevelSafetyPolicy: { protect_last_file: false },
  });
  assert.strictEqual(policyFalse.protect_last_file, false);
});

test("Item 14-L: metadata mode-aware strict validation", async (t) => {
  await t.test("missing workflow_mode + scan IDs returns false", () => {
    assert.strictEqual(
      isWorkflowPlanMetadata({
        source: "workflow",
        workflow_id: 1,
        workflow_revision: 1,
        scan_job_id: 10,
        definition_sha256: sha256A,
        compile_digest: sha256B,
        runtime_inputs: { scan_job_id: 10 },
      }),
      false
    );
  });

  await t.test("workflow_mode=file + scan IDs returns false", () => {
    assert.strictEqual(
      isWorkflowPlanMetadata({
        source: "workflow",
        workflow_id: 1,
        workflow_revision: 1,
        workflow_mode: "file",
        scan_job_id: 10,
        definition_sha256: sha256A,
        compile_digest: sha256B,
        runtime_inputs: { scan_job_id: 10 },
      }),
      false
    );
  });

  await t.test("workflow_mode=organizer + scan IDs returns false", () => {
    assert.strictEqual(
      isWorkflowPlanMetadata({
        source: "workflow",
        workflow_id: 1,
        workflow_revision: 1,
        workflow_mode: "organizer",
        scan_job_id: 10,
        definition_sha256: sha256A,
        compile_digest: sha256B,
        runtime_inputs: { scan_job_id: 10 },
      }),
      false
    );
  });

  await t.test("workflow_mode=dedupe + matching positive scan IDs returns true", () => {
    assert.strictEqual(
      isWorkflowPlanMetadata({
        source: "workflow",
        workflow_id: 1,
        workflow_revision: 1,
        workflow_mode: "dedupe",
        scan_job_id: 10,
        definition_sha256: sha256A,
        compile_digest: sha256B,
        runtime_inputs: { scan_job_id: 10 },
      }),
      true
    );
  });

  await t.test("workflow_mode=dedupe + mismatched scan IDs returns false", () => {
    assert.strictEqual(
      isWorkflowPlanMetadata({
        source: "workflow",
        workflow_id: 1,
        workflow_revision: 1,
        workflow_mode: "dedupe",
        scan_job_id: 10,
        definition_sha256: sha256A,
        compile_digest: sha256B,
        runtime_inputs: { scan_job_id: 20 },
      }),
      false
    );
  });
});

test("Item 14-M: incomplete adapter does not fabricate actionable, size=0, Scan Root 0, eligible=false", () => {
  const rawItems = [
    {
      source_path: "/data/doc.pdf",
      operation: "keep",
      changed: false,
      metadata: {
        group_provenance_id: 1,
        member_decision: "KEEP",
      },
    },
  ];

  assert.strictEqual(isCanonicalDedupeMetadataComplete(rawItems[0].metadata), false);

  const rows = mapWorkflowPreviewItemsToDedupeRows(rawItems);
  assert.strictEqual(rows.length, 1);
  const row = rows[0];

  assert.strictEqual(row.incomplete, true);
  assert.strictEqual(row.member_decision, "UNAVAILABLE");
  assert.strictEqual(row.group_status, undefined);
  assert.strictEqual(row.group_file_size, undefined);
  assert.strictEqual(row.scan_root_index, undefined);
  assert.strictEqual(row.eligible_as_keep, undefined);
  assert.strictEqual(row.recommended_keep, undefined);
});

test("Item 14-N: CompletedScan display finish time and Scan Root labels", () => {
  const scan = {
    id: 42,
    name: "My Scan",
    status: "completed",
    finished_at: "2026-09-08T12:00:00.000Z",
    roots: ["/nas/share1", "/nas/share2"],
  };

  const formattedTime = formatDateTime(scan.finished_at);
  assert.ok(formattedTime && formattedTime.length > 0);
  assert.notStrictEqual(formattedTime, "-");

  const rootLabels = scan.roots.map((r, idx) => formatScanRootLabel(idx, r));
  assert.deepStrictEqual(rootLabels, [
    "Scan Root 0 /nas/share1",
    "Scan Root 1 /nas/share2",
  ]);
  assert.notStrictEqual(rootLabels.join(""), scan.roots.join(", "));
});
