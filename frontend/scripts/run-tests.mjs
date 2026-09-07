import { execSync } from 'node:child_process';
import { writeFileSync, rmSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const outDir = resolve('dist-test');
try {
  execSync(
    './node_modules/.bin/tsc --outDir dist-test --module commonjs --target es2022 --moduleResolution node --esModuleInterop tests/task_observability.test.ts tests/task_actions.test.ts tests/task_cleanup.test.ts tests/scan_lifecycle.test.ts tests/dashboard_freshness.test.ts tests/plan_cleanup.test.ts tests/legacy_plan_cleanup.test.ts tests/index_lifecycle.test.ts tests/data_lifecycle.test.ts tests/gate4_quarantine_undo.test.ts tests/workflows.test.ts tests/stale_rebuild.test.ts tests/hotfix1_red.test.ts tests/hotfix2_red.test.ts tests/hotfix3_red.test.ts tests/hotfix4_red.test.ts',
    { stdio: 'inherit' }
  );
  writeFileSync(
    resolve(outDir, 'package.json'),
    JSON.stringify({ type: 'commonjs' })
  );
  execSync('node --test dist-test/tests/task_observability.test.js dist-test/tests/task_actions.test.js dist-test/tests/task_cleanup.test.js dist-test/tests/scan_lifecycle.test.js dist-test/tests/dashboard_freshness.test.js dist-test/tests/plan_cleanup.test.js dist-test/tests/legacy_plan_cleanup.test.js dist-test/tests/index_lifecycle.test.js dist-test/tests/data_lifecycle.test.js dist-test/tests/gate4_quarantine_undo.test.js dist-test/tests/workflows.test.js dist-test/tests/stale_rebuild.test.js dist-test/tests/hotfix1_red.test.js dist-test/tests/hotfix2_red.test.js dist-test/tests/hotfix3_red.test.js dist-test/tests/hotfix4_red.test.js', {
    stdio: 'inherit',
  });
} finally {
  if (existsSync(outDir)) {
    rmSync(outDir, { recursive: true, force: true });
  }
}
