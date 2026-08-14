// worktree.js — cortex `worktree` subcommands. Runtime: bun (ESM).
//
//   cortex worktree add --repo R --branch B [--base BASE] [--dry-run]
//   cortex worktree status --repo R --branch B [--json]
//   cortex worktree release --repo R --branch B --yes [--force]
//
// Layout: repositories/<repo>.worktrees/<branch> (branch may contain /).
// Listing stays with `bun run inventory --json` — no worktree list here.

import fs from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';
import { ROOT } from './config.js';
import { die } from './resource.js';
import { fail, resolveRepoDest } from './repo.js';

export function resolveWorktreePath(repo, branch, opts = {}) {
  const root = opts.root ?? ROOT;
  resolveRepoDest(repo, { root });
  if (!branch || String(branch).trim() === '') fail('branch is required');
  return path.join(root, 'repositories', `${repo}.worktrees`, branch);
}

function assertRepoGit(repoPath) {
  if (!fs.existsSync(path.join(repoPath, '.git'))) {
    fail('repo is not a git repository: ' + repoPath);
  }
}

function validateBranch(branch) {
  const result = spawnSync('git', ['check-ref-format', '--branch', branch], {
    encoding: 'utf8',
  });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || '').trim();
    fail(`invalid branch name: ${branch}${detail ? ` (${detail})` : ''}`);
  }
}

function runGit(cwd, args) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8' });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || `exit ${result.status}`).trim();
    fail(`git ${args.join(' ')} failed: ${detail}`);
  }
  return (result.stdout || '').trimEnd();
}

export function cmdAdd({ repo, branch, base, root = ROOT, dryRun = false } = {}) {
  if (!repo) fail('worktree add requires --repo');
  if (!branch) fail('worktree add requires --branch');

  const repoPath = resolveRepoDest(repo, { root });
  assertRepoGit(repoPath);
  validateBranch(branch);

  const wtPath = resolveWorktreePath(repo, branch, { root });
  if (fs.existsSync(wtPath)) fail('worktree path already exists: ' + wtPath);

  const args = ['worktree', 'add', wtPath, '-b', branch];
  if (base) args.push(base);
  const command = `git -C ${repoPath} ${args.join(' ')}`;

  if (dryRun) {
    console.log(`repo: ${repo}`);
    console.log(`branch: ${branch}`);
    console.log(`worktree_path: ${wtPath}`);
    console.log(`command: ${command}`);
    return { repo, branch, worktree_path: wtPath, command };
  }

  fs.mkdirSync(path.dirname(wtPath), { recursive: true });
  runGit(repoPath, args);
  return { repo, branch, worktree_path: wtPath };
}

export function cmdStatus({
  repo,
  branch,
  root = ROOT,
  env = process.env,
  json = false,
} = {}) {
  if (!repo) fail('worktree status requires --repo');
  if (!branch) fail('worktree status requires --branch');

  const repoPath = resolveRepoDest(repo, { root });
  assertRepoGit(repoPath);
  const wtPath = resolveWorktreePath(repo, branch, { root });

  const view = spawnSync(
    'gh',
    ['pr', 'view', branch, '--json', 'state,mergeStateStatus,mergedAt,url'],
    { cwd: repoPath, encoding: 'utf8', env },
  );

  let pr = null;
  if (view.status === 0) {
    try {
      pr = JSON.parse(view.stdout || 'null');
    } catch {
      pr = null;
    }
  }

  const checksProc = spawnSync('gh', ['pr', 'checks', branch], {
    cwd: repoPath,
    encoding: 'utf8',
    env,
  });
  const checks =
    checksProc.status === 0
      ? (checksProc.stdout || '').trimEnd()
      : (checksProc.stderr || checksProc.stdout || '').trimEnd();

  const ok = Boolean(pr) && checksProc.status === 0;
  const result = {
    repo,
    branch,
    worktree_path: wtPath,
    pr,
    checks,
    ok,
  };

  if (json) console.log(JSON.stringify(result));
  else {
    console.log(`repo: ${repo}`);
    console.log(`branch: ${branch}`);
    console.log(`worktree_path: ${wtPath}`);
    console.log(`pr: ${pr ? JSON.stringify(pr) : 'null'}`);
    console.log(`checks: ${checks || '(none)'}`);
    console.log(`ok: ${ok}`);
  }
  return result;
}

export function cmdRelease({
  repo,
  branch,
  root = ROOT,
  yes = false,
  force = false,
} = {}) {
  if (!repo) fail('worktree release requires --repo');
  if (!branch) fail('worktree release requires --branch');
  if (!yes) fail('refusing to release without --yes (ask the user first)');

  const repoPath = resolveRepoDest(repo, { root });
  assertRepoGit(repoPath);
  const wtPath = resolveWorktreePath(repo, branch, { root });

  runGit(repoPath, ['worktree', 'remove', wtPath]);

  const delFlag = force ? '-D' : '-d';
  const del = spawnSync('git', ['branch', delFlag, branch], {
    cwd: repoPath,
    encoding: 'utf8',
  });
  if (del.status !== 0) {
    const detail = (del.stderr || del.stdout || `exit ${del.status}`).trim();
    console.error(`worktree removed at ${wtPath}, but branch deletion failed: ${detail}`);
    fail(`branch deletion failed after worktree remove: ${detail}`);
  }
  return { repo, branch, worktree_path: wtPath, removed: true };
}

export function cmdWorktree(argv) {
  const [sub] = argv._;
  try {
    if (sub === 'add') {
      if (!argv.repo || !argv.branch) {
        die('usage: cortex worktree add --repo R --branch B [--base BASE] [--dry-run]');
      }
      return cmdAdd({
        repo: argv.repo,
        branch: argv.branch,
        base: argv.base,
        dryRun: !!argv.dryRun,
      });
    }
    if (sub === 'status') {
      if (!argv.repo || !argv.branch) {
        die('usage: cortex worktree status --repo R --branch B [--json]');
      }
      return cmdStatus({
        repo: argv.repo,
        branch: argv.branch,
        json: !!argv.json,
      });
    }
    if (sub === 'release') {
      if (!argv.repo || !argv.branch) {
        die('usage: cortex worktree release --repo R --branch B --yes [--force]');
      }
      return cmdRelease({
        repo: argv.repo,
        branch: argv.branch,
        yes: !!argv.yes,
        force: !!argv.force,
      });
    }
    die('worktree commands: add | status | release');
  } catch (e) {
    die(e.message || String(e));
  }
}
