import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";

const [prefix, endpoint] = process.argv.slice(2);
assert(prefix && endpoint, "Pass the TypeScript SDK npm prefix and the offline HTTP server's /mcp URL");
const require = createRequire(join(resolve(prefix), "package.json"));
const { Client } = require("@modelcontextprotocol/sdk/client/index.js");
const { StreamableHTTPClientTransport } = require("@modelcontextprotocol/sdk/client/streamableHttp.js");
const client = new Client({ name: "ntu-public-http-test", version: "1.0" });
try {
  await client.connect(new StreamableHTTPClientTransport(new URL(endpoint)));
  const { tools } = await client.listTools();
  assert.equal(tools.length, 34);
  assert(tools.every(tool => tool.annotations.readOnlyHint && tool.outputSchema));
  for (const [name, args] of [
    ["stars_get_course_metadata", { course_code: "ZZ0001", academic_year: 2026, semester: 1 }],
    ["mazemap_list_campuses", {}], ["drntu_search", { query: "learning" }],
    ["library_search", { query: "algorithms" }], ["faculty_search", { query: "Example" }],
    ["news_get_article", { url: "https://www.ntu.edu.sg/news/detail/synthetic-news-4.5g" }],
    ["service_search", { query: "clinic" }],
  ]) {
    const result = await client.callTool({ name, arguments: args });
    assert(!result.isError, name);
    assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
  }
  const denied = await client.callTool({ name: "stars_get_degree_audit", arguments: {} });
  assert(denied.isError);
  assert.deepEqual((await client.listResources()).resources, []);
  console.log("TypeScript HTTP interoperability passed: 34 public tools; personal reads rejected.");
} finally {
  await client.close();
}
