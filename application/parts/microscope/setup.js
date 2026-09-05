/**
 * The page's side of the setup seam: how the driver-configuration workflow
 * reaches a driver's *setup*, as against its session.
 *
 * Every call here lands on a `/api/setup/...` route of the bridge, and none
 * of those routes touches the controller session. That is the whole point of
 * this being a file of its own rather than more methods on the live backend:
 * the workflow that configures a microscope and the workflows that drive one
 * go through different doors, and this is the second door.
 *
 * What comes back is what the driver said, unedited. The words on screen are
 * the step's business.
 */

import { ask } from "./live.js";
import { isFailed } from "./connection-status.js";

export const setupBackend = {
  /** The drivers that can be set up, as their connection entries. */
  async instruments() {
    return (await ask("/api/setup/instruments")).instruments;
  },

  /** Open one for configuration. Answers with the driver's own account of
      itself: its label, its connection checks, and what it can configure. */
  async open(connection) {
    return ask("/api/setup/open", { connection });
  },

  async close() {
    return ask("/api/setup/close", {});
  },

  /** Whether a setup is open, and its description if so. */
  async status() {
    return ask("/api/setup");
  },

  async where() {
    return ask("/api/setup/where");
  },

  /** Every lens the turret holds, as the driver lists them. */
  async objectives() {
    return (await ask("/api/setup/objectives")).objectives;
  },

  async move({ x_um, y_um, z_um }) {
    return ask("/api/setup/move", { x_um, y_um, z_um });
  },

  /** The document that stands for one subsystem, and where it came from --
      or, with `fresh`, the driver's default for it, as a setup that starts
      over begins from. */
  async read(subsystem, { fresh = false } = {}) {
    return ask(`/api/setup/read/${subsystem}${fresh ? "?fresh=1" : ""}`);
  },

  /** Run one of the measuring procedures: `boundary`, `orientation`, `lens`
      (with a `name`), `objective_pair`, or `origin`. */
  async measure(what, extra = {}) {
    return ask("/api/setup/measure", { what, ...extra });
  },

  /** Write a dated snapshot of one subsystem into the configuration being
      stood on. `evidence` names what to keep beside it: pictures by the
      route a measure answered with (`{name, picture}`), and numbers to keep
      as JSON (`{name, note}`), so a reopened configuration can show them. */
  async publish(subsystem, document, evidence = []) {
    return ask("/api/setup/publish", { subsystem, document, evidence });
  },

  /** The configurations this machine keeps, newest first, and the one the
      setup stands on, if chosen. */
  /** The configurations the open setup's machine keeps, and the one being
      stood on -- read once the driver is open. */
  async standingConfiguration() {
    return ask("/api/setup/configurations");
  },

  /** Stand on one of the machine's configurations, by id. */
  async openConfiguration(id) {
    return ask("/api/setup/configuration", { open: id });
  },

  /** Start a configuration as a full copy of what stands now, and stand on it. */
  async newConfiguration() {
    return ask("/api/setup/configuration", { new: true });
  },
};


/**
 * The setup seam wearing the shape the page's Connect card expects.
 *
 * The card was written for a session: it lists instruments, connects, watches
 * a set of named checks answer, and disconnects. Opening a driver's setup is
 * the same conversation with different words on the far side, so this
 * adapter lets the driver-configuration workflow reuse the card unchanged.
 * The checks are the ones the driver's `describe` reports; they arrive all at
 * once rather than over time, which the card is happy with.
 */
export const setupAsBackend = {
  /** The page tells one backend from another by this; the canvas and the
      stage-watch are skipped for one that is not a session. */
  kind: "setup",

  async instruments() {
    return setupBackend.instruments();
  },

  /** The configurations a machine keeps, listed before opening it, so the
      card offers them beside "New configuration". */
  async configurations(connection) {
    return (await ask("/api/setup/configurations", { connection })).configurations;
  },

  /* The card lists "New configuration" among the choices for this backend:
     a setup may start one, where a session may only stand on one. */
  offersNewConfiguration: true,

  async connect(session, { onChecks, onCheck } = {}) {
    /* The password and the configuration travel with the connection, as
       they do for a session: the configuration is an id to reopen, or
       "new" to start one as a copy of the newest. */
    const opened = await setupBackend.open({
      ...session?.connection, password: session?.password, configuration: session?.configuration,
    });
    const checks = opened.describe?.checks ?? {};
    const keys = Object.keys(checks);
    onChecks?.(keys);
    let failure = null;
    keys.forEach((key, k) => {
      const value = checks[key];
      onCheck?.(k, value);
      if (isFailed(value)) failure ??= `${key}: ${value}`;
    });
    if (failure) throw new Error(failure);
    return { info: { describe: opened.describe, pictures: opened.pictures } };
  },

  async disconnect() {
    await setupBackend.close();
  },

  async info() {
    return setupBackend.status();
  },

  /* The rest of the seam, for the steps that come after Connect. */
  setup: setupBackend,
};
