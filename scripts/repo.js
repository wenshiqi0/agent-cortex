// repo.js — cortex `repo` subcommands + shared path helpers. Runtime: bun (ESM).
//
//   cortex repo clone <url> [--name N] [--dry-run]
//   cortex repo init <name> [--dry-run]
//
// Destination is always <root>/repositories/<name>. Listing stays with inventory.

import fs from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';
import { ROOT } from './config.js';
import { die } from './resource.js';

const NAME_RE = /^[A-Za-z0-9._-]+$/;

export function fail(message, code = 1) {
  const err = new Error(message);
  err.exitCode = code;
  err.code = code;
  throw err;
}

/** Derive a repo directory name from a clone URL (https or scp-style). */
export function deriveRepoName(url) {
  const trimmed = String(url ?? '').trim();
  if (!trimmed) fail('ambiguous or empty repo url');

  let pathPart;
  if (!trimmed.includes('://') && trimmed.includes(':')) {
    // scp-style: git@host:owner/repo.git — split on first ':'
    const idx = trimmed.indexOf(':');
    pathPart = trimmed.slice(idx + 1);
  } else {
    try {
      pathPart = new URL(trimmed).pathname;
    } catch {
      pathPart = trimmed;
    }
  }

  pathPart = pathPart.replace(/\/+$/, '');
  const segments = pathPart.split('/').filter(Boolean);
  if (segments.length === 0) fail('ambiguous or empty repo url: ' + trimmed);

  let name = segments[segments.length - 1];
  if (name.endsWith('.git')) name = name.slice(0, -4);
  if (!name || name === '.' || name === '..') fail('ambiguous or empty repo url: ' + trimmed);
  return name;
}

/** Resolve and validate repositories/<name> under an injectable root. */
export function resolveRepoDest(name, opts = {}) {
  const root = opts.root ?? ROOT;
  if (name == null || String(name).trim() === '') fail('repo name is required');
  const n = String(name);
  if (n === '.' || n === '..' || n.includes('..') || !NAME_RE.test(n)) {
    fail('invalid repo name (expected [A-Za-z0-9._-]+, no ..): ' + n);
  }

  const reposRoot = path.resolve(root, 'repositories');
  const dest = path.resolve(reposRoot, n);
  const prefix = reposRoot.endsWith(path.sep) ? reposRoot : reposRoot + path.sep;
  if (dest !== reposRoot && !dest.startsWith(prefix)) {
    fail('destination escapes repositories/: ' + n);
  }
  return dest;
}

function runGit(args, opts = {}) {
  const result = spawnSync('git', args, {
    encoding: 'utf8',
    ...opts,
  });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || `exit ${result.status}`).trim();
    fail(`git ${args.join(' ')} failed: ${detail}`);
  }
  return (result.stdout || '').trimEnd();
}

export function cmdClone({ url, name, root = ROOT, dryRun = false } = {}) {
  if (!url) fail('repo clone requires <url>');
  const repoName = name || deriveRepoName(url);
  const dest = resolveRepoDest(repoName, { root });
  const command = `git clone ${url} ${dest}`;

  if (dryRun) {
    console.log(`name: ${repoName}`);
    console.log(`dest: ${dest}`);
    console.log(`command: ${command}`);
    return { name: repoName, dest, command };
  }

  fs.mkdirSync(path.join(root, 'repositories'), { recursive: true });
  if (fs.existsSync(dest)) fail('destination already exists: ' + dest);
  runGit(['clone', url, dest]);
  return { name: repoName, dest };
}

export function cmdInit({ name, root = ROOT, dryRun = false } = {}) {
  if (!name) fail('repo init requires <name>');
  const dest = resolveRepoDest(name, { root });
  const command = `git -C ${dest} init`;

  if (dryRun) {
    console.log(`name: ${name}`);
    console.log(`dest: ${dest}`);
    console.log(`command: ${command}`);
    return { name, dest, command };
  }

  fs.mkdirSync(path.join(root, 'repositories'), { recursive: true });
  if (fs.existsSync(dest)) fail('destination already exists: ' + dest);
  fs.mkdirSync(dest, { recursive: true });
  runGit(['init'], { cwd: dest });
  return { name, dest };
}

/** CLI dispatcher: cortex repo <clone|init> … */
export function cmdRepo(argv) {
  const [sub, ...pos] = argv._;
  try {
    if (sub === 'clone') {
      const url = pos[0];
      if (!url) die('usage: cortex repo clone <url> [--name N] [--dry-run]');
      return cmdClone({ url, name: argv.name, dryRun: !!argv.dryRun });
    }
    if (sub === 'init') {
      const name = pos[0] || argv.name;
      if (!name) die('usage: cortex repo init <name> [--dry-run]');
      return cmdInit({ name, dryRun: !!argv.dryRun });
    }
    die('repo commands: clone | init');
  } catch (e) {
    die(e.message || String(e));
  }
}
