// Optional interoperability check using the official TypeScript SDK, without server dependencies.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const prefix = process.argv[2];
assert(prefix, "Pass the npm installation prefix containing @modelcontextprotocol/sdk");
const require = createRequire(join(resolve(prefix), "package.json"));
const { Client } = require("@modelcontextprotocol/sdk/client/index.js");
const { StdioClientTransport } = require("@modelcontextprotocol/sdk/client/stdio.js");
const tests = dirname(fileURLToPath(import.meta.url));
const cwd = await mkdtemp(join(tmpdir(), "ntu-mcp-client-"));
const transport = new StdioClientTransport({
  command: "python",
  args: [join(tests, "protocol_server.py")], cwd,
  env: { PYTHONPATH: join(tests, "..", "src"), NTU_WISH_USERNAME: "", NTU_WISH_PASSWORD: "" },
});
const client = new Client({ name: "ntu-typescript-test", version: "1.0" });
try {
  await client.connect(transport);
  const { tools } = await client.listTools();
  assert.equal(tools.length, 12);
  for (const tool of tools) {
    assert.equal(tool.outputSchema.type, "object");
    assert(Object.keys(tool.outputSchema.properties).length > 0);
  }
  const args = { course_code: "SC2001", academic_year: 2026, semester: 1 };
  for (const [name, parameters] of [
    ["search_courses", { query: "SC20", academic_year: 2026, semester: 1, limit: 2 }],
    ["get_course_metadata", args], ["get_course_indexes", args],
    ["get_index", { ...args, index: "10143" }],
    ["compare_indexes", { ...args, indexes: ["10143", "10144"] }],
    ["find_matching_indexes", args],
    ["get_graduate_course_schedule", { course_code: "EE6102" }],
    ["get_undergraduate_exam_schedule", { course_code: "SC2001" }],
    ["ntu_auth_status", {}],
  ]) {
    // listTools lets this SDK validate each call's structuredContent against outputSchema.
    const result = await client.callTool({ name, arguments: parameters });
    assert(!result.isError, name);
    assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
    assert(!("result" in result.structuredContent));
  }
  const error = await client.callTool({ name: "get_index", arguments: { ...args, index: "missing" } });
  assert(error.isError);
  assert.deepEqual((await client.listResources()).resources, []);
  assert.deepEqual((await client.listResourceTemplates()).resourceTemplates, []);
  console.log("TypeScript SDK interoperability passed: schemas, tool calls/errors, and resource discovery.");
} finally {
  await client.close();
  await rm(cwd, { recursive: true, force: true });
}
