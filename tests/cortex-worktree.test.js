import { afterEach, describe, expect, test } from "bun:test";
import fs from "fs";
import os from "os";
import path from "path";
import { spawnSync } from "child_process";

import { cmdAdd, cmdStatus, cmdRelease } from "../scripts/worktree.js";

function runGit(cwd, args) {
  // File redirect: bun test under workspace cwd may drop spawnSync pipes
  // (same pattern as tests/submit-pr.test.js).
  const id = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const outFile = path.join(os.tmpdir(), `cortex-wt-out-${id}.txt`);
  const errFile = path.join(os.tmpdir(), `cortex-wt-err-${id}.txt`);
  const quote = (value) => `'${String(value).replaceAll("'", `'\"'\"'`)}'`;
  try {
    const shellCmd = `git ${args.map(quote).join(" ")} >${quote(outFile)} 2>${quote(errFile)}`;
    const result = spawnSync("sh", ["-c", shellCmd], {
      cwd,
      encoding: "utf8",
      env: {
        ...process.env,
        GIT_AUTHOR_NAME: "cortex-worktree-test",
        GIT_AUTHOR_EMAIL: "cortex-worktree-test@example.com",
        GIT_COMMITTER_NAME: "cortex-worktree-test",
        GIT_COMMITTER_EMAIL: "cortex-worktree-test@example.com",
      },
    });
    const stdout = fs.existsSync(outFile) ? fs.readFileSync(outFile, "utf8") : "";
    const stderr = fs.existsSync(errFile) ? fs.readFileSync(errFile, "utf8") : "";
    if (result.status !== 0) {
      const detail = (stderr || stdout || `exit ${result.status}`).trim();
      throw new Error(`git ${args.join(" ")} failed: ${detail}`);
    }
    return stdout.trimEnd();
  } finally {
    fs.rmSync(outFile, { force: true });
    fs.rmSync(errFile, { force: true });
  }
}

function makeFixtureRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cortex-wt-root-"));
  const repo = path.join(root, "repositories", "demo");
  fs.mkdirSync(repo, { recursive: true });
  runGit(repo, ["init", "-b", "main"]);
  fs.writeFileSync(path.join(repo, "README.md"), "demo\n");
  runGit(repo, ["add", "README.md"]);
  runGit(repo, ["commit", "-m", "init"]);
  return { root, repo };
}

function withStubGh(binDir, behavior) {
  fs.mkdirSync(binDir, { recursive: true });
  const ghPath = path.join(binDir, "gh");
  const script = `#!/usr/bin/env bash
set -euo pipefail
cmd="\${1:-}"
sub="\${2:-}"
if [[ "$cmd" == "pr" && "$sub" == "view" ]]; then
  ${behavior.view}
fi
if [[ "$cmd" == "pr" && "$sub" == "checks" ]]; then
  ${behavior.checks}
fi
echo "unexpected gh args: $*" >&2
exit 99
`;
  fs.writeFileSync(ghPath, script, { mode: 0o755 });
  return {
    ...process.env,
    PATH: `${binDir}${path.delimiter}${process.env.PATH || ""}`,
  };
}

describe("cortex worktree", () => {
  const tmpDirs = [];

  afterEach(() => {
    while (tmpDirs.length) {
      fs.rmSync(tmpDirs.pop(), { recursive: true, force: true });
    }
  });

  test("add creates sibling repositories/<repo>.worktrees/<branch>", () => {
    const { root, repo } = makeFixtureRoot();
    tmpDirs.push(root);

    const branch = "feat/login";
    const wtPath = path.join(root, "repositories", "demo.worktrees", branch);

    cmdAdd({ repo: "demo", branch, root });

    expect(fs.existsSync(path.join(wtPath, ".git"))).toBe(true);
    expect(runGit(wtPath, ["rev-parse", "--abbrev-ref", "HEAD"])).toBe(branch);
    expect(runGit(repo, ["worktree", "list"]).includes(wtPath)).toBe(true);
  });

  test("add onto an existing worktree path exits with error", () => {
    const { root } = makeFixtureRoot();
    tmpDirs.push(root);

    const branch = "feat/dup";
    const wtPath = path.join(root, "repositories", "demo.worktrees", branch);
    fs.mkdirSync(wtPath, { recursive: true });

    expect(() => cmdAdd({ repo: "demo", branch, root })).toThrow();
  });

  test("status with no PR yields pr: null", () => {
    const { root } = makeFixtureRoot();
    tmpDirs.push(root);

    const branch = "feat/status";
    cmdAdd({ repo: "demo", branch, root });

    const binDir = path.join(root, "bin");
    tmpDirs.push(binDir);
    const env = withStubGh(binDir, {
      view: 'echo "no pull requests found" >&2; exit 1',
      checks: 'echo "no checks" >&2; exit 1',
    });

    const result = cmdStatus({ repo: "demo", branch, root, env, json: true });
    expect(result.repo).toBe("demo");
    expect(result.branch).toBe(branch);
    expect(result.worktree_path).toBe(
      path.join(root, "repositories", "demo.worktrees", branch),
    );
    expect(result.pr).toBeNull();
    expect(result).toHaveProperty("checks");
    expect(result).toHaveProperty("ok");
  });

  test("release without --yes exits 1 and keeps worktree", () => {
    const { root } = makeFixtureRoot();
    tmpDirs.push(root);

    const branch = "feat/gated";
    cmdAdd({ repo: "demo", branch, root });
    const wtPath = path.join(root, "repositories", "demo.worktrees", branch);

    let thrown = null;
    try {
      cmdRelease({ repo: "demo", branch, root });
    } catch (error) {
      thrown = error;
    }
    expect(thrown).toBeTruthy();
    expect(thrown.exitCode === 1 || thrown.code === 1 || /--yes/i.test(String(thrown.message))).toBe(
      true,
    );
    expect(fs.existsSync(wtPath)).toBe(true);
  });

  test("release with --yes removes worktree and deletes merged branch", () => {
    const { root, repo } = makeFixtureRoot();
    tmpDirs.push(root);

    const branch = "feat/done";
    cmdAdd({ repo: "demo", branch, root });
    const wtPath = path.join(root, "repositories", "demo.worktrees", branch);

    fs.writeFileSync(path.join(wtPath, "done.txt"), "merged\n");
    runGit(wtPath, ["add", "done.txt"]);
    runGit(wtPath, ["commit", "-m", "feat done"]);
    runGit(repo, ["merge", "--no-ff", branch, "-m", "merge feat/done"]);

    cmdRelease({ repo: "demo", branch, root, yes: true });

    expect(fs.existsSync(wtPath)).toBe(false);
    const branches = runGit(repo, ["branch", "--list", branch]);
    expect(branches.trim()).toBe("");
  });
});
