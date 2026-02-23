#!/usr/bin/env node

import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(scriptDir, '..');

function gitShortSha() {
  const result = spawnSync('git', ['rev-parse', '--short=12', 'HEAD'], {
    cwd: rootDir,
    encoding: 'utf8',
  });
  if (result.status === 0) {
    return result.stdout.trim();
  }
  return 'unknown';
}

const buildSha = (
  process.env.STOCKSBOT_BUILD_SHA ||
  process.env.VITE_BUILD_SHA ||
  gitShortSha()
).trim() || 'unknown';

const buildDate = (
  process.env.STOCKSBOT_BUILD_DATE ||
  process.env.VITE_BUILD_DATE ||
  new Date().toISOString()
).trim() || new Date().toISOString();

console.log(`[build-metadata] VITE_BUILD_SHA=${buildSha}`);
console.log(`[build-metadata] VITE_BUILD_DATE=${buildDate}`);

const env = {
  ...process.env,
  VITE_BUILD_SHA: buildSha,
  VITE_BUILD_DATE: buildDate,
};

const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const result = spawnSync(npmCmd, ['--prefix', 'ui', 'run', 'build'], {
  cwd: rootDir,
  stdio: 'inherit',
  env,
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
