import test from "node:test";
import assert from "node:assert/strict";

import { isWorkflowPlanMetadata } from "../src/types/workflow.js";
import {
  classifyMemberDecision,
  mapWorkflowPreviewItemsToDedupeRows,
  formatScanRootLabel,
  isBalancerContributionExcludedFromFactors,
} from "../src/utils/dedupePreview.js";
import { formatDedupeErrorMessage } from "../src/api/errors.js";
import {
  dedupeStateReducer,
  initialDedupeState,
  canGeneratePlan,
  DedupeState,
} from "../src/utils/dedupeState.js";

const sha256A = "a".repeat(64);
const sha256B = "b".repeat(64);

test("Item 15-A: classifyMemberDecision comprehensive mappings", async (t) => {
  await t.test("KEEP decision", () => {
    const res = classifyMemberDecision("KEEP");
    assert.strictEqual(res.label, "KEEP");
    assert.strictEqual(res.kind, "KEEP");
    assert.strictEqual(res.color, "success");
  });

  await t.test("QUARANTINE decision", () => {
    const res = classifyMemberDecision("QUARANTINE");
    assert.strictEqual(res.label, "QUARANTINE");
    assert.strictEqual(res.kind, "QUARANTINE");
    assert.strictEqual(res.color, "error");
  });

  await t.test("SKIPPED + eligible_as_keep=false maps to SAFETY EXCLUDED", () => {
    const res = classifyMemberDecision("SKIPPED", false);
    assert.strictEqual(res.label, "SAFETY EXCLUDED");
    assert.strictEqual(res.kind, "SAFETY_EXCLUDED");
    assert.strictEqual(res.color, "warning");
  });

  await t.test("SKIPPED + eligible_as_keep=true maps to SKIPPED", () => {
    const res = classifyMemberDecision("SKIPPED", true);
    assert.strictEqual(res.label, "SKIPPED");
    assert.strictEqual(res.kind, "SKIPPED");
    assert.strictEqual(res.color, "default");
  });

  await t.test("Raw string with SAFETY_EXCLUDED maps to SAFETY EXCLUDED", () => {
    const res = classifyMemberDecision("SAFETY_EXCLUDED");
    assert.strictEqual(res.label, "SAFETY EXCLUDED");
    assert.strictEqual(res.kind, "SAFETY_EXCLUDED");
    assert.strictEqual(res.color, "warning");
  });

  await t.test("UNAVAILABLE decision", () => {
    const res = classifyMemberDecision("UNAVAILABLE");
    assert.strictEqual(res.label, "UNAVAILABLE");
    assert.strictEqual(res.kind, "UNAVAILABLE");
    assert.strictEqual(res.color, "default");
  });
});

test("Item 15-B: isWorkflowPlanMetadata strict guard", async (t) => {
  await t.test("valid dedupe metadata with matching positive integers", () => {
    const meta = {
      source: "workflow",
      workflow_id: 1,
      workflow_revision: 2,
      workflow_mode: "dedupe",
      scan_job_id: 10,
      definition_sha256: sha256A,
      compile_digest: sha256B,
      runtime_inputs: {
        scan_job_id: 10,
      },
    };
    assert.strictEqual(isWorkflowPlanMetadata(meta), true);
  });

  await t.test("missing top-level scan_job_id returns false", () => {
    const meta = {
      source: "workflow",
      workflow_id: 1,
      workflow_revision: 2,
      workflow_mode: "dedupe",
      definition_sha256: sha256A,
      compile_digest: sha256B,
      runtime_inputs: {
        scan_job_id: 10,
      },
    };
    assert.strictEqual(isWorkflowPlanMetadata(meta), false);
  });

  await t.test("missing runtime scan_job_id returns false", () => {
    const meta = {
      source: "workflow",
      workflow_id: 1,
      workflow_revision: 2,
      workflow_mode: "dedupe",
      scan_job_id: 10,
      definition_sha256: sha256A,
      compile_digest: sha256B,
      runtime_inputs: {},
    };
    assert.strictEqual(isWorkflowPlanMetadata(meta), false);
  });

  await t.test("mismatched scan_job_id returns false", () => {
    const meta = {
      source: "workflow",
      workflow_id: 1,
      workflow_revision: 2,
      workflow_mode: "dedupe",
      scan_job_id: 10,
      definition_sha256: sha256A,
      compile_digest: sha256B,
      runtime_inputs: {
        scan_job_id: 20,
      },
    };
    assert.strictEqual(isWorkflowPlanMetadata(meta), false);
  });

  await t.test("non-positive or non-integer scan_job_id returns false", () => {
    assert.strictEqual(
      isWorkflowPlanMetadata({
        source: "workflow",
        workflow_id: 1,
        workflow_revision: 2,
        workflow_mode: "dedupe",
        scan_job_id: 0,
        definition_sha256: sha256A,
        compile_digest: sha256B,
        runtime_inputs: { scan_job_id: 0 },
      }),
      false
    );

    assert.strictEqual(
      isWorkflowPlanMetadata({
        source: "workflow",
        workflow_id: 1,
        workflow_revision: 2,
        workflow_mode: "dedupe",
        scan_job_id: -5,
        definition_sha256: sha256A,
        compile_digest: sha256B,
        runtime_inputs: { scan_job_id: -5 },
      }),
      false
    );

    assert.strictEqual(
      isWorkflowPlanMetadata({
        source: "workflow",
        workflow_id: 1,
        workflow_revision: 2,
        workflow_mode: "dedupe",
        scan_job_id: 1.5,
        definition_sha256: sha256A,
        compile_digest: sha256B,
        runtime_inputs: { scan_job_id: 1.5 },
      }),
      false
    );
  });
});

test("Item 15-C: formatDedupeErrorMessage covers all 13 canonical dedupe error codes", async () => {
  const codes = [
    "DEDUPE_SCAN_NOT_COMPLETED",
    "DEDUPE_SNAPSHOT_EMPTY",
    "DEDUPE_ROOT_MISMATCH",
    "DEDUPE_INVALID_CONFIG",
    "DEDUPE_FACTOR_UNAVAILABLE",
    "DEDUPE_LIMIT_EXCEEDED",
    "DEDUPE_EMPTY_PLAN",
    "DEDUPE_PREVIEW_CHANGED",
    "DEDUPE_QUARANTINE_CONFLICT",
    "DEDUPE_STEP_NOT_FOUND",
    "DEDUPE_MULTIPLE_STEPS_UNSUPPORTED",
    "DEDUPE_WORKFLOW_INPUT_MISMATCH",
    "PREVIEW_CHANGED",
  ];

  for (const code of codes) {
    const formatted = formatDedupeErrorMessage({
      error: { code, message: 'detail for ' + code },
    });
    assert.ok(formatted && formatted.length > 0, 'Formatted message for ' + code + ' must not be empty');
    assert.notStrictEqual(formatted, '未知错误');
    assert.notStrictEqual(formatted, '去重操作失败');
    assert.match(formatted, new RegExp(code.includes('PREVIEW_CHANGED') ? 'PREVIEW_CHANGED' : code));
  }
});

test("Item 15-D: dedupeStateReducer state transitions and generation tracking", async (t) => {
  await t.test("initial state cannot generate plan", () => {
    assert.strictEqual(initialDedupeState.status, "INITIAL");
    assert.strictEqual(initialDedupeState.configGeneration, 1);
    assert.strictEqual(initialDedupeState.acceptedPreviewDigest, null);
    assert.strictEqual(canGeneratePlan(initialDedupeState), false);
  });

  await t.test("start preview records activeRequestGeneration", () => {
    const s1 = dedupeStateReducer(initialDedupeState, { type: "PREVIEW_STARTED" });
    assert.strictEqual(s1.status, "PREVIEW_RUNNING");
    assert.strictEqual(s1.activeRequestGeneration, 1);
    assert.strictEqual(canGeneratePlan(s1), false);
  });

  await t.test("preview success with matching generation sets accepted digest and PREVIEW_READY", () => {
    let s = dedupeStateReducer(initialDedupeState, { type: "PREVIEW_STARTED" });
    s = dedupeStateReducer(s, {
      type: "PREVIEW_SUCCESS",
      digest: sha256A,
      requestGeneration: 1,
    });
    assert.strictEqual(s.status, "PREVIEW_READY");
    assert.strictEqual(s.acceptedPreviewDigest, sha256A);
    assert.strictEqual(s.currentPreviewDigest, sha256A);
    assert.strictEqual(s.activeRequestGeneration, null);
    assert.strictEqual(canGeneratePlan(s), true);
  });

  await t.test("config edit clears accepted digest and increments generation", () => {
    let s: DedupeState = {
      status: "PREVIEW_READY",
      configGeneration: 1,
      activeRequestGeneration: null,
      acceptedPreviewDigest: sha256A,
      currentPreviewDigest: sha256A,
      lastErrorMessage: null,
    };
    s = dedupeStateReducer(s, { type: "CONFIG_EDITED" });
    assert.strictEqual(s.status, "PREVIEW_STALE");
    assert.strictEqual(s.configGeneration, 2);
    assert.strictEqual(s.acceptedPreviewDigest, null);
    assert.strictEqual(s.currentPreviewDigest, null);
    assert.strictEqual(canGeneratePlan(s), false);
  });

  await t.test("outdated preview response from old generation is discarded", () => {
    // Current generation is 2
    let s: DedupeState = {
      status: "PREVIEW_STALE",
      configGeneration: 2,
      activeRequestGeneration: 1,
      acceptedPreviewDigest: null,
      currentPreviewDigest: null,
      lastErrorMessage: null,
    };
    // Response from generation 1 arrives
    s = dedupeStateReducer(s, {
      type: "PREVIEW_SUCCESS",
      digest: sha256A,
      requestGeneration: 1,
    });
    assert.strictEqual(s.status, "PREVIEW_STALE");
    assert.strictEqual(s.acceptedPreviewDigest, null);
    assert.strictEqual(canGeneratePlan(s), false);
  });

  await t.test("PREVIEW_CHANGED_ERROR resets digest and status to PREVIEW_STALE", () => {
    let s: DedupeState = {
      status: "PREVIEW_READY",
      configGeneration: 2,
      activeRequestGeneration: null,
      acceptedPreviewDigest: sha256A,
      currentPreviewDigest: sha256A,
      lastErrorMessage: null,
    };
    s = dedupeStateReducer(s, {
      type: "PREVIEW_CHANGED_ERROR",
      error: "digest mismatch",
    });
    assert.strictEqual(s.status, "PREVIEW_STALE");
    assert.strictEqual(s.acceptedPreviewDigest, null);
    assert.strictEqual(s.currentPreviewDigest, null);
    assert.strictEqual(s.lastErrorMessage, "digest mismatch");
    assert.strictEqual(canGeneratePlan(s), false);
  });
});

test("Item 15-E: mapWorkflowPreviewItemsToDedupeRows non-canonical handling", async (t) => {
  await t.test("missing metadata is marked incomplete with UNAVAILABLE decision and undefined score", () => {
    const rawItems = [
      {
        source_path: "/volume1/data/a.txt",
        operation: "keep",
        changed: false,
        metadata: {},
      },
    ];
    const rows = mapWorkflowPreviewItemsToDedupeRows(rawItems);
    assert.strictEqual(rows.length, 1);
    assert.strictEqual(rows[0].incomplete, true);
    assert.strictEqual(rows[0].member_decision, "UNAVAILABLE");
    assert.strictEqual(rows[0].total_score, undefined);
  });

  await t.test("canonical metadata is preserved and marked incomplete=false", () => {
    const rawItems = [
      {
        source_path: "/volume1/data/b.txt",
        operation: "quarantine",
        changed: true,
        metadata: {
          group_provenance_id: 101,
          member_decision: "QUARANTINE",
          eligible_as_keep: true,
          total_score: 85,
        },
      },
    ];
    const rows = mapWorkflowPreviewItemsToDedupeRows(rawItems);
    assert.strictEqual(rows.length, 1);
    assert.strictEqual(rows[0].incomplete, false);
    assert.strictEqual(rows[0].group_provenance_id, 101);
    assert.strictEqual(rows[0].member_decision, "QUARANTINE");
    assert.strictEqual(rows[0].total_score, 85);
  });
});

test("Item 15-F: Balancer & Helpers Contract Verification", () => {
  assert.strictEqual(
    isBalancerContributionExcludedFromFactors({ factor: "balanced_by_bytes", configured_weight: 0, actual_contribution: 0 }),
    true
  );
  assert.strictEqual(
    isBalancerContributionExcludedFromFactors({ factor: "mtime", configured_weight: 10, actual_contribution: 10 }),
    false
  );
  assert.strictEqual(
    formatScanRootLabel(0, "/data"),
    "Scan Root 0 /data"
  );
});
