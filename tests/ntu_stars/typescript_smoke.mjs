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
  env: { PYTHONPATH: join(tests, "..", "..", "src"), PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring" },
});
const client = new Client({ name: "ntu-typescript-test", version: "1.0" });
try {
  await client.connect(transport);
  const { tools } = await client.listTools();
  assert.equal(tools.length, 32);
  for (const tool of tools) {
    assert.equal(tool.outputSchema.type, "object");
    assert(Object.keys(tool.outputSchema.properties).length > 0);
  }
  const args = { course_code: "ZZ0001", academic_year: 2026, semester: 1 };
  for (const [name, parameters] of [
    ["stars_search_courses", { query: "ZZ00", academic_year: 2026, semester: 1, limit: 2 }],
    ["stars_get_course_metadata", args], ["stars_get_course_indexes", args],
    ["stars_get_index", { ...args, index: "00001" }],
    ["stars_compare_indexes", { ...args, indexes: ["00001", "00002"] }],
    ["stars_find_matching_indexes", args],
    ["stars_get_graduate_course_schedule", { course_code: "EE6102" }],
    ["stars_get_undergraduate_exam_schedule", { course_code: "ZZ0001" }],
    ["stars_auth_status", {}],
  ]) {
    // listTools lets this SDK validate each call's structuredContent against outputSchema.
    const result = await client.callTool({ name, arguments: parameters });
    assert(!result.isError, name);
    assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
    assert(!("result" in result.structuredContent));
  }
  const error = await client.callTool({ name: "stars_get_index", arguments: { ...args, index: "missing" } });
  assert(error.isError);
  assert.deepEqual((await client.listResources()).resources, []);
  assert.deepEqual((await client.listResourceTemplates()).resourceTemplates, []);
} finally {
  await client.close();
  await rm(cwd, { recursive: true, force: true });
}

const learnCwd = await mkdtemp(join(tmpdir(), "ntu-learn-client-"));
const learn = new Client({ name: "ntu-learn-typescript-test", version: "1.0" });
try {
  await learn.connect(new StdioClientTransport({
    command: "python", args: [join(tests, "..", "ntulearn", "protocol_server.py")], cwd: learnCwd,
    env: { PYTHONPATH: join(tests, "..", "..", "src"), PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring" },
  }));
  assert.equal((await learn.listTools()).tools.length, 32);
  for (const [name, parameters] of [
    ["ntulearn_get_content_tree", { course_id: "_100_1" }],
    ["ntulearn_search_course_content", { course_id: "_100_1", query: "slides" }],
    ["ntulearn_search_all_courses", { query: "slides" }],
    ["ntulearn_list_messages", {}],
    ["ntulearn_read_message", { message_id: "_801_1", course_id: "_100_1", conversation_id: "_800_1" }],
    ["ntulearn_read_file_content", { course_id: "_100_1", content_id: "_202_1", attachment_id: "_500_1" }],
    ["ntulearn_whats_new", { course_ids: ["_100_1"] }],
  ]) {
    const result = await learn.callTool({ name, arguments: parameters });
    assert(!result.isError, name);
    assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
  }
  console.log("TypeScript SDK interoperability passed for STARS and NTULearn: schemas, tool calls/errors, and resource discovery.");
} finally {
  await learn.close();
  await rm(learnCwd, { recursive: true, force: true });
}
