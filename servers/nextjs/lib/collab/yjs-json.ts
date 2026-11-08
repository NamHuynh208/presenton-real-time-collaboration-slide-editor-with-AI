// Map Presenton's plain-JSON deck onto Yjs types and back, applying only the
// minimal changes between two JSON snapshots. Objects -> Y.Map, arrays -> Y.Array,
// strings stored under a "text" key (text runs) -> Y.Text so two people typing in
// the same text box merge character by character; other strings are atomic.
import * as Y from "yjs";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

const isObject = (v: unknown): v is Record<string, Json> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

export function toY(value: unknown, key?: string): unknown {
  if (Array.isArray(value)) {
    const arr = new Y.Array<unknown>();
    arr.insert(0, value.map((item) => toY(item)));
    return arr;
  }
  if (isObject(value)) {
    const map = new Y.Map<unknown>();
    for (const [k, v] of Object.entries(value)) {
      if (v !== undefined) map.set(k, toY(v, k));
    }
    return map;
  }
  if (typeof value === "string" && key === "text") return new Y.Text(value);
  return value === undefined ? null : value;
}

export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a)) {
    if (!Array.isArray(b) || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (!deepEqual(a[i], b[i])) return false;
    return true;
  }
  if (isObject(a)) {
    if (!isObject(b)) return false;
    const ka = Object.keys(a).filter((k) => a[k] !== undefined);
    const kb = Object.keys(b).filter((k) => b[k] !== undefined);
    if (ka.length !== kb.length) return false;
    for (const k of ka) if (!deepEqual(a[k], b[k])) return false;
    return true;
  }
  return false;
}

function diffText(ytext: Y.Text, oldStr: string, newStr: string) {
  if (ytext.toString() !== oldStr) {
    // Local snapshot drifted from the shared text; replace wholesale.
    ytext.delete(0, ytext.length);
    ytext.insert(0, newStr);
    return;
  }
  let start = 0;
  const min = Math.min(oldStr.length, newStr.length);
  while (start < min && oldStr[start] === newStr[start]) start++;
  let endOld = oldStr.length;
  let endNew = newStr.length;
  while (endOld > start && endNew > start && oldStr[endOld - 1] === newStr[endNew - 1]) {
    endOld--;
    endNew--;
  }
  if (endOld > start) ytext.delete(start, endOld - start);
  if (endNew > start) ytext.insert(start, newStr.slice(start, endNew));
}

// Identity used to line up array items (slides, components) across snapshots.
const itemKey = (v: unknown): unknown => (isObject(v) && typeof v.id === "string" ? v.id : undefined);
const sameItem = (a: unknown, b: unknown) => {
  const ka = itemKey(a);
  const kb = itemKey(b);
  return ka !== undefined || kb !== undefined ? ka === kb : deepEqual(a, b);
};

function diffArray(yarr: Y.Array<unknown>, oldArr: unknown[], newArr: unknown[]) {
  if (yarr.length !== oldArr.length) {
    yarr.delete(0, yarr.length);
    yarr.insert(0, newArr.map((v) => toY(v)));
    return;
  }
  let start = 0;
  const min = Math.min(oldArr.length, newArr.length);
  while (start < min && sameItem(oldArr[start], newArr[start])) start++;
  let endOld = oldArr.length;
  let endNew = newArr.length;
  while (endOld > start && endNew > start && sameItem(oldArr[endOld - 1], newArr[endNew - 1])) {
    endOld--;
    endNew--;
  }
  // Matched prefix/suffix items may still have changed inside: recurse.
  for (let i = 0; i < start; i++) diffValueAt(yarr, i, oldArr[i], newArr[i]);
  for (let j = 0; j < oldArr.length - endOld; j++) {
    diffValueAt(yarr, endOld + j, oldArr[endOld + j], newArr[endNew + j]);
  }
  const removed = endOld - start;
  const added = endNew - start;
  if (removed === added) {
    for (let i = 0; i < added; i++) diffValueAt(yarr, start + i, oldArr[start + i], newArr[start + i]);
  } else {
    if (removed > 0) yarr.delete(start, removed);
    if (added > 0) yarr.insert(start, newArr.slice(start, endNew).map((v) => toY(v)));
  }
}

function diffValueAt(yarr: Y.Array<unknown>, index: number, oldVal: unknown, newVal: unknown) {
  if (oldVal === newVal) return;
  const current = yarr.get(index);
  if (canPatch(current, oldVal, newVal)) {
    patch(current, oldVal, newVal);
    return;
  }
  if (deepEqual(oldVal, newVal)) return;
  yarr.delete(index, 1);
  yarr.insert(index, [toY(newVal)]);
}

function canPatch(current: unknown, oldVal: unknown, newVal: unknown) {
  return (
    (current instanceof Y.Map && isObject(oldVal) && isObject(newVal)) ||
    (current instanceof Y.Array && Array.isArray(oldVal) && Array.isArray(newVal)) ||
    (current instanceof Y.Text && typeof oldVal === "string" && typeof newVal === "string")
  );
}

function patch(current: unknown, oldVal: unknown, newVal: unknown) {
  if (current instanceof Y.Map) diffMap(current, oldVal as Record<string, Json>, newVal as Record<string, Json>);
  else if (current instanceof Y.Array) diffArray(current, oldVal as unknown[], newVal as unknown[]);
  else if (current instanceof Y.Text) diffText(current, oldVal as string, newVal as string);
}

export function diffMap(ymap: Y.Map<unknown>, oldObj: Record<string, unknown>, newObj: Record<string, unknown>) {
  if (oldObj === newObj) return;
  for (const key of Object.keys(oldObj)) {
    if (newObj[key] === undefined && ymap.has(key)) ymap.delete(key);
  }
  for (const [key, newVal] of Object.entries(newObj)) {
    if (newVal === undefined) continue;
    const oldVal = oldObj[key];
    if (oldVal === newVal) continue;
    const current = ymap.get(key);
    if (current !== undefined && canPatch(current, oldVal, newVal)) {
      patch(current, oldVal, newVal);
    } else if (!(ymap.has(key) && deepEqual(oldVal, newVal))) {
      ymap.set(key, toY(newVal, key));
    }
  }
}
