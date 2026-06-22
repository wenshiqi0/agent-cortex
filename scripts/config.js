// config.js — roots + per-kind layout for the cortex CLI. Runtime: bun (ESM).
//
// Two kinds of resource, two origins:
//   builtin  : ships with the template, lives in knowledge/{skills,agents}/, tracked by git.
//   external : installed from a source, lives in ./{skills,agents}/, gitignored.
//
// Tools scan a single flat directory per resource. Each tool dir is a REAL folder
// holding one symlink per resource, pointing at builtin (knowledge/) or external (./).

import path from 'path';

// Script lives at scripts/, so ROOT is one level up.
export const ROOT = path.resolve(import.meta.dir, '..');     // agent-cortex/
export const KNOWLEDGE = path.join(ROOT, 'knowledge');       // knowledge/
export const LOCK_VERSION = 1;

export const KIND = {
  skill: {
    builtinDir: path.join(KNOWLEDGE, 'skills'),
    externalDir: path.join(ROOT, 'skills'),
    lock: path.join(ROOT, 'skills', 'skills-lock.json'),
    toolDirs: [path.join(ROOT, '.claude', 'skills'), path.join(ROOT, '.agents', 'skills')],
    kind: 'folder',                 // <name>/ containing SKILL.md
    entryName: (name) => name,      // link/dir name
  },
  agent: {
    builtinDir: path.join(KNOWLEDGE, 'agents'),
    externalDir: path.join(ROOT, 'agents'),
    lock: path.join(ROOT, 'agents', 'agents-lock.json'),
    toolDirs: [
      path.join(ROOT, '.claude', 'agents'),
      path.join(ROOT, '.cursor', 'agents'),
      path.join(ROOT, '.opencode', 'agent'),
    ],
    kind: 'file',                   // <name>.md
    entryName: (name) => name + '.md',
  },
};
