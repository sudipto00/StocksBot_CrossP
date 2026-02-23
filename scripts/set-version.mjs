#!/usr/bin/env node

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(scriptDir, '..');
const nextVersion = (process.argv[2] || '').trim();

const SEMVER_RE = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;

if (!nextVersion) {
  console.error('Usage: npm run version:set -- <version>');
  process.exit(1);
}

if (!SEMVER_RE.test(nextVersion)) {
  console.error(`Invalid semver version: ${nextVersion}`);
  process.exit(1);
}

const changedFiles = [];

function updateFile(filePath, updater) {
  const absPath = resolve(rootDir, filePath);
  const original = readFileSync(absPath, 'utf8');
  const updated = updater(original);
  if (updated !== original) {
    writeFileSync(absPath, updated, 'utf8');
    changedFiles.push(filePath);
  }
}

function updateJsonVersion(filePath) {
  updateFile(filePath, (content) => {
    const parsed = JSON.parse(content);
    if (parsed.version === nextVersion) {
      return content;
    }
    parsed.version = nextVersion;
    return `${JSON.stringify(parsed, null, 2)}\n`;
  });
}

function updateCargoVersion(filePath) {
  updateFile(filePath, (content) => {
    const newline = content.includes('\r\n') ? '\r\n' : '\n';
    const hasTrailingNewline = /\r?\n$/.test(content);
    const lines = content.split(/\r?\n/);
    if (hasTrailingNewline && lines[lines.length - 1] === '') {
      lines.pop();
    }
    let inPackage = false;
    let replaced = false;

    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      if (/^\[package\]\s*$/.test(line)) {
        inPackage = true;
        continue;
      }
      if (inPackage && /^\[[^\]]+\]\s*$/.test(line)) {
        inPackage = false;
      }
      if (inPackage && /^\s*version\s*=\s*"[^"]+"\s*$/.test(line)) {
        if (line.trim() !== `version = "${nextVersion}"`) {
          lines[i] = `version = "${nextVersion}"`;
        }
        replaced = true;
        break;
      }
    }

    if (!replaced) {
      throw new Error(`Failed to find [package] version in ${filePath}`);
    }

    const rebuilt = lines.join(newline);
    return hasTrailingNewline ? `${rebuilt}${newline}` : rebuilt;
  });
}

function updateRegex(filePath, pattern, replacement, label) {
  updateFile(filePath, (content) => {
    if (!pattern.test(content)) {
      throw new Error(`Failed to find ${label} in ${filePath}`);
    }
    return content.replace(pattern, replacement);
  });
}

try {
  updateJsonVersion('package.json');
  updateJsonVersion('ui/package.json');
  updateJsonVersion('src-tauri/tauri.conf.json');
  updateCargoVersion('src-tauri/Cargo.toml');

  updateRegex(
    'backend/app.py',
    /version\s*=\s*"[^"]+"/,
    `version="${nextVersion}"`,
    'FastAPI version'
  );

  updateRegex(
    'backend/api/health.py',
    /_APP_VERSION\s*=\s*"[^"]+"/,
    `_APP_VERSION = "${nextVersion}"`,
    'health version'
  );

  if (changedFiles.length === 0) {
    console.log(`Version already set to ${nextVersion}`);
  } else {
    console.log(`Updated version to ${nextVersion}`);
    for (const file of changedFiles) {
      console.log(`- ${file}`);
    }
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
