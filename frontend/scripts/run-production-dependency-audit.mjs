import { spawnSync } from 'node:child_process';

const MAX_ATTEMPTS = 3;
const DEFAULT_DELAY_MS = 10_000;
const npmAuditArgs = [
  'audit',
  '--omit=dev',
  '--audit-level=moderate',
  '--fetch-retries=0',
  '--fetch-timeout=45000',
];

const delayValue = process.env.NFC_AUDIT_RETRY_DELAY_MS;
const retryDelay = delayValue === undefined ? DEFAULT_DELAY_MS : Number(delayValue);
if (!Number.isInteger(retryDelay) || retryDelay < 0 || retryDelay > 60_000) {
  console.error('Invalid NFC_AUDIT_RETRY_DELAY_MS');
  process.exit(1);
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
  console.error('Production dependency audit attempt ' + attempt + '/' + MAX_ATTEMPTS);
  const result = spawnSync('npm', npmAuditArgs, {
    cwd: process.cwd(),
    encoding: 'utf8',
    timeout: 75_000,
    maxBuffer: 8 * 1024 * 1024,
    env: process.env,
  });
  const stdout = result.stdout || '';
  const stderr = result.stderr || '';
  if (stdout) process.stdout.write(stdout);
  if (stderr) process.stderr.write(stderr);

  // An actual clean audit is the only success path. No missing result,
  // vulnerability exit status, timeout or registry outage can be accepted.
  if (result.status === 0 && !result.error && !result.signal) {
    process.exit(0);
  }

  const output = stdout + '\n' + stderr;
  const audit503 =
    /\b503\b[^\n]{0,100}\bService Unavailable\b/i.test(output) &&
    /\baudit\b|\/-\/npm\/v1\/security\/audits\//i.test(output);
  if (result.error) console.error('npm audit execution error: ' + result.error.message);
  if (result.signal) console.error('npm audit terminated by signal: ' + result.signal);

  if (!audit503 || result.error || result.signal) {
    console.error('Production dependency audit failed; no bypass or retry for vulnerabilities/unknown errors.');
    process.exit(1);
  }
  if (attempt === MAX_ATTEMPTS) {
    console.error('Production dependency audit could not reach npm advisory service after 3 attempts; FAIL CLOSED.');
    process.exit(1);
  }
  console.error('npm advisory endpoint returned HTTP 503; retrying only transient service failure.');
  await sleep(retryDelay);
}
process.exit(1);
