import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { default: OpenAI } = await import(pathToFileURL(process.env.C3R_JS_SDK_MODULE).href);
const url = new URL(process.env.C3R_SDK_TEST_URL);
assert.equal(url.hostname, "127.0.0.1");
const client = new OpenAI({ apiKey: process.env.C3R_SDK_TEST_KEY,
  baseURL: url.href, maxRetries: 0, timeout: 5000 });
const response = await client.responses.create({ model: "c3r-core", input: "Inspect", store: false });
assert.equal(response.output_text, "Inspect safely.");
assert.equal(response.usage.total_tokens, 7);
assert.equal(typeof response.created_at, "number");
assert.ok(!JSON.stringify(response).includes("NEVER_PUBLIC"));
const stream = await client.responses.create({ model: "c3r-core", input: "Inspect", stream: true });
let text = "", terminal;
for await (const event of stream) {
  if (event.type === "response.output_text.delta") text += event.delta;
  terminal = event.type;
}
assert.equal(text, "Inspect safely.");
assert.equal(terminal, "response.completed");
console.log("SDK_ACCEPTANCE_PASS");
