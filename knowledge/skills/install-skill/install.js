#!/usr/bin/env node
// install.js — install/verify/restore/remove skills into agent-cortex's SSOT.
//
// Skills are copied into knowledge/skills/<name>/ (the single source of truth);
// the runtime symlinks (.claude/skills, .agents/skills) expose them to every
// tool automatically. A lockfile (knowledge/skills-lock.json) records each
// skill's source + a SHA-256 of its folder contents for verify/restore.
//
// Usage:
//   node install.js install github <owner/repo> [name] [--ref <ref>] [--path <dir>]
//   node install.js install git    <repo-url>   [name] [--ref <ref>] [--path <dir>]
//   node install.js install npm    <package>    [name] [--path <dir>]
//   node install.js verify  [name]      # recompute hashes, report drift
//   node install.js restore [name]      # reinstall from lock (npm-ci equivalent)
//   node install.js remove  <name>      # delete skill folder + lock entry
//   node install.js list                # list installed skills from lock
//
// name defaults to the skill folder name found in the source.
// --path overrides where to look for the skill inside the source (default: auto:
//   skills/<name>/SKILL.md, then <name>/SKILL.md, then ./SKILL.md).

'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

// ---- locate SSOT roots (script lives at knowledge/skills/install-skill/) ----
const SKILL_DIR = __dirname;
const SKILLS_ROOT = path.resolve(SKILL_DIR, '..');            // knowledge/skills
const KNOWLEDGE_ROOT = path.resolve(SKILLS_ROOT, '..');       // knowledge
const LOCK_PATH = path.join(KNOWLEDGE_ROOT, 'skills-lock.json');
const LOCK_VERSION = 1;

// ---- tiny helpers ----
function die(msg) { console.error('error: ' + msg); process.exit(1); }
function sh(cmd, args, opts = {}) {
  return execFileSync(cmd, args, { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', ...opts });
}
function rmrf(p) { fs.rmSync(p, { recursive: true, force: true }); }
function mkdtmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'cortex-skill-')); }

function readLock() {
  if (!fs.existsSync(LOCK_PATH)) return { version: LOCK_VERSION, skills: {} };
  try { return JSON.parse(fs.readFileSync(LOCK_PATH, 'utf8')); }
  catch (e) { die('corrupt lockfile ' + LOCK_PATH + ': ' + e.message); }
}
function writeLock(lock) {
  lock.version = LOCK_VERSION;
  fs.writeFileSync(LOCK_PATH, JSON.stringify(lock, null, 2) + '\n');
}

// SHA-256 over every file in a folder (sorted rel path + bytes), excluding VCS/dep dirs.
function hashFolder(dir) {
  const h = crypto.createHash('sha256');
  const files = [];
  (function walk(d, rel) {
    for (const e of fs.readdirSync(d, { withFileTypes: true }).sort((a, b) => a.name < b.name ? -1 : 1)) {
      if (e.name === '.git' || e.name === 'node_modules') continue;
      const abs = path.join(d, e.name);
      const r = rel ? rel + '/' + e.name : e.name;
      if (e.isDirectory()) walk(abs, r);
      else if (e.isFile()) files.push([r, abs]);
    }
  })(dir, '');
  for (const [rel, abs] of files) {
    h.update(rel, 'utf8'); h.update('\0');
    h.update(fs.readFileSync(abs)); h.update('\0');
  }
  return 'sha256:' + h.digest('hex');
}

// Find the skill folder (the dir containing SKILL.md) inside a fetched source.
function findSkillDir(srcRoot, name, explicitPath) {
  const candidates = [];
  if (explicitPath) candidates.push(path.join(srcRoot, explicitPath));
  if (name) candidates.push(path.join(srcRoot, 'skills', name));
  if (name) candidates.push(path.join(srcRoot, name));
  candidates.push(srcRoot);
  for (const c of candidates) {
    if (fs.existsSync(path.join(c, 'SKILL.md'))) return c;
  }
  // last resort: first skills/*/SKILL.md
  const skillsDir = path.join(srcRoot, 'skills');
  if (fs.existsSync(skillsDir)) {
    for (const e of fs.readdirSync(skillsDir, { withFileTypes: true })) {
      if (e.isDirectory() && fs.existsSync(path.join(skillsDir, e.name, 'SKILL.md')))
        return path.join(skillsDir, e.name);
    }
  }
  return null;
}

function nameFromFrontmatter(skillDir, fallback) {
  const md = fs.readFileSync(path.join(skillDir, 'SKILL.md'), 'utf8');
  const m = md.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (m) { const n = m[1].match(/^name:\s*(.+)$/m); if (n) return n[1].trim(); }
  return fallback || path.basename(skillDir);
}

function copyDir(src, dst) {
  rmrf(dst);
  fs.cpSync(src, dst, { recursive: true, filter: (s) => {
    const b = path.basename(s);
    return b !== '.git' && b !== 'node_modules';
  }});
}

// ---- fetch sources into a temp dir, return its root path ----
function fetchGithub(repo, ref) {
  const tmp = mkdtmp();
  const url = `https://github.com/${repo}.git`;
  const args = ['clone', '--depth', '1'];
  if (ref) args.push('--branch', ref);
  args.push(url, tmp);
  sh('git', args);
  return tmp;
}
function fetchGit(url, ref) {
  const tmp = mkdtmp();
  const args = ['clone', '--depth', '1'];
  if (ref) args.push('--branch', ref);
  args.push(url, tmp);
  sh('git', args);
  return tmp;
}
function fetchNpm(pkg) {
  const tmp = mkdtmp();
  // npm pack downloads the tarball; extract it.
  const tgz = sh('npm', ['pack', pkg, '--silent', '--pack-destination', tmp]).trim().split('\n').pop();
  sh('tar', ['-xzf', path.join(tmp, tgz), '-C', tmp]);
  return path.join(tmp, 'package'); // npm tarballs unpack under package/
}

// ---- commands ----
function cmdInstall(argv) {
  const sourceType = argv._[0];
  const source = argv._[1];
  let name = argv._[2] || null;
  if (!sourceType || !source) die('usage: install <github|git|npm> <source> [name] [--ref r] [--path p]');

  let tmpRoot, srcRoot;
  if (sourceType === 'github') { tmpRoot = fetchGithub(source, argv.ref); srcRoot = tmpRoot; }
  else if (sourceType === 'git') { tmpRoot = fetchGit(source, argv.ref); srcRoot = tmpRoot; }
  else if (sourceType === 'npm') { srcRoot = fetchNpm(source); tmpRoot = path.dirname(srcRoot); }
  else die('unknown source type: ' + sourceType + ' (github|git|npm)');

  try {
    const skillDir = findSkillDir(srcRoot, name, argv.path);
    if (!skillDir) die('no SKILL.md found in source (looked in skills/<name>/, <name>/, ./, skills/*/)');
    name = name || nameFromFrontmatter(skillDir, null);

    const dest = path.join(SKILLS_ROOT, name);
    copyDir(skillDir, dest);
    const hash = hashFolder(dest);

    const skillPath = path.relative(srcRoot, skillDir) + '/SKILL.md';
    const lock = readLock();
    lock.skills[name] = {
      source, sourceType,
      ...(argv.ref ? { ref: argv.ref } : {}),
      skillPath: skillPath.replace(/\\/g, '/'),
      computedHash: hash,
    };
    writeLock(lock);
    console.log(`installed ${name} -> knowledge/skills/${name}  (${hash.slice(0, 19)}…)`);
  } finally {
    rmrf(tmpRoot);
  }
}

function cmdVerify(argv) {
  const lock = readLock();
  const names = argv._[0] ? [argv._[0]] : Object.keys(lock.skills);
  let drift = 0;
  for (const n of names) {
    const entry = lock.skills[n];
    if (!entry) { console.log(`?  ${n}: not in lock`); drift++; continue; }
    const dir = path.join(SKILLS_ROOT, n);
    if (!fs.existsSync(dir)) { console.log(`MISSING ${n}: folder gone`); drift++; continue; }
    const cur = hashFolder(dir);
    if (cur === entry.computedHash) console.log(`OK  ${n}`);
    else { console.log(`DRIFT ${n}: lock ${entry.computedHash.slice(0,19)}… vs disk ${cur.slice(0,19)}…`); drift++; }
  }
  if (drift) process.exit(1);
}

function cmdRestore(argv) {
  const lock = readLock();
  const names = argv._[0] ? [argv._[0]] : Object.keys(lock.skills);
  for (const n of names) {
    const e = lock.skills[n];
    if (!e) die('not in lock: ' + n);
    console.log(`restoring ${n} from ${e.sourceType}:${e.source}${e.ref ? '@' + e.ref : ''}`);
    cmdInstall({ _: [e.sourceType, e.source, n], ref: e.ref, path: e.skillPath.replace(/\/SKILL\.md$/, '') });
  }
}

function cmdRemove(argv) {
  const name = argv._[0];
  if (!name) die('usage: remove <name>');
  rmrf(path.join(SKILLS_ROOT, name));
  const lock = readLock();
  delete lock.skills[name];
  writeLock(lock);
  console.log('removed ' + name);
}

function cmdList() {
  const lock = readLock();
  const names = Object.keys(lock.skills);
  if (!names.length) { console.log('(no skills in lock)'); return; }
  for (const n of names) {
    const e = lock.skills[n];
    console.log(`${n}\t${e.sourceType}:${e.source}${e.ref ? '@' + e.ref : ''}`);
  }
}

// ---- minimal arg parse (flags: --ref, --path; rest positional) ----
function parse(args) {
  const out = { _: [] };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '--ref') out.ref = args[++i];
    else if (a === '--path') out.path = args[++i];
    else out._.push(a);
  }
  return out;
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const argv = parse(rest);
  switch (cmd) {
    case 'install': return cmdInstall(argv);
    case 'verify': return cmdVerify(argv);
    case 'restore': return cmdRestore(argv);
    case 'remove': return cmdRemove(argv);
    case 'list': return cmdList();
    default: die('commands: install | verify | restore | remove | list');
  }
}
main();
