import { execSync } from 'node:child_process';
import { writeFileSync, rmSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const outDir = resolve('dist-test');
try {
  execSync(
    'npx tsc --outDir dist-test --module commonjs --target es2022 --moduleResolution node --esModuleInterop tests/task_observability.test.ts',
    { stdio: 'inherit' }
  );
  writeFileSync(
    resolve(outDir, 'package.json'),
    JSON.stringify({ type: 'commonjs' })
  );
  execSync('node --test dist-test/tests/task_observability.test.js', {
    stdio: 'inherit',
  });
} finally {
  if (existsSync(outDir)) {
    rmSync(outDir, { recursive: true, force: true });
  }
}
