import { describe, expect, test } from "bun:test";

import {
  SubmitPrError,
  appendUpdate,
  buildCommandPlan,
  isSensitivePath,
  parseArgs,
  validatePaths,
} from "../scripts/submit-pr.js";

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
