#!/usr/bin/env bun
// cli.js — cortex CLI entrypoint. Runtime: bun (ESM).
//
//   cortex install                                   bootstrap: relink + restore externals
//   cortex install <skill|agent> <github|git|npm> <source> [name] [--ref r] [--path p]
//   cortex uninstall <name>                          remove an external resource
//   cortex refresh <name> [--dry-run]                 re-fetch one external from lock
//   cortex relink                                    rebuild all tool symlinks
//   cortex verify [name]                             check on-disk hashes vs lock
//   cortex list                                      list builtin + external
//   cortex repo clone|init …                         repositories/ placement
//   cortex worktree add|status|release …             <repo>.worktrees/<branch>

import { die } from './resource.js';
import { cmdInstall, cmdUninstall, cmdRefresh, cmdRelink, cmdVerify, cmdList } from './commands.js';
import { cmdRepo } from './repo.js';
import { cmdWorktree } from './worktree.js';

function parse(args) {
  const o = { _: [] };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '--ref') o.ref = args[++i];
    else if (a === '--path') o.path = args[++i];
    else if (a === '--name') o.name = args[++i];
    else if (a === '--dry-run') o.dryRun = true;
    else if (a === '--repo') o.repo = args[++i];
    else if (a === '--branch') o.branch = args[++i];
    else if (a === '--base') o.base = args[++i];
    else if (a === '--yes') o.yes = true;
    else if (a === '--force') o.force = true;
    else if (a === '--json') o.json = true;
    else o._.push(a);
  }
  return o;
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const argv = parse(rest);
  switch (cmd) {
    case 'install': return cmdInstall(argv);
    case 'uninstall': return cmdUninstall(argv);
    case 'refresh': return cmdRefresh(argv);
    case 'relink': return cmdRelink();
    case 'verify': return cmdVerify(argv);
    case 'list': return cmdList();
    case 'repo': return cmdRepo(argv);
    case 'worktree': return cmdWorktree(argv);
    default: die('commands: install | uninstall | refresh | relink | verify | list | repo | worktree');
  }
}
main();
