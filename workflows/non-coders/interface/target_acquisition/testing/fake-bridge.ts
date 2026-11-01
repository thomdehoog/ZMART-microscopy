/**
 * A bridge for the backend's unit tests: `fetch`, answered by the test.
 *
 * The live backend speaks to the bridge through `fetch` and nothing else, so
 * a test stands in for the bridge by answering `fetch` itself, and keeps what
 * it was asked, in order, to say afterwards what the page did.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

import { vi } from "vitest";

/** A request's body as the bridge reads it: whatever `JSON.parse` makes of it. */
export type Parsed = ReturnType<typeof JSON.parse>;

/** One request: the route asked, and its body (null for a GET). */
export type Call = [route: string, body: Parsed];

/** What the fake bridge answers: a status, and the JSON body. */
export interface Answer {
  ok: boolean;
  status?: number;
  json(): Promise<unknown>;
}

/** An answer that went through. */
export const ok = (json: unknown): Answer => ({ ok: true, json: async () => json });

/** An answer that did not. */
export const refused = (status: number, json: unknown): Answer => ({ ok: false, status, json: async () => json });

/** The route asked for, without the bridge's address in front. */
const routeOf = (url: string): string => url.replace(/^http:\/\/[^/]+/, "");

/** A request's body, read as JSON; null for a GET. */
const bodyOf = (init?: RequestInit): Parsed => (init?.body ? JSON.parse(String(init.body)) : null);

/**
 * Stand in for the bridge: every `fetch` is answered by `answering(route,
 * body)`, and kept. The request itself comes last, for a test that asks
 * which method was used. Put back with `vi.unstubAllGlobals()`.
 */
export function aBridge(
  answering: (route: string, body: Parsed, url: string, init?: RequestInit) => Answer | Promise<Answer>,
) {
  const calls: Call[] = [];
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const route = routeOf(url);
    const body = bodyOf(init);
    calls.push([route, body]);
    return answering(route, body, url, init);
  });
  vi.stubGlobal("fetch", fetch);
  return { calls, fetch };
}

/** The body of the first request to `route`. */
export const theFirstTo = (calls: Call[], route: string): Parsed => calls.find(([asked]) => asked === route)?.[1];
