import { afterEach, describe, expect, test } from "bun:test";
import fs from "fs";
import os from "os";
import path from "path";

import { buildInventory, listProjects } from "../scripts/cortex-inventory.js";

function makeInventoryFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cortex-inv-root-"));

  // Builtin skill + agent
  const builtinSkill = path.join(root, "knowledge", "skills", "builtin-skill");
  fs.mkdirSync(builtinSkill, { recursive: true });
  fs.writeFileSync(path.join(builtinSkill, "SKILL.md"), "---\nname: builtin-skill\n---\n\nbuiltin\n");
  fs.mkdirSync(path.join(root, "knowledge", "agents"), { recursive: true });
  fs.writeFileSync(path.join(root, "knowledge", "agents", "builtin-agent.md"), "# builtin-agent\n");

  // External skill + agent (plus lock files that must be filtered out)
  const extSkill = path.join(root, "skills", "ext-skill");
  fs.mkdirSync(extSkill, { recursive: true });
  fs.writeFileSync(path.join(extSkill, "SKILL.md"), "---\nname: ext-skill\n---\n\nexternal\n");
  fs.writeFileSync(path.join(root, "skills", "skills-lock.json"), '{"version":1,"items":{}}\n');
  fs.mkdirSync(path.join(root, "agents"), { recursive: true });
  fs.writeFileSync(path.join(root, "agents", "ext-agent.md"), "# ext-agent\n");
  fs.writeFileSync(path.join(root, "agents", "agents-lock.json"), '{"version":1,"items":{}}\n');

  // Generated tool dirs (empty is fine; shape still present)
  for (const dir of [
    ".claude/skills",
    ".agents/skills",
    ".claude/agents",
    ".cursor/agents",
    ".opencode/agent",
  ]) {
    fs.mkdirSync(path.join(root, dir), { recursive: true });
  }

  // Projects: one with .git, one without; plus worktree sibling
  const demo = path.join(root, "repositories", "demo");
  fs.mkdirSync(path.join(demo, ".git"), { recursive: true });
  fs.writeFileSync(path.join(demo, "README.md"), "demo\n");

  const bare = path.join(root, "repositories", "bare");
  fs.mkdirSync(bare, { recursive: true });
  fs.writeFileSync(path.join(bare, "README.md"), "bare\n");

  const wt = path.join(root, "repositories", "demo.worktrees", "feat-x");
  fs.mkdirSync(wt, { recursive: true });
  fs.writeFileSync(path.join(wt, "note.txt"), "worktree\n");

  return root;
}

describe("cortex-inventory", () => {
  const tmpDirs = [];

  afterEach(() => {
    while (tmpDirs.length) {
      fs.rmSync(tmpDirs.pop(), { recursive: true, force: true });
    }
  });

  test("buildInventory(root) is importable and returns --json shape keys", () => {
    const root = makeInventoryFixture();
    tmpDirs.push(root);

    const inv = buildInventory(root);

    expect(path.resolve(String(inv.root))).toBe(path.resolve(root));
    expect(inv.resources).toEqual(expect.any(Object));
    expect(inv.projects).toEqual(expect.any(Object));
    for (const key of ["root", "resources", "projects"]) {
      expect(inv).toHaveProperty(key);
    }
  });

  test("buildInventory(root) lists builtin/external and filters *-lock.json", () => {
    const root = makeInventoryFixture();
    tmpDirs.push(root);

    const inv = buildInventory(root);
    const skillNames = {
      builtin: inv.resources.skills.builtin.map((item) => item.name),
      external: inv.resources.skills.external.map((item) => item.name),
    };
    const agentNames = {
      builtin: inv.resources.agents.builtin.map((item) => item.name),
      external: inv.resources.agents.external.map((item) => item.name),
    };

    expect(skillNames.builtin).toContain("builtin-skill");
    expect(skillNames.external).toContain("ext-skill");
    expect(skillNames.external).not.toContain("skills-lock");
    expect(skillNames.external.some((n) => n.includes("lock"))).toBe(false);

    expect(agentNames.builtin).toContain("builtin-agent");
    expect(agentNames.external).toContain("ext-agent");
    expect(agentNames.external).not.toContain("agents-lock");
    expect(agentNames.external.some((n) => n.includes("lock"))).toBe(false);
  });

  test("listProjects(root) parses worktrees and hasGit", () => {
    const root = makeInventoryFixture();
    tmpDirs.push(root);

    const projects = listProjects(root);

    expect(projects.repositories).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: "demo", hasGit: true }),
        expect.objectContaining({ name: "bare", hasGit: false }),
      ]),
    );
    expect(projects.worktrees).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          repository: "demo",
          name: "feat-x",
          path: expect.stringContaining(path.join("repositories", "demo.worktrees", "feat-x")),
        }),
      ]),
    );

    // Same data must surface through buildInventory.
    const inv = buildInventory(root);
    expect(inv.projects.repositories).toEqual(projects.repositories);
    expect(inv.projects.worktrees).toEqual(projects.worktrees);
  });
});
