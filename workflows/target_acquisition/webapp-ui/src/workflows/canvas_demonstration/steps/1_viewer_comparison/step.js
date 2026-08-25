/**
 * The one bench step: a run, and the engines compared against each other in it.
 *
 * This is not a step of a real run, and the workflow it belongs to says so in
 * its name. It exists so that the canvas — the picture of a run that an
 * operator pans and zooms — can be watched behaving inside the real operator
 * window, before it is put to work in a workflow that drives a microscope.
 *
 * There were two of these, one per engine. They were dropped into one because
 * the row of engine buttons above the picture already does the comparing, and
 * does it better: changing engine keeps the view exactly where it is, so the
 * same scene is seen through each in turn rather than through two pictures
 * that were never guaranteed to be looking at the same place.
 *
 * It asks for one module and gets that alone — there is no panel of controls
 * down the right-hand side, because this step wants only the picture and the
 * handful of buttons above it. And it says `nothingWaitsOnThis`: a step that
 * only shows you something produces nothing for a later step to use, so there
 * is genuinely nothing to wait for.
 */

export const theCanvas = {
  id: "canvas-picture",
  title: "Viewer comparison",
  why: "Opens the run and draws its three layers, once per drawing engine, side by side on the same scene.",
  panels: ["viewer-canvas"],
  nothingWaitsOnThis: true,
};
