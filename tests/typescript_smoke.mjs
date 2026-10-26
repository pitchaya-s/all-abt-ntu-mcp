// Optional interoperability check using the official TypeScript SDK, without server dependencies.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
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
  args: [join(tests, "stars", "protocol_server.py")], cwd,
  env: { PYTHONPATH: join(tests, "..", "src"), PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring" },
});
const client = new Client({ name: "ntu-typescript-test", version: "1.0" });
try {
  await client.connect(transport);
  const { tools } = await client.listTools();
  assert.equal(tools.length, 69);
  for (const tool of tools) {
    assert.equal(tool.outputSchema.type, "object");
    assert(Object.keys(tool.outputSchema.properties).length > 0);
  }
  const args = { course_code: "ZZ0001", academic_year: 2026, semester: 1 };
  for (const [name, parameters] of [
    ["stars_search_courses", { query: "ZZ00", academic_year: 2026, semester: 1, limit: 2 }],
    ["stars_get_course_metadata", args], ["stars_get_course_indexes", args],
    ["stars_find_available_rooms", { academic_year:2030, semester:1, window:{day:"MON",start_time:"14:00",end_time:"15:00",teaching_weeks:[2]} }],
    ["stars_get_room_schedule", {academic_year:2030,semester:1,venue:"LT1"}],
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
    command: "python", args: [join(tests, "ntulearn", "protocol_server.py")], cwd: learnCwd,
    env: { PYTHONPATH: join(tests, "..", "src"), PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring" },
  }));
  assert.equal((await learn.listTools()).tools.filter(tool => tool.name.startsWith("ntulearn_")).length, 20);
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
} finally {
  await learn.close();
  await rm(learnCwd, { recursive: true, force: true });
}

const mapCwd = await mkdtemp(join(tmpdir(), "ntu-map-client-"));
const map = new Client({ name: "ntu-map-typescript-test", version: "1.0" });
try {
  await map.connect(new StdioClientTransport({
    command: "python", args: [join(tests, "mazemap", "protocol_server.py")], cwd: mapCwd,
    env: { PYTHONPATH: [join(tests, "..", "src"), join(tests, "..")].join(delimiter) },
  }));
  assert.equal((await map.listTools()).tools.filter(tool => tool.name.startsWith("mazemap_")).length, 5);
  for (const [name, parameters] of [
    ["mazemap_list_campuses", {}], ["mazemap_list_buildings", { query: "Example" }],
    ["mazemap_search_places", { query: "TR+7", limit: 1 }],
    ["mazemap_get_place", { poi_id: 1001 }],
    ["mazemap_get_directions", { from_poi_id: 1001, to_poi_id: 1002 }],
  ]) {
    const result = await map.callTool({ name, arguments: parameters });
    assert(!result.isError, name);
    assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
  }
  const error = await map.callTool({ name: "mazemap_get_place", arguments: { poi_id: -1 } });
  assert(error.isError);
} finally {
  await map.close();
  await rm(mapCwd, { recursive: true, force: true });
}

const repositoryCwd = await mkdtemp(join(tmpdir(), "ntu-repository-client-"));
const repository = new Client({ name: "ntu-repository-typescript-test", version: "1.0" });
try {
  await repository.connect(new StdioClientTransport({
    command: "python", args: [join(tests, "repository", "protocol_server.py")], cwd: repositoryCwd,
    env: { PYTHONPATH: [join(tests, "..", "src"), join(tests, "..")].join(delimiter) },
  }));
  assert.equal((await repository.listTools()).tools.filter(tool => tool.name.startsWith("drntu_")).length, 12);
  for (const [name, parameters] of [
    ["drntu_search", { query: "learning" }],
    ["drntu_get_item", { item_id: "11111111-1111-4111-8111-111111111111" }],
    ["drntu_browse", {}], ["drntu_get_facets", { facet: "dateIssued" }],
    ["drntu_list_bundles", { item_id: "11111111-1111-4111-8111-111111111111" }],
    ["drntu_list_files", { bundle_id: "22222222-2222-4222-8222-222222222222" }],
    ["drntu_get_dataset", { persistent_id: "doi:10.21979/EXAMPLE/DATA" }],
    ["drntu_oai_identify", {}], ["drntu_oai_list_metadata_formats", {}],
    ["drntu_oai_list_sets", { limit: 1 }],
    ["drntu_oai_list_records", { headers_only: true, limit: 1 }],
    ["drntu_oai_get_record", { identifier: "oai:dr.ntu.edu.sg:10356/EXAMPLE1" }],
  ]) {
    const result = await repository.callTool({ name, arguments: parameters });
    assert(!result.isError, name);
    assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
  }
} finally {
  await repository.close();
  await rm(repositoryCwd, { recursive: true, force: true });
}

for (const [folder, prefixName, count, calls] of [
  ["news", "news_", 3, [
    ["news_search", { query: "quantum" }],
    ["news_search", { page: 2, sort: "oldest" }],
    ["news_list_categories", {}],
    ["news_get_article", { url: "https://www.ntu.edu.sg/news/detail/synthetic-news-4.5g", max_chars: 20 }],
  ]],
  ["service", "service_", 2, [
    ["service_search", { query: "clinic" }],
    ["service_search", { location_contains: "south" }],
    ["service_list_filters", {}],
  ]],
  ["faculty", "faculty_", 2, [
    ["faculty_search", { query: "Example" }],
    ["faculty_search", { page: 2 }],
    ["faculty_search", { interest_id: "11111111-1111-4111-8111-111111111111" }],
    ["faculty_list_interests", { query: "intelligence" }],
  ]],
  ["library", "library_", 6, [
    ["library_search", { query: "algorithms" }],
    ["library_get_record", { record_id: "almaExample001" }],
    ["library_get_record", { record_id: "cdi_example_article", context: "PC" }],
    ["library_get_availability", { record_id: "almaExample001" }],
    ["library_list_facilities", {}],
    ["library_get_map_availability", { map_slug: "abcdef123456", date: "2026-10-24", time: "14:00" }],
    ["library_get_facility_schedule", { date: "2026-10-24", space_id: 100 }],
  ]],
]) {
  const directory = await mkdtemp(join(tmpdir(), "ntu-" + folder + "-client-"));
  const service = new Client({ name: "ntu-" + folder + "-typescript-test", version: "1.0" });
  try {
    await service.connect(new StdioClientTransport({
      command: "python", args: [join(tests, folder, "protocol_server.py")], cwd: directory,
      env: { PYTHONPATH: [join(tests, "..", "src"), join(tests, "..")].join(delimiter) },
    }));
    assert.equal((await service.listTools()).tools.filter(tool => tool.name.startsWith(prefixName)).length, count);
    for (const [name, parameters] of calls) {
      const result = await service.callTool({ name, arguments: parameters });
      assert(!result.isError, name);
      assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
    }
  } finally {
    await service.close();
    await rm(directory, { recursive: true, force: true });
  }
}
console.log("TypeScript SDK interoperability passed for all eight NTU tool sets.");
