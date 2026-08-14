import { afterEach, describe, expect, test } from "bun:test";
import fs from "fs";
import os from "os";
import path from "path";
import { spawnSync } from "child_process";

import {
  SubmitPrError,
  appendUpdate,
  buildCommandPlan,
  isSensitivePath,
  parseArgs,
  prepare,
  validatePaths,
} from "../scripts/submit-pr.js";

function runGit(cwd, args) {
  const id = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const outFile = path.join(os.tmpdir(), `submit-pr-test-out-${id}.txt`);
  const errFile = path.join(os.tmpdir(), `submit-pr-test-err-${id}.txt`);
  const quote = (value) => `'${String(value).replaceAll("'", `'\"'\"'`)}'`;
  try {
    const shellCmd = `git ${args.map(quote).join(" ")} >${quote(outFile)} 2>${quote(errFile)}`;
    const result = spawnSync("sh", ["-c", shellCmd], {
      cwd,
      encoding: "utf8",
      env: {
        ...process.env,
        GIT_AUTHOR_NAME: "submit-pr-test",
        GIT_AUTHOR_EMAIL: "submit-pr-test@example.com",
        GIT_COMMITTER_NAME: "submit-pr-test",
        GIT_COMMITTER_EMAIL: "submit-pr-test@example.com",
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

function makePrepareFixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "submit-pr-prepare-"));
  runGit(dir, ["init", "-b", "main"]);

  fs.writeFileSync(path.join(dir, "staged.txt"), "staged-v1\n");
  fs.writeFileSync(path.join(dir, "unstaged.txt"), "unstaged-v1\n");
  fs.writeFileSync(path.join(dir, ".env"), "SECRET=initial\n");
  runGit(dir, ["add", "--", "staged.txt", "unstaged.txt", ".env"]);
  runGit(dir, ["commit", "-m", "init fixture"]);
  runGit(dir, ["commit", "--allow-empty", "-m", "second commit"]);
  runGit(dir, ["commit", "--allow-empty", "-m", "third commit"]);

  fs.writeFileSync(path.join(dir, "staged.txt"), "staged-v2\n");
  runGit(dir, ["add", "--", "staged.txt"]);
  fs.writeFileSync(path.join(dir, "unstaged.txt"), "unstaged-v2\n");
  fs.writeFileSync(path.join(dir, ".env"), "SECRET=changed\n");

  return dir;
}

describe("submit-pr", () => {
  test("parseArgs requires explicit paths", () => {
    const args = parseArgs([
      "--title",
      "feat: add stable PR submission",
      "--body-file",
      "/tmp/body.md",
      "--commit-message",
      "feat: add stable PR submission",
      "--path",
      "knowledge/skills/submitting-prs/SKILL.md",
      "--path",
      "scripts/submit-pr.js",
    ]);

    expect(args.title).toBe("feat: add stable PR submission");
    expect(args.paths).toEqual([
      "knowledge/skills/submitting-prs/SKILL.md",
      "scripts/submit-pr.js",
    ]);

    expect(() =>
      parseArgs([
        "--title",
        "feat: add stable PR submission",
        "--body-file",
        "/tmp/body.md",
        "--commit-message",
        "feat: add stable PR submission",
      ]),
    ).toThrow(SubmitPrError);
  });

  test("sensitive paths are rejected unless explicitly allowed", () => {
    const paths = [
      "app/.env",
      "config/credentials.json",
      "secrets/service-account.json",
      "deploy/private.key",
      "ssh/id_rsa",
      "certs/prod.pem",
    ];

    for (const path of paths) {
      expect(isSensitivePath(path)).toBe(true);
    }

    validatePaths(["src/app.js"], false);
    expect(() => validatePaths(["src/app.js", "app/.env"], false)).toThrow(SubmitPrError);
    validatePaths(["src/app.js", "app/.env"], true);
  });

  test("appendUpdate preserves existing body", () => {
    const existingBody = "## Summary\n- Add initial flow\n\n## Test plan\n- bun test\n";
    const updateBody = "## Summary\n- Add Bun submit script\n\n## Test plan\n- bun test tests/submit-pr.test.js\n";

    const merged = appendUpdate(existingBody, updateBody, "2026-06-24 11:15 +0800");

    expect(merged).toContain(existingBody);
    expect(merged).toContain("## Updates");
    expect(merged).toContain("### 2026-06-24 11:15 +0800");
    expect(merged).toContain(updateBody);
  });

  test("appendUpdate adds to existing updates section", () => {
    const existingBody =
      "## Summary\n- Add initial flow\n\n" +
      "## Updates\n\n" +
      "### 2026-06-24 10:00 +0800\n" +
      "First update\n";

    const merged = appendUpdate(existingBody, "Second update\n", "2026-06-24 11:15 +0800");

    expect(merged.match(/## Updates/g)).toHaveLength(1);
    expect(merged).toContain("First update");
    expect(merged).toContain("Second update");
  });

  test("dry-run plan contains git and gh steps", () => {
    const args = {
      title: "feat: add stable PR submission",
      bodyFile: "/tmp/body.md",
      commitMessage: "feat: add stable PR submission",
      paths: ["knowledge/skills/submitting-prs/SKILL.md"],
      base: null,
      draft: false,
      dryRun: true,
      allowSensitive: false,
    };

    const plan = buildCommandPlan(args, "feat/stable-pr-skill", false);

    expect(plan[0]).toEqual(["git", "add", "--", "knowledge/skills/submitting-prs/SKILL.md"]);
    expect(plan).toContainEqual(["git", "commit", "-m", "feat: add stable PR submission"]);
    expect(plan).toContainEqual(["git", "push", "-u", "origin", "HEAD"]);
    expect(plan.at(-1).slice(0, 3)).toEqual(["gh", "pr", "create"]);
  });
});

describe("submit-pr prepare", () => {
  const tmpDirs = [];

  afterEach(() => {
    while (tmpDirs.length) {
      const dir = tmpDirs.pop();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("prepare returns stable JSON with staged+unstaged diff and sensitive flags", () => {
    const dir = makePrepareFixture();
    tmpDirs.push(dir);

    const paths = ["staged.txt", "unstaged.txt", ".env"];
    const statusBefore = runGit(dir, ["status", "--short", "--", ...paths]);
    const expectedDiff = runGit(dir, ["diff", "HEAD", "--", ...paths]);
    const expectedLog = runGit(dir, ["log", "-5", "--oneline"]);

    const result = prepare({ paths, cwd: dir });

    expect(Object.keys(result).sort()).toEqual([
      "branch",
      "diff",
      "log",
      "paths",
      "sensitive_flags",
      "status",
      "status_short",
    ]);
    expect(result.status).toBe("prepare");
    expect(result.branch).toBe("main");
    expect(result.paths).toEqual(paths);
    expect(result.sensitive_flags).toEqual({
      "staged.txt": false,
      "unstaged.txt": false,
      ".env": true,
    });
    expect(typeof result.status_short).toBe("string");
    expect(result.status_short).toContain("staged.txt");
    expect(result.status_short).toContain("unstaged.txt");
    expect(result.status_short).toContain(".env");
    expect(result.diff).toBe(expectedDiff);
    expect(result.log).toBe(expectedLog);

    // git diff HEAD includes staged AND unstaged changes.
    expect(result.diff).toContain("staged-v2");
    expect(result.diff).toContain("unstaged-v2");
    expect(result.diff).toContain("SECRET=changed");
    expect(result.log.split("\n")).toHaveLength(3);
    expect(result.log).toContain("third commit");

    // Read-only: index and worktree must be unchanged.
    expect(runGit(dir, ["status", "--short", "--", ...paths])).toBe(statusBefore);
    expect(runGit(dir, ["diff", "--cached", "--", "staged.txt"])).toContain("staged-v2");
    expect(runGit(dir, ["diff", "--", "unstaged.txt"])).toContain("unstaged-v2");
  });

  test("prepare rejects broad and absolute paths", () => {
    const dir = makePrepareFixture();
    tmpDirs.push(dir);

    try {
      prepare({ paths: ["."], cwd: dir });
      throw new Error("expected prepare to reject broad path");
    } catch (error) {
      expect(error).toBeInstanceOf(SubmitPrError);
      expect(error.message).toMatch(/broad|ambiguous/i);
    }

    try {
      prepare({ paths: ["/tmp/absolute.txt"], cwd: dir });
      throw new Error("expected prepare to reject absolute path");
    } catch (error) {
      expect(error).toBeInstanceOf(SubmitPrError);
      expect(error.message).toMatch(/relative/i);
    }
  });
});
