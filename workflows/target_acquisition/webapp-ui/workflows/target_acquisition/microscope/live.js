/**
 * The seam where the microscope goes — the live side of it.
 *
 * The same shape as `mock.js`, implemented as HTTP calls to the bridge
 * (`workflow/webapp/bridge.py`), which speaks to the zmart controller, which
 * speaks to whichever driver is plugged in — the Leica driver on the
 * microscope PC (real LAS X or its simulator, the same driver either way),
 * or the controller's own mock driver on a machine with no instrument.
 *
 * Everything about the wire lives in this one file: the address, the JSON,
 * and how a failure becomes a thrown Error carrying the bridge's own
 * sentence. Nothing else in the page knows HTTP exists. The page chooses
 * this backend with `?backend=live` in its address; the pretend one stays
 * the default, so development and the test suite need no bridge running.
 *
 * The live path deliberately stops at the overview scan, as the bridge does.
 */

/* Where the bridge answers. Empty means the page's own origin — the way it is
   on the microscope, where one Python process serves the page and the bridge
   together. `?bridge=http://127.0.0.1:8600` points elsewhere during
   development, when the vite server holds the page instead. */
const WHERE =
  new URLSearchParams(globalThis.location?.search ?? "").get("bridge") ?? "";

/** One call to the bridge: JSON in, JSON out, failure as a plain sentence. */
async function ask(route, payload) {
  const answer = await fetch(`${WHERE}${route}`, payload === undefined
    ? undefined
    : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  const body = await answer.json().catch(() => ({}));
  if (!answer.ok || body.error) {
    throw new Error(body.error ?? `the bridge answered ${answer.status}`);
  }
  return body;
}

const rest = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const backend = {
  /**
   * Open the session through the bridge and report what was verified.
   *
   * The bridge answers once, with the driver's account of itself, so the
   * checks here are that account unpacked — each row lands through `onCheck`
   * the way the pretend ones do, just all at the same moment.
   */
  async connect(session, { onCheck } = {}) {
    const checks = [
      { id: "bridge", label: "Bridge reachable" },
      { id: "driver", label: "Driver connected" },
      { id: "instrument", label: "Instrument reports itself" },
    ];
    const { context, info } = await ask("/api/connect", {
      instrument: session?.instrument ?? "mock",
    });
    /* Answers land after the return: the window builds its rows from the
       list this hands back, so an answer delivered before that would find no
       row to land in. The pretend backend's timers kept the same order by
       accident; here it is kept on purpose. */
    setTimeout(() => {
      onCheck?.(0, WHERE || "same origin");
      onCheck?.(1, `${context.vendor} · ${context.microscope} · ${context.api}`);
      onCheck?.(2, JSON.stringify(info).slice(0, 60));
    }, 0);
    return { checks };
  },

  /**
   * A readout, never a procedure: the instrument's state as it is set now.
   * One `get_state` through the controller, shaped by the bridge into the
   * reading the window records. `nth` is the pretend operator's knob and the
   * live instrument has no use for it.
   */
  async readSetting(type) {
    return ask(`/api/setting?type=${encodeURIComponent(type)}`);
  },

  /**
   * Drive to each point and focus there. The bridge runs the autofocus
   * procedure per position and reports the heights; the sweep traces the
   * pretend backend charts are the mock's own knowledge, so live points come
   * back without them and the chart stays empty until the driver can report
   * real sweeps.
   */
  async measureFocus(points, { metric } = {}) {
    return ask("/api/focus/measure", { points, metric });
  },

  /**
   * Start the overview scan and follow it by asking, not by being told: the
   * bridge drives the stage in a background thread, and this polls its
   * progress until the drive is over. The window's live picture watches the
   * run's own store, exactly as it does on the pretend side.
   */
  async scanOverview({ positions, onProgress } = {}) {
    await ask("/api/scan", { positions });
    for (;;) {
      const progress = await ask("/api/scan");
      onProgress?.(progress.done, progress.of);
      if (progress.error) throw new Error(progress.error);
      if (!progress.running) return { done: progress.done, of: progress.of };
      await rest(300);
    }
  },
};
