import { describe, expect, test } from "bun:test";

import {
  CortexMemError,
  VECTOR_SIZE,
  buildFilter,
  containsSensitiveData,
  embedText,
  extractMemory,
  memoryToPoint,
  parseArgs,
  qdrantPaths,
} from "../scripts/cortex-mem.js";

const validMemory = {
  summary: "在 agent-cortex 中，cortex-mem 使用本地 Qdrant 作为跨会话记忆的语义索引。",
  scope: {
    repo: "agent-cortex",
    runtime: "cursor",
  },
  kind: "decision",
  evidence: [
    {
      type: "file",
      ref: "knowledge/skills/cortex-mem/SKILL.md",
      note: "skill 明确要求本地 Qdrant",
    },
  ],
  tags: ["cortex-mem", "qdrant"],
  confidence: 0.94,
  expires_at: null,
};

describe("cortex-mem", () => {
  test("parseArgs parses scoped search filters", () => {
    const args = parseArgs([
      "search",
      "--query",
      "之前怎么设计 memory",
      "--repo",
      "agent-cortex",
      "--kind",
      "decision",
      "--tag",
      "qdrant",
      "--file",
      "README.md",
      "--limit",
      "3",
    ]);

    expect(args.command).toBe("search");
    expect(args.query).toBe("之前怎么设计 memory");
    expect(args.repo).toBe("agent-cortex");
    expect(args.kind).toBe("decision");
    expect(args.tags).toEqual(["qdrant"]);
    expect(args.files).toEqual(["README.md"]);
    expect(args.limit).toBe(3);
  });

  test("parseArgs supports managed Qdrant startup", () => {
    const args = parseArgs(["qdrant-start", "--url", "http://127.0.0.1:6335", "--grpc-port", "6336"]);

    expect(args.command).toBe("qdrant-start");
    expect(args.url).toBe("http://127.0.0.1:6335");
    expect(args.grpcPort).toBe(6336);
  });

  test("qdrantPaths keeps runtime files under .cortex-mem", () => {
    const paths = qdrantPaths();

    expect(paths.runtime_dir.endsWith("/.cortex-mem/qdrant")).toBe(true);
    expect(paths.storage_dir.endsWith("/.cortex-mem/qdrant/storage")).toBe(true);
    expect(paths.log_file.endsWith("/.cortex-mem/qdrant/logs/qdrant.log")).toBe(true);
    expect(paths.pid_file.endsWith("/.cortex-mem/qdrant/qdrant.pid")).toBe(true);
  });

  test("embedText returns normalized fixed-size vectors", () => {
    const vector = embedText("Qdrant semantic memory 语义记忆");

    expect(vector).toHaveLength(VECTOR_SIZE);
    expect(vector.some((value) => value !== 0)).toBe(true);
    const norm = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
    expect(norm).toBeCloseTo(1, 6);
  });

  test("buildFilter maps scope fields to Qdrant filter clauses", () => {
    expect(
      buildFilter({
        repo: "agent-cortex",
        project: "memory",
        kind: "decision",
        tags: ["qdrant"],
        files: ["README.md"],
      }),
    ).toEqual({
      must: [
        { key: "scope.repo", match: { value: "agent-cortex" } },
        { key: "scope.project", match: { value: "memory" } },
        { key: "kind", match: { value: "decision" } },
        { key: "tags", match: { value: "qdrant" } },
        { key: "files", match: { value: "README.md" } },
      ],
    });
  });

  test("extractMemory accepts curator envelope", () => {
    const extracted = extractMemory({
      should_remember: true,
      memory: validMemory,
      rejection_reason: null,
    });

    expect(extracted.summary).toBe(validMemory.summary);
  });

  test("extractMemory rejects sensitive-looking fields", () => {
    expect(containsSensitiveData({ api_key: "redacted" })).toBe(true);
    expect(() =>
      extractMemory({
        ...validMemory,
        evidence: [{ type: "user", ref: "chat", note: "token: sk-123456789012345678901234" }],
      }),
    ).toThrow(CortexMemError);
  });

  test("memoryToPoint builds Qdrant point payload", () => {
    const point = memoryToPoint(validMemory, new Date("2026-06-24T00:00:00.000Z"));

    expect(point.id).toBeTruthy();
    expect(point.vector).toHaveLength(VECTOR_SIZE);
    expect(point.payload.summary).toBe(validMemory.summary);
    expect(point.payload.scope.repo).toBe("agent-cortex");
    expect(point.payload.files).toEqual(["knowledge/skills/cortex-mem/SKILL.md"]);
    expect(point.payload.created_at).toBe("2026-06-24T00:00:00.000Z");
  });
});
