#!/usr/bin/env bun
// Print agent-cortex resources from explicit filesystem paths, including
// gitignored directories that repo-wide search commonly skips.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { ROOT, KIND } from './config.js';

function usage() {
  console.log(`usage: scripts/cortex-inventory.js [--json]

Lists currently available agent-cortex resources from explicit paths:
  - builtin and external skills
  - builtin and external agents
  - generated tool links
  - repositories and feature worktrees

Use this before grep/search when looking for skills, agents, or projects.`);
}

function exists(p) {
  return fs.existsSync(p);
}

function kindAt(root = ROOT) {
  if (root === ROOT) return KIND;
  const knowledge = path.join(root, 'knowledge');
  return {
    skill: {
      builtinDir: path.join(knowledge, 'skills'),
      externalDir: path.join(root, 'skills'),
      lock: path.join(root, 'skills', 'skills-lock.json'),
      toolDirs: [path.join(root, '.claude', 'skills'), path.join(root, '.agents', 'skills')],
      kind: 'folder',
      entryName: (name) => name,
    },
    agent: {
      builtinDir: path.join(knowledge, 'agents'),
      externalDir: path.join(root, 'agents'),
      lock: path.join(root, 'agents', 'agents-lock.json'),
      toolDirs: [
        path.join(root, '.claude', 'agents'),
        path.join(root, '.cursor', 'agents'),
        path.join(root, '.opencode', 'agent'),
      ],
      kind: 'file',
      entryName: (name) => name + '.md',
    },
  };
}

function rel(p, root = ROOT) {
  return path.relative(root, p) || '.';
}

function sortedDirEntries(dir) {
  if (!exists(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true })
    .sort((a, b) => a.name.localeCompare(b.name));
}

function lstatKind(p) {
  const st = fs.lstatSync(p, { throwIfNoEntry: false });
  if (!st) return 'missing';
  if (st.isSymbolicLink()) return 'symlink';
  if (st.isDirectory()) return 'directory';
  if (st.isFile()) return 'file';
  return 'other';
}

function listResourceDir(dir, cfg, root) {
  const isFile = cfg.kind === 'file';
  return sortedDirEntries(dir)
    .filter((entry) => {
      if (entry.name.endsWith('-lock.json')) return false;
      return isFile ? entry.isFile() && entry.name.endsWith('.md') : entry.isDirectory();
    })
    .map((entry) => {
      const fullPath = path.join(dir, entry.name);
      return {
        name: isFile ? entry.name.slice(0, -3) : entry.name,
        path: rel(fullPath, root),
        kind: lstatKind(fullPath),
      };
    });
}

function listGeneratedDir(dir, cfg, root) {
  const isFile = cfg.kind === 'file';
  return sortedDirEntries(dir)
    .filter((entry) => isFile ? entry.name.endsWith('.md') : true)
    .map((entry) => {
      const fullPath = path.join(dir, entry.name);
      const item = {
        name: isFile ? entry.name.replace(/\.md$/, '') : entry.name,
        path: rel(fullPath, root),
        kind: lstatKind(fullPath),
      };
      if (item.kind === 'symlink') item.target = fs.readlinkSync(fullPath);
      return item;
    });
}

function listResources(root = ROOT) {
  const resources = {};
  for (const [kind, cfg] of Object.entries(kindAt(root))) {
    resources[kind + 's'] = {
      builtin: listResourceDir(cfg.builtinDir, cfg, root),
      external: listResourceDir(cfg.externalDir, cfg, root),
      generated: cfg.toolDirs.map((dir) => ({
        path: rel(dir, root),
        entries: listGeneratedDir(dir, cfg, root),
      })),
    };
  }
  return resources;
}

export function listProjects(root = ROOT) {
  const reposDir = path.join(root, 'repositories');
  const entries = sortedDirEntries(reposDir).filter((entry) => entry.isDirectory());
  const repositories = [];
  const worktrees = [];

  for (const entry of entries) {
    const fullPath = path.join(reposDir, entry.name);
    if (entry.name.endsWith('.worktrees')) {
      for (const wt of sortedDirEntries(fullPath).filter((candidate) => candidate.isDirectory())) {
        worktrees.push({
          repository: entry.name.slice(0, -'.worktrees'.length),
          name: wt.name,
          path: rel(path.join(fullPath, wt.name), root),
        });
      }
      continue;
    }

    repositories.push({
      name: entry.name,
      path: rel(fullPath, root),
      hasGit: exists(path.join(fullPath, '.git')),
    });
  }

  return {
    root: rel(reposDir, root),
    repositories,
    worktrees,
  };
}

export function buildInventory(root = ROOT) {
  return {
    root,
    resources: listResources(root),
    projects: listProjects(root),
    searchRule: 'Search these explicit paths directly; do not rely on repo-wide grep/search that respects .gitignore.',
  };
}

function printResourceGroup(title, group) {
  console.log(`# ${title}`);
  for (const origin of ['builtin', 'external']) {
    console.log(`## ${origin}`);
    if (group[origin].length === 0) console.log('  (none)');
    for (const item of group[origin]) console.log(`  ${item.name}\t${item.path}`);
  }
  console.log('## generated');
  for (const toolDir of group.generated) {
    console.log(`  ${toolDir.path}`);
    if (toolDir.entries.length === 0) console.log('    (none)');
    for (const item of toolDir.entries) {
      const target = item.target ? ` -> ${item.target}` : '';
      console.log(`    ${item.name}\t${item.path}${target}`);
    }
  }
}

function printText(inv) {
  console.log(`# agent-cortex inventory`);
  console.log(`root: ${inv.root}`);
  console.log('');
  printResourceGroup('skills', inv.resources.skills);
  console.log('');
  printResourceGroup('agents', inv.resources.agents);
  console.log('');
  console.log('# projects');
  console.log(`root: ${inv.projects.root}`);
  console.log('## repositories');
  if (inv.projects.repositories.length === 0) console.log('  (none)');
  for (const repo of inv.projects.repositories) {
    console.log(`  ${repo.name}\t${repo.path}${repo.hasGit ? '\t[git]' : ''}`);
  }
  console.log('## worktrees');
  if (inv.projects.worktrees.length === 0) console.log('  (none)');
  for (const wt of inv.projects.worktrees) {
    console.log(`  ${wt.repository}:${wt.name}\t${wt.path}`);
  }
  console.log('');
  console.log(inv.searchRule);
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help') || args.includes('-h')) return usage();
  const json = args.includes('--json');
  const unknown = args.filter((arg) => arg !== '--json');
  if (unknown.length) {
    console.error(`error: unknown option ${unknown[0]}`);
    usage();
    process.exit(1);
  }

  const inventory = buildInventory();
  if (json) console.log(JSON.stringify(inventory, null, 2));
  else printText(inventory);
}

const isCli = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isCli) main();
