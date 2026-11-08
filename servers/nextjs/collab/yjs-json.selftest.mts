// Self-check for lib/collab/yjs-json.ts: two replicas edit concurrently and converge.
// Run: node collab/yjs-json.selftest.mts   (Node >= 22.6 strips the TS types)
import assert from "node:assert/strict";
import * as Y from "yjs";
import { diffMap, toY } from "../lib/collab/yjs-json.ts";

const deck = {
  title: "Deck",
  slides: [
    { id: "s1", ui: { components: [{ id: "c1", elements: [{ type: "text", runs: [{ text: "Hello world" }], position: { x: 1, y: 2 } }] }] } },
    { id: "s2", ui: { components: [] } },
  ],
};

const a = new Y.Doc();
const b = new Y.Doc();
a.getMap("deck").set("data", toY(deck));
Y.applyUpdate(b, Y.encodeStateAsUpdate(a));

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const edit = (doc: Y.Doc, mutate: (d: any) => void) => {
  const before = (doc.getMap("deck").get("data") as Y.Map<unknown>).toJSON();
  const after = clone(before);
  mutate(after);
  doc.transact(() => diffMap(doc.getMap("deck").get("data") as Y.Map<unknown>, before, after));
};

// A types in the same text run and moves the element; B edits the same run and adds a slide.
edit(a, (d) => {
  d.slides[0].ui.components[0].elements[0].runs[0].text = "Hello big world";
  d.slides[0].ui.components[0].elements[0].position.x = 50;
});
edit(b, (d) => {
  d.slides[0].ui.components[0].elements[0].runs[0].text = "Hello world!";
  d.slides.splice(1, 0, { id: "s3", ui: { components: [] } });
  d.title = "Team deck";
});
Y.applyUpdate(a, Y.encodeStateAsUpdate(b));
Y.applyUpdate(b, Y.encodeStateAsUpdate(a));

const ja = (a.getMap("deck").get("data") as Y.Map<unknown>).toJSON();
const jb = (b.getMap("deck").get("data") as Y.Map<unknown>).toJSON();
assert.deepEqual(ja, jb, "replicas converge");
const el = ja.slides[0].ui.components[0].elements[0];
assert.equal(el.runs[0].text, "Hello big world!", "both text edits kept");
assert.equal(el.position.x, 50);
assert.deepEqual(ja.slides.map((s: any) => s.id), ["s1", "s3", "s2"]);
assert.equal(ja.title, "Team deck");

// Deleting a slide on one side while the other edits a different slide.
edit(a, (d) => d.slides.splice(2, 1));
edit(b, (d) => (d.slides[0].ui.components[0].elements[0].position.y = 99));
Y.applyUpdate(a, Y.encodeStateAsUpdate(b));
Y.applyUpdate(b, Y.encodeStateAsUpdate(a));
const j2 = (a.getMap("deck").get("data") as Y.Map<unknown>).toJSON();
assert.deepEqual(j2, (b.getMap("deck").get("data") as Y.Map<unknown>).toJSON());
assert.deepEqual(j2.slides.map((s: any) => s.id), ["s1", "s3"]);
assert.equal(j2.slides[0].ui.components[0].elements[0].position.y, 99);

// No-op diff produces no update.
let updates = 0;
a.on("update", () => updates++);
edit(a, () => {});
assert.equal(updates, 0, "identical snapshot writes nothing");

console.log("yjs-json selftest: OK");
