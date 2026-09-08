import test from "node:test";
import assert from "node:assert/strict";
import {
  isWorkflowPlanMetadata,
  WorkflowPlanMetadata,
  DedupeStep,
} from "../src/types/workflow.js";
import {
  validateWorkflowStepOrder,
  getAllowedInsertions,
  canMoveStep,
  canDeleteStep,
} from "../src/utils/workflowTopology.js";
import {
  createDefaultDedupeScorerConfig,
  buildWorkflowGeneratePayload,
} from "../src/utils/dedupeConfig.js";
import { formatDedupeErrorMessage } from "../src/api/errors.js";

test("Dedupe Workflow Plan Metadata Guard", async (t) => {
  const sha256A = "a".repeat(64);
  const sha256B = "b".repeat(64);

  await t.test("accepts valid dedupe workflow plan metadata without root_ids", () => {
    const meta: WorkflowPlanMetadata = {
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

  await t.test("rejects dedupe metadata if scan_job_id is invalid or missing", () => {
    const metaNoScan: any = {
      source: "workflow",
      workflow_id: 1,
      workflow_revision: 2,
      workflow_mode: "dedupe",
      definition_sha256: sha256A,
      compile_digest: sha256B,
      runtime_inputs: {},
    };
    assert.strictEqual(isWorkflowPlanMetadata(metaNoScan), false);

    const metaNegScan: any = {
      source: "workflow",
      workflow_id: 1,
      workflow_revision: 2,
      workflow_mode: "dedupe",
      scan_job_id: -1,
      definition_sha256: sha256A,
      compile_digest: sha256B,
      runtime_inputs: { scan_job_id: -1 },
    };
    assert.strictEqual(isWorkflowPlanMetadata(metaNegScan), false);
  });

  await t.test("rejects dedupe metadata if top-level and runtime_inputs scan_job_id conflict", () => {
    const metaConflict: any = {
      source: "workflow",
      workflow_id: 1,
      workflow_revision: 2,
      workflow_mode: "dedupe",
      scan_job_id: 10,
      definition_sha256: sha256A,
      compile_digest: sha256B,
      runtime_inputs: { scan_job_id: 20 },
    };
    assert.strictEqual(isWorkflowPlanMetadata(metaConflict), false);
  });

  await t.test("non-dedupe workflow plan metadata still requires root_ids", () => {
    const metaFileWithoutRoots: any = {
      source: "workflow",
      workflow_id: 1,
      workflow_revision: 2,
      workflow_mode: "file",
      definition_sha256: sha256A,
      compile_digest: sha256B,
      runtime_inputs: {},
    };
    assert.strictEqual(isWorkflowPlanMetadata(metaFileWithoutRoots), false);

    const metaFileWithRoots: any = {
      source: "workflow",
      workflow_id: 1,
      workflow_revision: 2,
      workflow_mode: "file",
      definition_sha256: sha256A,
      compile_digest: sha256B,
      runtime_inputs: { root_ids: [1, 2] },
    };
    assert.strictEqual(isWorkflowPlanMetadata(metaFileWithRoots), true);
  });
});

test("Dedupe Workflow Topology & Step Invariance", async (t) => {
  const dedupeStep: DedupeStep = {
    id: "step_dedupe_1",
    type: "dedupe",
    scorer_config: createDefaultDedupeScorerConfig(),
  };

  await t.test("validateWorkflowStepOrder requires exactly one dedupe step", () => {
    assert.strictEqual(validateWorkflowStepOrder([dedupeStep], "dedupe").valid, true);

    // Empty steps invalid
    assert.strictEqual(validateWorkflowStepOrder([], "dedupe").valid, false);

    // Multiple steps invalid
    assert.strictEqual(validateWorkflowStepOrder([dedupeStep, dedupeStep], "dedupe").valid, false);

    // Other step types in dedupe mode invalid
    const scanStep: any = { id: "s1", type: "scan", root_ids: [1] };
    assert.strictEqual(validateWorkflowStepOrder([scanStep], "dedupe").valid, false);
  });

  await t.test("dedupe mode allows 0 insertions and disables move/delete", () => {
    assert.deepStrictEqual(getAllowedInsertions([dedupeStep], "dedupe"), []);
    assert.strictEqual(canMoveStep([dedupeStep], 0, "up", "dedupe"), false);
    assert.strictEqual(canMoveStep([dedupeStep], 0, "down", "dedupe"), false);
    assert.strictEqual(canDeleteStep([dedupeStep], 0, "dedupe"), false);
  });
});

test("Workflow Generate Payload Contract", async (t) => {
  await t.test("buildWorkflowGeneratePayload sets compile_digest and scan_job_id without root_ids", () => {
    const payload = buildWorkflowGeneratePayload("comp_123456", 77);
    assert.strictEqual(payload.expected_compile_digest, "comp_123456");
    assert.strictEqual(payload.runtime_inputs.scan_job_id, 77);
    assert.strictEqual((payload.runtime_inputs as any).root_ids, undefined);
  });
});

test("Structured Error Presentation for Dedupe", async (t) => {
  await t.test("formats PREVIEW_CHANGED error", () => {
    const err = { error: { code: "PREVIEW_CHANGED", message: "digest mismatch" } };
    const msg = formatDedupeErrorMessage(err);
    assert.match(msg, /PREVIEW_CHANGED/);
    assert.match(msg, /重新运行预览/);
  });

  await t.test("formats DEDUPE_FACTOR_UNAVAILABLE error", () => {
    const err = { error: { code: "DEDUPE_FACTOR_UNAVAILABLE", message: "mtime not available" } };
    const msg = formatDedupeErrorMessage(err);
    assert.match(msg, /DEDUPE_FACTOR_UNAVAILABLE/);
  });

  await t.test("formats DEDUPE_LIMIT_EXCEEDED error", () => {
    const err = { error: { code: "DEDUPE_LIMIT_EXCEEDED", message: "rules exceed 64" } };
    const msg = formatDedupeErrorMessage(err);
    assert.match(msg, /DEDUPE_LIMIT_EXCEEDED/);
  });
});
