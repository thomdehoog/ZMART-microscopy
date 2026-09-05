/**
 * What a driver has to say about configuring itself, and why this exists.
 *
 * The five steps of this workflow mean the same thing on every microscope:
 * open a session, say how far the stage may travel, say how the picture is
 * turned relative to the stage, measure the optics, and choose the point the
 * run counts from. What none of them can be is the same *procedure* on every
 * microscope. Measuring the orientation on a Leica through Navigator Expert is
 * not the work it would be on a Zeiss through the ZEN API, the two write
 * different files in differently shaped folders, and some instruments have
 * nothing to measure for a given step at all.
 *
 * Nor can this be driven through the controller, which is the layer the
 * imaging workflows use. The controller is for operating a microscope that has
 * already been configured: with no published envelope the Leica driver refuses
 * to move at all, on purpose, so that a mistyped position cannot drive the
 * stage into the objective. Configuration is what happens before there is
 * anything for the controller to stand on.
 *
 * So each driver brings its own account of how it is set up, and this file
 * says what that account has to contain. The steps then stay short and honest:
 * they hold the meaning, and the driver holds the method.
 *
 * ## The shape
 *
 * A driver module exports one object named `setup`:
 *
 * - `vendor`, `microscope`, `api` — which instrument this account is for.
 *   `microscope` may be `null`, meaning "every microscope this vendor makes
 *   that speaks this API", which is how a driver organised by API rather than
 *   by instrument is matched.
 * - `label` — what to call it in a sentence to the operator.
 * - `subsystems` — one entry per configurable step, keyed by the step's id:
 *   `limits`, `orientation`, `calibration`, `origin`. Each entry says:
 *   - `supported` — whether this instrument has this to configure at all. A
 *     driver that says `false` is not broken; some instruments genuinely have
 *     no camera turn to measure. The step then greys out and says so, which is
 *     kinder than a button that does nothing.
 *   - `how` — a sentence for the operator about what the measuring involves.
 *   - `publishes` — where the answer is written, in the driver's own words, so
 *     an operator can go and look at what they just published.
 *
 * A subsystem the driver does not mention is treated as unsupported. Saying
 * nothing and saying "no" should mean the same thing, so that a driver being
 * written cannot half-claim a step by forgetting it.
 */

/** The four steps of this workflow that a driver configures, in the order they
 * are walked. Connect is not among them: connecting is the same everywhere,
 * which is exactly why this workflow borrows that step rather than owning it. */
export const CONFIGURABLE = ["limits", "orientation", "calibration", "origin"];

/**
 * What this driver says about one step, with the silences filled in.
 *
 * Returns an entry for any subsystem asked about, so callers never have to
 * check whether the driver mentioned it. A driver that said nothing gets
 * `supported: false` and a plain sentence saying as much.
 */
export function subsystem(setup, id) {
  const declared = setup?.subsystems?.[id];
  if (!declared) {
    return {
      supported: false,
      how: "This driver does not configure this yet.",
      publishes: null,
    };
  }
  return {
    supported: Boolean(declared.supported),
    how: declared.how ?? "",
    publishes: declared.publishes ?? null,
  };
}
