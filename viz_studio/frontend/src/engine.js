/**
 * Keeping the engine's picture in step with the panel, without rebuilding it.
 *
 * The panel and the engine hold the same information in two different shapes.
 * The panel thinks in acquisition types and channels; the engine thinks in a flat
 * list of layers. Something has to carry changes from one to the other, and this
 * is that something.
 *
 * The obvious way to do it is to hand Neuroglancer a fresh description of the
 * whole scene every time anything changes, and let it sort out the difference.
 * Neuroglancer offers exactly that call, and we used it. It turns out not to work
 * the way the name suggests: `restoreState` does not compare the new description
 * against the old one. It throws every existing layer away and builds the lot
 * again from scratch. So nudging one contrast slider was quietly demolishing and
 * rebuilding every layer on screen.
 *
 * Three things go wrong when that happens, and they get worse as the data gets
 * bigger:
 *
 * 1. Anything the operator drew is lost. A drawn target lives inside its layer,
 *    and the rebuilt layer is a new, empty one — so the target disappears from the
 *    image while the list beside it still claims the target is there.
 * 2. The pieces of image already fetched are dropped and asked for again. They
 *    are kept in a shared cache that survives for a moment after the last layer
 *    lets go of them, so a fast enough rebuild often catches them still warm and
 *    nothing is refetched. That is luck, not design, and on a run of several
 *    hundred gigabytes — where a rebuild can easily land while pieces are still
 *    in flight — it is luck that runs out.
 * 3. Everything the engine had worked out about the scene has to be worked out
 *    again: which copy of the image to draw, how the layers line up in space, which
 *    shader programs to compile. None of it changed.
 *
 * So this module does the comparing itself. It looks at what the engine currently
 * has, works out the smallest set of changes that would turn it into what the
 * panel is asking for, and makes only those. A layer is built only when it is
 * genuinely new, and thrown away only when it has genuinely gone. Everything else
 * — brightness, colour, opacity, whether a channel is showing, what order the
 * acquisition types are drawn in — is written straight onto the layer that is
 * already there, which is what Neuroglancer expects and is fast enough to do on
 * every drag of a slider.
 */

import { makeLayer, deleteLayer } from "neuroglancer/unstable/layer/index.js";
import {
  advancingSourceRevisions,
  memoEntriesForStableSource,
  rememberedSourceRevisions,
  sourceRevisionsFor,
} from "./live-refresh.js";

// -- what each layer was last told ---------------------------------------------
//
// Working out the smallest set of changes means remembering what the engine was
// handed last time, because the engine cannot always be asked. Everything
// remembered here is filed against the layer it belongs to, in a kind of map that
// lets go of an entry on its own once the layer is thrown away — so closing an
// acquisition hands the memory back without anything having to tidy up.

// The addresses each layer was last given. Kept here rather than read back out of
// the engine because Neuroglancer tidies up the addresses it is handed, so what
// comes back out is not always character-for-character what went in — and a
// comparison that got that wrong would add the same image over and over. A
// WeakMap is used so that a layer being thrown away takes its entry with it.
const sourcesApplied = new WeakMap();

// For each layer, how many frames each of its stores was last known to hold: a map
// from the store's address to its count. This is what decides which stores are worth
// reading again, and it has to be per store rather than per layer -- see syncSources
// for what asking the wrong question cost. Kept beside the addresses above and for the
// same reason: a layer being thrown away takes its entry with it.
const framesSeen = new WeakMap();

// The committed revision last applied for each stable aggregate source.  Kept
// separately from the URL because the URL deliberately never changes when a
// position or moment is published.
const revisionsSeen = new WeakMap();

// Request-cost evidence exposed to the browser tests.  ``sources`` contains
// only stable source identities that advanced on the most recent sync pass;
// unchanged and unrelated sources must never appear here.
export const sourceRefreshing = {
  passes: 0,
  sources: [],
  metadataEntries: 0,
  decodedEntries: 0,
};

function sourceList(spec) {
  if (spec.source == null) return [];
  return Array.isArray(spec.source) ? spec.source : [spec.source];
}

// -- handing the stores over a few at a time ----------------------------------

/**
 * Handing the engine its stores a few at a time, rather than all at once.
 *
 * This exists because of a fault that was easy to miss and serious to have: above
 * roughly six hundred and eighty positions, the rest of the specimen never appeared,
 * and nothing on screen said so. A folder of two thousand positions drew six hundred
 * and eighty-six of them and presented that as the whole thing.
 *
 * The cause is not ours and not the disk's. Reading one store means about four small
 * requests for the files that describe it, and a browser will only hold six
 * conversations with one address at a time. Beyond a few thousand requests waiting
 * their turn it stops accepting new ones altogether — it says so in its own words,
 * `net::ERR_INSUFFICIENT_RESOURCES`. The engine takes a refused request as "this
 * store cannot be read" and quietly leaves that position out. Nothing was wrong with
 * the data: every store it gave up on reads back perfectly well afterwards, one at a
 * time. The server was never answering more than seven requests at once and spent two
 * thirds of the wait idle.
 *
 * So the stores are handed over in groups, and each group is allowed to finish being
 * read before the next one is offered. The browser's queue then never fills, nothing
 * is refused, and nothing is lost. Fed this way, a folder of a thousand positions
 * loads a thousand of a thousand and a folder of two thousand loads two thousand of
 * two thousand, with no failures at all.
 *
 * **There is deliberately no special case for opening a finished folder.** It is
 * tempting to think of this as something needed only for a cold open, but it is better
 * understood as simply *how stores are handed over*: give it however many there are,
 * and it feeds them in groups. While the microscope is running that number is one,
 * which is a single group and costs nothing beyond what happened before. Opening a
 * finished folder of forty thousand positions is many groups. Same path either way,
 * and nothing anywhere asks whether the data is live.
 *
 * **What this does not do is make a large folder quick**, and it should not be expected
 * to. Every one of forty thousand positions is still read, merely in an orderly fashion
 * rather than all at once.
 *
 * Speed is a separate problem, and it is deliberately *not* solved here. Two ways of
 * solving it were considered and both were turned down, for the same reason: each would
 * have added a second copy of something that already exists elsewhere.
 *
 * The first was to hand the engine only the positions the operator is looking at.
 * Neuroglancer already decides which pieces of image to fetch from where the view is, and
 * it does that better than we would; keeping our own idea of what is in view means holding
 * a second copy of knowledge the engine already has, which is how this project has got
 * into trouble before. The second was to fuse the positions into one image per acquisition
 * type, which means a second copy of the data itself, written by us, and a whole writer to
 * maintain.
 *
 * What is left is the honest answer: a folder of forty thousand positions takes as long as
 * it takes, and the way to wait less is to open less — which is the operator's choice to
 * make, not ours to make for them. See Decision 5 in `DATA_LAYOUT.md`.
 *
 * There is one real way to make it quicker, and it is not in this file: have the run write
 * into a single image rather than one store per position, so there are forty thousand
 * places within one store instead of forty thousand stores. That is faster by a wide margin
 * and is what we are aiming for, but it is a decision about how data is written, and this
 * function has to go on working well for the runs that keep their positions separate. See
 * Decision 1b.
 */

// How many stores are offered at a time, **across the whole scene**. Two hundred is the
// size that was measured to work: large enough that a folder of a few thousand positions
// is not made needlessly slow by waiting, and far enough below the browser's limit that a
// group of them can be in flight together without any risk of one being refused.
//
// That it is shared between rows rather than allowed to each of them separately is the
// point, and it is easy to get wrong. A store holding four channels in separate files
// feeds four rows, and if each row were free to offer two hundred stores the browser
// would see eight hundred at once and be back at the limit this exists to stay under.
// The browser's queue of outstanding requests is one shared thing, so the budget for it
// has to be one shared thing too. When several rows are waiting they share the two
// hundred between them.
const AT_A_TIME = 200;

// How long to wait for one group before going on regardless. A store that cannot be
// read reports that quickly and is not the case this guards against; what it guards
// against is a store that never answers at all — a share that has gone away
// mid-acquisition, say. Without this, one such store would stop every later group from
// ever being offered, which is the same silent loss of the specimen this whole
// mechanism exists to prevent. A minute is far longer than a group of two hundred
// stores has ever taken, so in ordinary use it never comes into play.
const PATIENCE_MS = 60_000;

function howManyAtATime() {
  // The browser tests set this to a small number, so that the pacing can be watched
  // happening on a folder of a few dozen positions instead of a few thousand. Nothing
  // in the viewer itself sets it.
  const asked = globalThis.zmartSourceBatch;
  return Number.isFinite(asked) && asked > 0 ? asked : AT_A_TIME;
}

// What each layer is still waiting to be handed. The queue is per layer, because each
// row has its own list of stores; the *rate* is not, for the reason given above.
// A WeakMap is used so that a layer being thrown away takes its entry with it, the same
// as the two maps above.
const feeding = new WeakMap();

// The layers with something still to hand over. Held by ordinary reference rather than
// weakly, which is safe because a layer is taken out the moment its queue empties or it
// is discarded — nothing lingers here long enough to keep a dead layer alive.
const hungry = new Set();

// The group handed over most recently, across the whole scene, and whether the loop
// below is already running. Both are shared rather than per layer: one budget, one loop.
let inFlight = [];
let handingOver = false;

// Ways to stop waiting early, so that a layer going away does not leave the loop
// listening for stores that will never answer. See stopFeeding.
const giveUpWaiting = new Set();

function feedFor(layer) {
  let feed = feeding.get(layer);
  if (!feed) {
    feed = { waiting: [], stopped: false };
    feeding.set(layer, feed);
  }
  return feed;
}

// A layer that has been discarded while its stores were still being read. Offering more
// to it would raise an error in the middle of nothing, so the loop simply drops it.
function goneAway(layer) {
  return Boolean(layer.wasDisposed || layer.managedLayer?.wasDisposed);
}

/**
 * Stop handing stores to a layer that is going away.
 *
 * Without this, closing a folder while it was still loading would leave the loop
 * waiting on stores belonging to a layer that no longer exists — waiting that would
 * never end, because a discarded layer's data sources have nothing left to announce.
 */
function stopFeeding(layer) {
  hungry.delete(layer);
  const feed = feeding.get(layer);
  if (!feed) return;
  feed.stopped = true;
  feed.waiting.length = 0;
  // Wake the loop so it notices, rather than leaving it waiting on this layer's stores.
  for (const stopWaiting of [...giveUpWaiting]) stopWaiting();
}

/**
 * Wait until the engine has finished reading this group of stores.
 *
 * "Finished" here means it has an answer, whichever answer it is: a store that turns
 * out to be unreadable has been dealt with just as much as one that read perfectly, and
 * waiting longer would not improve it. The engine says so by giving the data source a
 * load state, which is empty while the reading is still under way.
 */
function whenTheseHaveBeenRead(sources) {
  return new Promise((done) => {
    const stopListening = [];
    let patience;
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      for (const stop of stopListening) stop();
      giveUpWaiting.delete(finish);
      clearTimeout(patience);
      done();
    };
    const look = () => {
      if (sources.some((source) => source.loadState === undefined)) return;
      finish();
    };
    giveUpWaiting.add(finish);
    patience = setTimeout(finish, PATIENCE_MS);
    for (const source of sources) stopListening.push(source.changed.add(look));
    // In case they are all read already, which is the ordinary case while the
    // microscope is running: one position arrives, nothing else is outstanding, and
    // this returns without any waiting at all.
    look();
  });
}

/**
 * Offer the waiting stores, a group at a time, until every queue is empty.
 *
 * One loop for the whole scene rather than one per row, so that the two hundred is a
 * budget shared between the rows waiting rather than an allowance given to each of them.
 * Anything queued while it is running is picked up by the same loop, so a position
 * arriving during a cold open simply joins the end rather than starting a burst of its
 * own.
 */
async function keepHandingOver() {
  if (handingOver) return;
  handingOver = true;
  try {
    for (;;) {
      for (const layer of [...hungry]) {
        const feed = feeding.get(layer);
        if (!feed || feed.stopped || !feed.waiting.length || goneAway(layer)) {
          hungry.delete(layer);
        }
      }
      if (!hungry.size) break;
      // Let the group offered last time finish before offering another. On the first
      // turn that is whatever the new layers were built with; after that it is the
      // previous group. Either way it is at most one group's worth, so this never costs
      // anything that grows with the size of the folder.
      await whenTheseHaveBeenRead(inFlight);
      const offered = [];
      let room = howManyAtATime();
      // Shared out evenly, so that a row holding forty thousand positions does not keep
      // another row's handful waiting behind it.
      const share = Math.max(1, Math.floor(room / hungry.size));
      for (const layer of [...hungry]) {
        if (room <= 0) break;
        const feed = feeding.get(layer);
        // Checked again here as well as at the top: the waiting above is where the time
        // passes, and so is where a layer is most likely to disappear.
        if (!feed || feed.stopped || goneAway(layer)) {
          hungry.delete(layer);
          continue;
        }
        const group = feed.waiting.splice(0, Math.min(share, room));
        room -= group.length;
        for (const url of group) {
          // Neuroglancer's own reader turns the address into whatever it needs, so the
          // format the panel writes and the format the engine wants cannot drift apart.
          // It is handed a list of one rather than a bare address on purpose: that is
          // the same path a layer takes when it is first built, so a store added later
          // is set up in exactly the same way as one that was there from the start.
          for (const source of layer.getDataSourceSpecifications({ source: [url] })) {
            offered.push(layer.addDataSource(source));
          }
        }
        if (!feed.waiting.length) hungry.delete(layer);
      }
      inFlight = offered;
    }
  } finally {
    handingOver = false;
  }
}

// -- making the engine look at the disk again ---------------------------------
//
// The engine remembers everything it has ever read, and there is no time limit on
// that memory. It is the right thing almost always, and it is exactly wrong while a
// run is still writing: what was true when the engine looked is no longer true.
//
// There are two ways of telling it to look again, and they are different sizes.
// `letGoOfDecodedPieces` drops the picture the engine has already decoded, for the
// whole scene. `forgetWhatWasReadAbout` drops only what was read about one store,
// which is what a timelapse gaining a frame needs. Between them sits
// `sourcesStillWaiting`, which is not about looking again at all — it belongs to the
// feeding above and lives here only so that the two counts a test reads are together.

/**
 * Let go of the pieces of image the engine has already decoded, so that looking again
 * really looks.
 *
 * This is what makes it possible to watch a run that writes into **one** store rather
 * than one store per position — a single OME-Zarr, created empty at the start, with each
 * tile written straight into its place. That layout is worth a great deal: what costs
 * the viewer is the number of separate stores rather than the amount of data behind
 * them, and one store opens in a second and a half where three hundred take longer on
 * thirty times the requests.
 *
 * The difficulty is that the engine remembers every piece of image it has decoded, and
 * that includes the pieces it found to be empty. There is no time limit on that memory.
 * So a tile written into a place the viewer has already looked at is simply not noticed:
 * the panel goes on showing the emptiness it decided on earlier and never goes back to
 * the disk. Measured, that is not "slow to appear" — it is **no request at all**, ever.
 *
 * So the sources are asked to let go, which the engine offers a way to do: the pieces
 * live in a separate worker, and this sends word to that worker to drop them. What comes
 * back is fetched afresh.
 *
 * **What it costs, and why it is affordable.** Only the pieces actually on screen are
 * fetched again — nine of them in the measurement — because the engine asks for what it
 * needs to draw and nothing else. That number follows the size of the window rather than
 * the size of the specimen, so it is the same on a folder of forty terabytes as on one of
 * forty megabytes. Anything the operator had scrolled past is dropped and will be fetched
 * again if they scroll back, which is the price, and it is a fair one.
 *
 * **When this is called matters as much as what it does**, and the rule is narrow on
 * purpose. There are exactly two occasions, both in App.jsx:
 *
 * 1. A run announced that it wrote image into a store already open, by sending
 *    `wrote_image_in_place`. It is the only one who knows, so it is believed.
 * 2. An acquisition that the panel already knew about, and that had no picture in it at
 *    all, has just gained one — seen as a store going from having no histogram and no
 *    count of moments to having them.
 *
 * An earlier attempt used a wider rule: an announcement arrived and the answer came back
 * completely unchanged. That reads well and is wrong in practice. Redundant announcements
 * are ordinary — the microscope and the folder watcher both see the same write — so it
 * fired on every one of them, and measured, that cost a refetch of the whole view on
 * every position arrival. When a position arrives or a timelapse lengthens, this is not
 * called, and nothing already fetched is thrown away.
 *
 * Returns how many sources were asked, so a test can tell "it was asked and nothing
 * happened" from "it was never asked".
 */
// How many times the viewer has let go, and how many sources it asked the last time.
// Kept so that a test can tell "it was asked and nothing came of it" from "it was never
// asked at all" -- two failures that look identical on screen and have quite different
// causes. Read through `window.zmartLetGo`; see App.jsx.
export const lettingGo = { times: 0, asked: 0 };

export function letGoOfDecodedPieces(viewer) {
  // The pieces are held by objects shared with the worker that decodes them, and the
  // engine keeps its side of that conversation as a plain map. Anything in it that knows
  // how to let go is asked to; that is the sources holding image, and asking one that
  // holds nothing costs nothing.
  const shared = viewer.chunkManager?.rpc?.objects;
  if (!shared) return 0;
  let asked = 0;
  for (const [, held] of shared) {
    if (!held || typeof held.invalidateCache !== "function") continue;
    held.invalidateCache();
    asked += 1;
  }
  lettingGo.times += 1;
  lettingGo.asked = asked;
  return asked;
}

/**
 * How many stores are still queued across the whole scene.
 *
 * Zero means everything the panel asked for has been handed to the engine. The browser
 * tests use it to tell "still arriving" apart from "this is all there is", which is
 * precisely the distinction that was missing when positions were being lost in silence.
 */
/**
 * How many stores this page has still to hand over — **not** how many the engine
 * has still to read.
 *
 * The difference matters and has cost real measurements. What is counted here is
 * the page's own queue draining: stores it has been given and not yet passed on.
 * The engine goes on reading each one's description afterwards, and that is the
 * slow part. Traced on a run of a hundred stores, this reached nought with **30**
 * of them actually resolved; on four hundred, with **300**. So it reaches nought
 * at a different fraction of the work depending on how many stores there are,
 * which is the worst possible behaviour for anything comparing one size against
 * another — two runs stop at different amounts of finished work and the
 * difference between them looks like a result.
 *
 * A measurement that wants a settled page should wait on every store having a
 * load state of its own, not on this.
 */
export function sourcesStillWaiting(viewer) {
  let total = 0;
  for (const managed of viewer.layerManager.managedLayers) {
    const feed = managed.layer && feeding.get(managed.layer);
    if (feed) total += feed.waiting.length;
  }
  return total;
}

/**
 * Forget what the engine was told about one store, so that asking again really asks.
 *
 * Neuroglancer remembers the answer to every question it has asked about a store —
 * the small files describing how many frames there are, how big a voxel is, where
 * the copies of the image live. That memory is the right thing almost always: opening
 * the same acquisition in a second window, or coming back to it later, costs
 * nothing. But it is held for as long as the page is open and there is no time
 * limit on it, so when a timelapse grows the engine will keep answering "two
 * frames" from memory and never look at the disk again. Handing a data source its
 * own address back is not enough on its own: it does make the engine resolve the
 * store afresh, but the resolving is answered out of the same memory, so nothing
 * is re-read and nothing changes. That was measured — after an announcement the
 * page asked for no description files at all.
 *
 * So the remembered answers about this one store are dropped first. What is dropped
 * is only what was *read* about it. The pieces of image themselves are remembered
 * separately, and those entries are left strictly alone — they are recognisable
 * because they name the kind of object that holds decoded image rather than a file
 * that was fetched. Dropping one of those would not free anything (the layer is
 * still using it) but it would make the engine build a second one beside it and
 * fetch every piece again, which is the exact cost this whole path exists to avoid.
 *
 * Two things are worth knowing if you are changing this:
 *
 * - Removing the entry does not throw anything away. It only means the next question
 *   is answered by looking rather than by remembering. Anything still in use is held
 *   by the layer using it and stays alive.
 * - These entries are never removed on their own. Neuroglancer takes a reference each
 *   time one is used and never gives it back, so they last as long as the page does.
 *   That is why forgetting has to be done deliberately here, and also why doing so is
 *   safe: there is no tidying-up already scheduled that this could collide with.
 */
function forgetWhatWasReadAbout(chunkManager, url) {
  const remembered = chunkManager?.memoize?.map;
  if (!remembered) return;
  // The address the panel writes ends in the name of the reader to use --
  // ".../pos001.ome.zarr/|zarr2:". The files themselves sit under the part before
  // that, which ends in a slash, so it cannot accidentally match a differently
  // named store that merely starts the same way (pos001 against pos0011).
  const folder = url.split("|")[0];
  if (!folder) return;
  for (const question of [...remembered.keys()]) {
    if (!question.includes(folder)) continue;
    // Anything naming a class of object is a holder of decoded image, not a file
    // that was read. Leave those exactly where they are; see above for why.
    if (question.includes('"constructorId"')) continue;
    remembered.delete(question);
  }
}

/**
 * Drop cached knowledge and decoded absence for one aggregate source only.
 *
 * A newly committed tile may occupy coordinates this source previously found
 * empty.  Metadata-only forgetting is therefore insufficient: the empty chunk
 * holder would survive and no pixel request would be made.  Neuroglancer files
 * both kinds of memoized object under keys containing the store folder; decoded
 * holders are the entries naming a constructor. Metadata identities are removed
 * so the existing layer's source re-resolution reads them again. Each matching
 * decoded holder is asked to clear its own chunks, while holders belonging to
 * every other stable URL remain untouched.
 */
function forgetOneStableSource(chunkManager, url) {
  const remembered = chunkManager?.memoize?.map;
  const removed = { metadata: 0, decoded: 0 };
  if (!remembered) return removed;
  const matching = memoEntriesForStableSource(remembered.keys(), url);
  for (const question of matching.metadata) {
    if (remembered.delete(question)) removed.metadata += 1;
  }
  for (const question of matching.decoded) {
    const holder = remembered.get(question);
    if (holder && typeof holder.invalidateCache === "function") {
      holder.invalidateCache();
      removed.decoded += 1;
    }
  }
  return removed;
}

function revisionsFor(spec) {
  return sourceRevisionsFor(sourceList(spec), spec.sourceIds, spec.sourceRevisions);
}

// -- bringing the engine into line with the panel -----------------------------
//
// This is the heart of the module: given the scene the panel wants, change as
// little as possible to reach it. One function per kind of change — the images a
// layer reads from, the settings the operator turns, the order the layers are drawn
// in — and `syncLayers` below puts them together.

/**
 * Give one layer any images it does not yet have.
 *
 * A row in the panel can be drawn from several stores at once — the same channel
 * of the same acquisition type, recorded at a dozen stage positions — and during a
 * run those positions appear one at a time. Adding the new one to the layer that
 * is already there costs nothing; rebuilding the layer would throw away the
 * eleven positions that were fine.
 *
 * Only additions are made. A position is never removed on its own: closing things
 * is done a whole acquisition type at a time, which removes the layer outright, so
 * there is no case where a layer should quietly lose one of its images.
 *
 * Returns how many images were added, so the caller knows whether the shape of
 * the scene changed.
 */
function syncSources(
  layer,
  spec,
  reread = false,
  chunkManager = undefined,
  forgotten = null,
  refreshed = null,
) {
  const wanted = sourceList(spec);
  // Held as a set rather than a list. A row can be drawn from as many stores as
  // the run has positions, and asking a list "do you already contain this?" for
  // each of them means walking the whole list every time -- which for a few
  // thousand positions is most of a second, spent on every single step of a
  // contrast drag, on the same thread the engine draws with.
  const already = sourcesApplied.get(layer) || new Set();
  const fresh = wanted.filter((url) => !already.has(url));

  // A valid higher revision refreshes the stable aggregate source inside this
  // existing layer.  No URL is added and the layer is not rebuilt, so camera and
  // every operator-owned setting stay where they are.
  const revisions = revisionsFor(spec);
  const lastRevisions = revisionsSeen.get(layer);
  const advanced = advancingSourceRevisions(lastRevisions, revisions);
  if (revisions.size) {
    revisionsSeen.set(layer, rememberedSourceRevisions(revisions));
  }
  if (advanced.length) {
    const growing = new Map(
      advanced.map(([identity, value]) => [value.url.split("|")[0], identity]),
    );
    for (const source of layer.dataSources) {
      const store = source.spec.url.split("|")[0];
      const identity = growing.get(store);
      if (identity == null) continue;
      if (!refreshed || !refreshed.has(identity)) {
        const removed = forgetOneStableSource(chunkManager, store);
        sourceRefreshing.sources.push(identity);
        sourceRefreshing.metadataEntries += removed.metadata;
        sourceRefreshing.decodedEntries += removed.decoded;
        if (refreshed) refreshed.add(identity);
      }
      // Resolves the same stable address again after its affected memoized
      // entries were removed.  This changes the source, not the layer.
      source.spec = { ...source.spec };
    }
  }

  // Which of this row's stores have gained a frame since the last look.
  //
  // An announcement says only that *something* on disk has changed, never what, so
  // the counts the server reports are the only way to tell. They are per store, and
  // that matters: a row can hold a position for every place the microscope visited,
  // and asking all of them whether they have grown -- when the answer for all but
  // one of them is no -- was measured at a thousand positions as six thousand small
  // requests and eighteen seconds for a single frame landing. Comparing per store
  // makes that one store, however many there are.
  //
  // A row with no time axis reports no counts and so is never re-read at all, which
  // is right: nothing about it can grow.
  const counts = spec.frameCounts;
  const lastCounts = framesSeen.get(layer);
  const grown =
    reread && Array.isArray(counts) && lastCounts
      ? wanted.filter((url, at) => lastCounts.get(url) !== undefined
                                   && lastCounts.get(url) !== counts[at])
      : [];
  if (Array.isArray(counts)) {
    framesSeen.set(layer, new Map(wanted.map((url, at) => [url, counts[at]])));
  }
  if (grown.length) {
    // Ask the stores that were already open what they say about themselves now.
    //
    // This is what happens when a timelapse gains a frame. The store is already
    // open and the engine already holds its address, so there is nothing to add --
    // but the engine also still believes the length it read when it first looked,
    // and the slider will not reach a frame it does not know about. Handing a data
    // source its own address back makes the engine let go of what it worked out and
    // ask again.
    //
    // What this costs, measured rather than assumed, because it is more than it
    // looks. Re-reading the descriptions themselves is genuinely cheap: a few
    // hundred bytes per store, served with instructions never to keep a copy, so
    // what comes back is the truth. But the engine files its decoded image under a
    // key that includes the array's shape, so when the shape has genuinely changed
    // the pieces on screen are filed under a new key and fetched again. It is
    // bounded -- the frame being looked at, not the whole timelapse -- and it
    // happens once per growth, but it is not free, and a viewer left on a fast
    // timelapse will pay it repeatedly.
    //
    // The happier half of the same fact: when a store's description comes back
    // unchanged -- an acquisition that declared its length up front and is filling
    // in the frames it already promised -- the key is unchanged too and nothing at
    // all is re-fetched. That case is pinned by
    // test_frames_arriving_do_not_disturb_what_is_shown.
    //
    // The forgetting has to come first. Without it the engine resolves the store
    // again but answers itself from what it already remembers, so the re-read never
    // reaches the disk and the length never moves. See forgetWhatWasReadAbout above.
    //
    // Note that this happens *as well as* adding anything new below, not instead of
    // it. One announcement can mean both -- a position finished and another gained a
    // frame -- and an earlier version that treated them as alternatives quietly
    // stopped new positions appearing at all.
    // Matched on the folder each address points at rather than on the address
    // itself. Neuroglancer tidies up an address it has been handed, so what comes
    // back out is not always character-for-character what went in -- and a
    // comparison that got that wrong here would quietly re-read nothing at all.
    const growing = new Set(grown.map((url) => url.split("|")[0]));
    for (const source of layer.dataSources) {
      const store = source.spec.url.split("|")[0];
      // The stores that did not grow are left completely alone. This is the line
      // that turns a thousand positions from six thousand requests into six.
      if (!growing.has(store)) continue;
      // And a store that did grow is forgotten once, not once per row that reads
      // from it. A store holding two channels feeds two rows, and forgetting per
      // row meant the second row throwing away the very files the first had just
      // fetched and asking for them again. Re-resolving still happens for every row
      // that reads the store, because each row's own sense of how long the image is
      // has to be brought up to date -- it is only the forgetting that is shared.
      // The second row then finds the first row's request already in flight and
      // waits for it rather than making one of its own.
      if (!forgotten || !forgotten.has(store)) {
        forgetWhatWasReadAbout(chunkManager, store);
        if (forgotten) forgotten.add(store);
      }
      source.spec = { ...source.spec };
    }
  }

  if (fresh.length) {
    // Queued rather than handed straight over, so that a great many arriving at once
    // are offered to the engine in groups. While the microscope is running this is a
    // single position, which becomes a group of one and reaches the engine
    // immediately; see the notes above keepHandingOver for why there is
    // deliberately no separate path for that case.
    //
    // Pushed one at a time rather than spread into the call, because a spread of forty
    // thousand addresses is forty thousand arguments and the browser refuses calls that
    // large.
    const feed = feedFor(layer);
    for (const url of fresh) feed.waiting.push(url);
    hungry.add(layer);
    // Recorded as applied as soon as they are queued. From here on they belong to the
    // feeding above, and a later pass over the same scene must not offer them a second
    // time while the first offer is still working its way through the queue.
    sourcesApplied.set(layer, new Set(wanted));
  }
  return fresh.length;
}

/**
 * Write the adjustable settings of one layer.
 *
 * These are the things the operator changes constantly — contrast, colour,
 * opacity, whether a channel is showing — so this runs very often and does as
 * little as possible. Each setting is a value the engine watches, and writing the
 * value it already holds is ignored, so setting all of them and letting the engine
 * notice which actually moved is both correct and cheap.
 */
function applySettings(managed, spec) {
  const visible = spec.visible !== false;
  if (managed.visible !== visible) managed.setVisible(visible);
  const layer = managed.layer;
  if (!layer) return;
  if (spec.type === "image") {
    // The shader is the small program that turns stored numbers into what you
    // see: it carries the channel colour and any colour map. Setting it to the
    // text it already holds is ignored by the engine, so this is free whenever
    // the colour has not changed -- which is nearly always.
    if (spec.shader != null) layer.fragmentMain.value = spec.shader;
    // The contrast window and the 3-D opacity travel separately, as values for
    // controls the program declares. Sent this way they reach a program that is
    // already compiled, so dragging a contrast handle costs the graphics card
    // almost nothing however many layers are open.
    if (spec.shaderControls) layer.shaderControlState.restoreState(spec.shaderControls);
    if (spec.opacity != null) layer.opacity.value = spec.opacity;
    layer.volumeRenderingMode.restoreState(spec.volumeRendering ?? "off");
    if (spec.volumeRenderingDepthSamples != null) {
      layer.volumeRenderingDepthSamplesTarget.value = spec.volumeRenderingDepthSamples;
    }
    // Gain has to be named here or it goes nowhere. Nothing in this function
    // restores a whole specification; every field is carried across by a line of
    // its own, so a field added to the specification and not to this list is
    // dropped in silence -- which is exactly what happened when this control was
    // first added, and why it appeared to have no effect while the depth fade
    // beside it worked. That one travels as a shader control, and those are
    // restored wholesale two lines above.
    if (spec.volumeRenderingGain != null) {
      layer.volumeRenderingGain.value = spec.volumeRenderingGain;
    }
  } else if (spec.type === "segmentation") {
    // A mask has no brightness to adjust; how strongly it is painted over the
    // image is the only thing there is to set.
    layer.displayState.selectedAlpha.value = spec.selectedAlpha ?? 1;
    layer.displayState.notSelectedAlpha.value = spec.notSelectedAlpha ?? 0;
  } else if (spec.type === "annotation" && spec.annotationColor) {
    layer.annotationDisplayState.color.restoreState(spec.annotationColor);
  }
  // Note what is deliberately absent: for an annotation layer, the annotations
  // themselves. Once the layer exists, the drawings inside it belong to the
  // engine, and the panel's list is a reflection of them rather than the other way
  // round. Writing them back here is what used to erase whatever had just been
  // drawn.
}

/**
 * Put the layers in the order the panel shows them.
 *
 * This is a real setting rather than tidying: the engine paints the list from
 * bottom to top, so the order decides which acquisition type covers which.
 */
function applyOrder(manager, names) {
  // Where each layer currently sits, looked up once. Searching the list for every
  // name instead costs the square of the number of layers, which at a few thousand
  // is tens of milliseconds -- again on every step of a slider drag.
  const at = new Map(manager.managedLayers.map((managed, index) => [managed.name, index]));
  names.forEach((name, wanted) => {
    const here = at.get(name);
    if (here === undefined || here === wanted) return;
    manager.reorderManagedLayer(here, wanted);
    // Moving one layer shifts the others, so the map is rebuilt rather than
    // trusted. This happens only when the order has genuinely changed.
    manager.managedLayers.forEach((managed, index) => at.set(managed.name, index));
  });
}

/**
 * Bring the engine's layers into line with what the panel is asking for.
 *
 * ``specs`` is the scene the panel wants, in the order it should be drawn, each
 * entry written the way Neuroglancer describes a layer.
 *
 * Returns how many layers were built, removed or given a new image — in other
 * words, how much of the scene actually changed shape. That number matters
 * because it is the only case where the engine has to work out where everything
 * sits in space again, so the interface uses it to decide whether the view needs
 * putting back where the operator had it. It is also what the browser tests
 * watch: for an ordinary change — a slider moved, a channel hidden — it must be
 * zero.
 *
 * Pass ``reread`` when something on disk has changed — that is, on the pass that
 * follows an announcement. It means "check whether anything already open has grown",
 * not "re-read everything": only a row whose frame count has actually moved is read
 * again, and its layers are left exactly as they are while that happens. This is the
 * one case where nothing is added to the scene and yet something must still happen.
 */
export function syncLayers(viewer, specs, { reread = false } = {}) {
  const manager = viewer.layerManager;
  const wanted = new Set(specs.map((spec) => spec.name));
  let reshaped = 0;
  // The stores already forgotten on this pass, so that a store feeding several
  // rows is forgotten once rather than once per row. See syncSources.
  const forgotten = new Set();
  const refreshed = new Set();
  sourceRefreshing.passes += 1;
  sourceRefreshing.sources = [];
  sourceRefreshing.metadataEntries = 0;
  sourceRefreshing.decodedEntries = 0;

  // Anything the panel no longer lists has genuinely been closed, so let it go.
  // Doing this first also frees the name, in case something new is taking it.
  for (const managed of [...manager.managedLayers]) {
    if (wanted.has(managed.name)) continue;
    if (managed.layer) stopFeeding(managed.layer);
    deleteLayer(managed);
    reshaped += 1;
  }

  // How many layers this pass will build. The stores they are built with have to add up
  // to one group between them rather than one group each, for the same reason the
  // feeding budget is shared: four rows each starting with two hundred stores is eight
  // hundred at once, which is the burst all of this exists to avoid.
  const building = specs.filter((spec) => {
    const already = manager.getLayerByName(spec.name);
    return !already || already.layer?.type !== spec.type;
  }).length;
  const firstShare = Math.max(1, Math.floor(howManyAtATime() / Math.max(1, building)));

  specs.forEach((spec, index) => {
    let managed = manager.getLayerByName(spec.name);
    // A layer that has changed kind — an image where there was a mask — cannot be
    // adjusted into the other; that one really does have to be built again.
    if (managed && managed.layer?.type !== spec.type) {
      if (managed.layer) stopFeeding(managed.layer);
      deleteLayer(managed);
      managed = undefined;
      reshaped += 1;
    }
    if (managed) {
      reshaped += syncSources(
        managed.layer,
        spec,
        reread,
        viewer.chunkManager,
        forgotten,
        refreshed,
      );
      applySettings(managed, spec);
      return;
    }
    // A layer is built with at most one group of stores, and the rest are fed to it
    // afterwards. This is where the loss described above actually happened, and it is
    // worth saying why, because it is not where it appears to be. When a folder is
    // opened cold the layer does not exist yet, so it is built from a description that
    // already names *every* position — and the engine reads the lot inside the
    // constructor, in one burst, before this module has any say in it. Pacing only the
    // stores added later would have left a cold open exactly as broken as it was.
    const stores = sourceList(spec);
    const rest = stores.slice(firstShare);
    managed = makeLayer(
      viewer.layerSpecification,
      spec.name,
      rest.length ? { ...spec, source: stores.slice(0, firstShare) } : spec,
    );
    // Building from the description already applied everything in it, including
    // the images; record them so the next pass does not add them a second time.
    sourcesApplied.set(managed.layer, new Set(stores));
    if (rest.length) {
      const feed = feedFor(managed.layer);
      for (const url of rest) feed.waiting.push(url);
      hungry.add(managed.layer);
      // What the constructor has just started reading counts against the shared budget
      // like any other group, so the next group waits for it. Without this the second
      // group would be offered immediately and the burst would simply be twice as large.
      inFlight = inFlight.concat(managed.layer.dataSources);
    }
    // Likewise how far along each of its stores was when it was built, so that the
    // first announcement after it appears does not mistake "I have never asked" for
    // "this has grown" and re-read every store on the row for nothing.
    if (Array.isArray(spec.frameCounts)) {
      framesSeen.set(
        managed.layer,
        new Map(sourceList(spec).map((url, at) => [url, spec.frameCounts[at]])),
      );
    }
    const initialRevisions = revisionsFor(spec);
    if (initialRevisions.size) {
      revisionsSeen.set(managed.layer, rememberedSourceRevisions(initialRevisions));
    }
    viewer.layerSpecification.add(managed, index);
    reshaped += 1;
  });

  applyOrder(manager, specs.map((spec) => spec.name));
  // Start handing over only once the whole pass is done. Started earlier — from inside
  // the loop above — the first row would begin feeding before the other rows had even
  // been built, so it would take the whole budget for itself and the rows built a moment
  // later would have their first stores read outside it. Doing it here means every row
  // that wants stores this pass is known before any of them are offered. Costs nothing
  // when there is nothing waiting, which is the ordinary case.
  keepHandingOver();

  return reshaped;
}

// -- settling the view when an image is first opened --------------------------
//
// Three things have to be decided the moment an image says how big it is, and all
// three were wrong at some point in a way that produced a picture nobody could see:
// which axes to draw, where in time to start, and how far to zoom. They happen once,
// before anybody is looking, and afterwards the operator is in charge.

/**
 * Draw the axes that measure distance, and leave the rest to the sliders.
 *
 * An image says what its axes are and what each one measures. Some are places in
 * the specimen — depth, height, width — and some are not: which moment this is,
 * or which colour of light was recorded. Only the first kind belongs on screen.
 *
 * The engine does not know that on its own. Left alone it takes the first three
 * axes the image declares, in the order they were written. For an image of a
 * single moment those happen to be depth, height and width and everything looks
 * right — which is exactly what made this hard to see. Add a time axis at the
 * front, as every timelapse has, and the first three become time, depth and
 * height: the engine draws time against depth and pins width, so the specimen is
 * nowhere on screen. Nothing reports a fault. The picture is simply black while
 * the data on disk is perfectly correct.
 *
 * Measured, on the same tiles in the same places: an image declaring one moment
 * filled the view, and an image declaring three drew nothing at all.
 *
 * Which axes measure distance is not guessed at. An image declares a unit for
 * each axis, and "m" — metres — is the only one that measures distance across a
 * specimen. Seconds do not, and an axis with no unit does not. That is the same
 * test the scale bar uses, for the same reason.
 *
 * The *order* they are handed over in matters as much as which ones they are, and
 * it cannot be chosen on its own. The engine decides what goes across the window,
 * what goes down it and what goes into the screen from two things together: the
 * order of this list, and which of its named panel layouts the viewer asks for.
 * The layout is chosen in `App.jsx`, next to `SLICE_LAYOUT`, and the two are a
 * matched pair. Change one without the other and the view comes out either
 * edge-on — looking at the specimen from the side, so a stack of planes collapses
 * to a line — or mirrored left to right, which is the quieter and more dangerous
 * of the two because the picture still looks perfectly healthy.
 *
 * The order used here is the reverse of the order the image declares. An OME-Zarr
 * image lists its distance axes slowest-changing first, which is depth, then
 * height, then width; reversing that gives width, height, depth, and asking for
 * the layout `App.jsx` calls `xy` then puts width across the window running to the
 * right, height down it, and depth into the screen — the plane the operator
 * scrolls through. That is the specimen the right way round.
 *
 * This was not always so. The viewer used to hand the axes over in the declared
 * order and ask for the layout called `yz`, which also put width across and height
 * down and looked entirely right, but ran width towards the *left*: every picture
 * was a mirror image of the specimen, and nothing said so. It is measured, from
 * the picture rather than from anything the engine reports about itself, in
 * `tests/test_the_picture_is_not_mirrored.py`.
 *
 * Note that none of this reads an axis by name. Which axes are drawn comes from
 * their unit, and which way round they go comes from the order the image declares
 * them in — so an image whose axes are called something other than z, y and x is
 * treated exactly the same way.
 *
 * An image declaring fewer than two such axes is left completely alone. We would
 * have nothing better to offer than the engine's own choice, and replacing a
 * possibly-odd view with a certainly-wrong one is not an improvement.
 */
function pinTheAxesThatMeasureDistance(viewer) {
  const space = viewer.navigationState.position.coordinateSpace.value;
  if (!space?.names) return;
  const distances = space.names.filter((_, at) => space.units?.[at] === "m");
  if (distances.length < 2) return;
  // Width first, depth last. The image declares its distance axes the other way
  // round -- depth, height, width -- so reversing them is what puts width across
  // the window and depth into the screen, which is what the `xy` layout asked for
  // in App.jsx expects. The two belong together; see the note above.
  const facing = distances.slice(0, 3).reverse();
  const current = viewer.navigationState.pose.displayDimensions.value;
  // Left alone when it is already right. Handing the engine the same answer it
  // already had is not free: it counts as a change, and everything downstream
  // that follows the view -- the zoom, the scale bar, the panel -- is asked to
  // catch up with a difference that does not exist.
  const showing = Array.from(current?.displayDimensionIndices ?? [])
    .filter((at) => at >= 0)
    .map((at) => space.names[at]);
  if (showing.length === facing.length
      && showing.every((name, at) => name === facing[at])) {
    return;
  }
  try {
    viewer.navigationState.pose.displayDimensions.restoreState(facing);
  } catch {
    // An engine that will not take them leaves the view as it was rather than
    // leaving the page broken. This runs while an operator is waiting for their
    // acquisition to appear, so it must not be the thing that stops it.
  }
}

/**
 * Open a timelapse at its first moment rather than half way through it.
 *
 * The engine opens every axis in the middle, which is the right thing to do for
 * the axes that measure the specimen — the middle of a stack is a sensible plane
 * to start on. Time is not like that. A recording is watched from the beginning,
 * and the middle of a run is not a place anybody asked for.
 *
 * There is a second reason, and it is the one that shows on screen. A timelapse
 * declares room for all the moments it could record and fills them in as the
 * experiment goes, so until the run ends most of its declared moments are empty.
 * Opening in the middle of one therefore means opening on a black screen, with
 * the recorded data sitting at the beginning, unseen and with nothing to say so.
 * Measured, on a store declaring three moments with only the first imaged: the
 * view opened blank, and moving to the first moment showed the specimen.
 *
 * This is not a rare shape. It is what every run in progress looks like, and what
 * an instrument that plans its length up front writes as well.
 *
 * The time axis is recognised by its unit — seconds — which is the same test used
 * for the axes that measure distance, and for the same reason: an image says what
 * its axes mean, so there is no need to guess from their names.
 *
 * This runs once, as the image is opened. Afterwards the operator is in charge of
 * where in time they are, and nothing here moves them again.
 */
function startTimeAtTheFirstMoment(viewer) {
  const { position } = viewer.navigationState;
  const space = position.coordinateSpace.value;
  if (!space?.names || !space.units) return;
  const at = Array.from(space.units).indexOf("s");
  if (at < 0) return;
  // The engine describes an axis by the extent the data covers, and says
  // separately whether a moment sits *on* a whole number or half way between two.
  // Both conventions occur, and the first moment has to be worked out for the one
  // in use or the view lands between two frames. This is the same reading the time
  // slider does -- see AxisSlider.jsx, where it is set out at length.
  const onWholeNumbers = space.bounds.voxelCenterAtIntegerCoordinates[at];
  const lower = space.bounds.lowerBounds[at];
  const first = onWholeNumbers ? Math.ceil(lower) : Math.ceil(lower - 0.5) + 0.5;
  if (!Number.isFinite(first) || position.value[at] === first) return;
  const moved = Float32Array.from(position.value);
  moved[at] = first;
  position.value = moved;
}

/**
 * Wait for the images to say how big they are, then let the engine choose the
 * starting magnification again.
 *
 * Without this the viewer opens on an empty grey rectangle, with the data
 * present and correct but drawn far too small to see. It is worth explaining
 * why, because the cause is nowhere near the symptom.
 *
 * The engine picks a starting magnification the first moment it believes it
 * knows what space the picture lives in. It expresses that magnification in
 * physical units — so many micrometres to a screen pixel — and it is careful
 * afterwards: if the size of a voxel changes, it adjusts the number so that what
 * is on screen stays the same real size. That is the right thing to do, and it
 * is exactly what hurts us here.
 *
 * The trouble is timing. We hand the engine its layers immediately, while the
 * images themselves are still being read over the network. For a moment there
 * are layers but no axes yet, and in that moment the engine considers the space
 * settled — an empty space, in which it has no voxel size to work from and falls
 * back to treating one voxel as one metre. It picks its ordinary default of one
 * voxel to a pixel, which now means *one metre* to a pixel. A little later the
 * real axes arrive saying a voxel is a third of a micrometre, and the engine
 * dutifully preserves the physical scale it was given. A specimen a tenth of a
 * millimetre across is then drawn about a ten-thousandth of a pixel wide, which
 * is to say invisibly, and the panel shows nothing but its own background.
 *
 * So we wait for the axes to actually arrive and then clear the magnification,
 * which makes the engine choose it once more — this time knowing how big a voxel
 * really is. This happens once, before anything is on screen, so it cannot
 * disturb an operator who has started looking around. Afterwards the engine's
 * careful adjustment is left alone, because from then on it is working from real
 * sizes and is right.
 *
 * Returns a function that stops the waiting, for the caller to use when the
 * viewer goes away.
 */
/**
 * Bring the picture back: centre what is on screen and choose the magnification
 * afresh, as if the image had just been opened.
 *
 * This exists because there was no way back. The only recentring the engine
 * offers is its right button, which centres on the point clicked -- and once an
 * operator has panned far enough that no part of the specimen is on screen,
 * there is nothing left to click on. The picture is still there, correctly
 * placed, and unreachable. The one button labelled Reset puts back the
 * brightness window and does not move the view, so pressing it in that state
 * changes the contrast of a picture nobody can see.
 *
 * **Only the axes being drawn are moved.** Where the operator is in depth or in
 * time is theirs, and losing your place in a stack because you asked to see the
 * whole field would be its own small betrayal. So the plane and the moment stay
 * where they were and the view slides back over them.
 *
 * The magnification is cleared rather than computed, for the reason set out at
 * :func:`chooseScaleWhenTheImagesAreMeasured` -- the engine's own default is
 * right once it knows how big a voxel is, and by the time anybody presses this
 * it does.
 *
 * Returns whether anything could be done, which is false only before the image
 * has said how big it is.
 */
/**
 * One press shows the whole picture: centred, and zoomed so it fits the window.
 *
 * The zoom is computed rather than reset, because the engine's default zoom
 * knows nothing about this picture -- on a survey it left the operator centred
 * but still deep in detail, filling a third of the window with specimen and
 * the rest with ground beyond it. How many pixels an axis of the picture
 * occupies is its voxel extent times the engine's own per-axis factor divided
 * by the zoom (the scale bar reads its size from the same arithmetic), so the
 * fitting zoom is whatever makes the largest axis just fill its side of the
 * window, with a small margin so the edge is visibly an edge.
 *
 * The volume view counts its zoom across the height of the panel rather than
 * per pixel, and its box can be turned, so the box is fitted against the
 * window's smaller side. Where a viewport or a bound is missing, the engine's
 * default zoom is kept -- a wrong guess dressed as a fit would be worse.
 */

// How much window the overview leaves around the picture. The picture's longest
// side fills the window divided by this, so 1.2 leaves about a sixth of the
// window as visible ground on that axis -- roughly eight percent a side, which
// on a full-screen window of the lab monitor is the two centimetres the
// operator judged right by eye. Proportional rather than a fixed distance, so
// a small window is not mostly margin. Chosen twice by the same operator on
// the 12,800-position survey: first that the exact fit needed an edge at all,
// then that the first margin wanted doubling.
const OVERVIEW_MARGIN = 1.2;

export function showTheWholePicture(viewer) {
  const { position } = viewer.navigationState;
  const space = position.coordinateSpace.value;
  if (!space?.rank) return false;

  // The first two display dimensions only -- the plane on screen. The third is
  // the depth the operator is looking through, and moving it would step them
  // somewhere else in the stack, which is what the test below caught: in a
  // cross-section the engine still counts the perpendicular axis as displayed.
  const render = viewer.navigationState.pose.displayDimensionRenderInfo.value;
  const drawn = Array.from(render?.displayDimensionIndices ?? []);
  const onScreen = new Set(drawn.slice(0, 2));
  const { lowerBounds, upperBounds } = space.bounds;

  const middle = Float32Array.from(position.value);
  for (let axis = 0; axis < space.rank; axis += 1) {
    if (!onScreen.has(axis)) continue;
    const low = lowerBounds[axis];
    const high = upperBounds[axis];
    if (Number.isFinite(low) && Number.isFinite(high)) middle[axis] = (low + high) / 2;
  }
  position.value = middle;

  const extent = (axis) => {
    const low = lowerBounds[axis];
    const high = upperBounds[axis];
    return Number.isFinite(low) && Number.isFinite(high) ? high - low : null;
  };

  let flat = null;
  let volume = null;
  for (const panel of viewer.display?.panels ?? []) {
    if ("sliceView" in panel) flat = panel.renderViewport;
    else if ("sliceViews" in panel) volume = panel.renderViewport;
  }

  let fit = 0;
  drawn.slice(0, 2).forEach((axis, slot) => {
    const across = extent(axis);
    const pixels = slot === 0 ? flat?.logicalWidth : flat?.logicalHeight;
    if (across === null || !pixels) return;
    fit = Math.max(fit, (across * render.canonicalVoxelFactors[slot]) / pixels);
  });
  if (fit > 0) viewer.navigationState.zoomFactor.value = fit * OVERVIEW_MARGIN;
  else viewer.navigationState.zoomFactor.reset();

  let boxFit = 0;
  const smaller = Math.min(volume?.logicalWidth ?? 0, volume?.logicalHeight ?? 0);
  drawn.slice(0, 3).forEach((axis, slot) => {
    const across = extent(axis);
    if (across === null || !smaller) return;
    boxFit = Math.max(
      boxFit,
      (across * render.canonicalVoxelFactors[slot] * volume.logicalHeight) / smaller,
    );
  });
  if (boxFit > 0) {
    viewer.perspectiveNavigationState.zoomFactor.value = boxFit * OVERVIEW_MARGIN;
  } else {
    viewer.perspectiveNavigationState.zoomFactor.reset();
  }
  return true;
}

export function chooseScaleWhenTheImagesAreMeasured(viewer) {
  const { position } = viewer.navigationState;
  // Axes, not images: a space with no axes is the placeholder described above.
  // The moment it has any, the engine knows how big a voxel is.
  const measured = () => (position.coordinateSpace.value?.rank ?? 0) > 0;
  let stop = () => {};
  const check = () => {
    if (!measured()) return;
    // Which axes are drawn is settled first, because how far to zoom is worked
    // out from what is being drawn. Choosing the zoom and then changing the axes
    // leaves the view scaled for a picture nobody is looking at.
    pinTheAxesThatMeasureDistance(viewer);
    // And then where in time to start, which is the beginning rather than the
    // middle the engine would otherwise choose.
    startTimeAtTheFirstMoment(viewer);
    // Clearing rather than setting a number of our own on purpose: the engine's
    // own default is a sensible starting point, and it is the one an operator
    // who has used neuroglancer elsewhere will expect. All that was ever wrong
    // with it was when it got decided.
    viewer.navigationState.zoomFactor.reset();
    viewer.perspectiveNavigationState.zoomFactor.reset();
    stop();
    stop = () => {};
  };
  stop = position.coordinateSpace.changed.add(check);
  // In case the axes are already known by the time we are asked -- reopening a
  // folder, say, where the descriptions are still in hand.
  check();
  return () => stop();
}

// -- the parts of the view that are not layers --------------------------------

/**
 * Set the parts of the view that are not layers: which panels are on screen, and
 * whether the engine draws its own furniture.
 *
 * Rebuilding the panel layout means new drawing surfaces, so it is done only when
 * the operator has actually switched between the flat view and the volume — never
 * as a side effect of some unrelated change.
 */
export function syncView(viewer, { layout, chrome }) {
  if (viewer.layout.toJSON() !== layout) viewer.layout.restoreState(layout);
  viewer.showDefaultAnnotations.value = chrome;
  viewer.showAxisLines.value = chrome;
  // Neuroglancer's own scale bars are off. It draws one per axis along the bottom
  // left, including one for time -- which looks like a distance and is not one. A
  // single bar for distance is drawn in the corner of the image instead, and it is
  // ours so it can be put somewhere out of the way. See ScaleBar.jsx.
  viewer.showScaleBar.value = false;
  // Black behind the slice, rather than the engine's mid-grey.
  //
  // Fluorescence images are mostly dark, and a grey surround sitting right up
  // against a dark specimen makes the specimen look brighter than it is -- the
  // eye judges brightness by comparison, so the same image reads differently
  // depending on what is next to it. Black is also simply what a microscopist
  // expects to see around an image.
  //
  // Worth knowing if you are debugging: this grey used to be the only clue that
  // nothing was being drawn at all, since an empty panel showed the engine's
  // background and a drawn one did not. That clue is no longer needed, because a
  // test now looks at the picture and fails if it is a flat colour -- see
  // tests/pixels.py. It is the test that makes this line safe to have.
  //
  // Written through `restoreState` rather than assigned: it parses the colour and
  // only writes when it differs from what is already there, and this function
  // runs on every change to the view.
  viewer.crossSectionBackgroundColor.restoreState("#000000");
}


/**
 * Stretch the picture along an axis without touching what is on disk.
 *
 * The engine keeps one factor per dimension of the coordinate space and applies
 * them to the display alone, so this changes how the specimen is drawn and
 * nothing about what it claims to be. That distinction is the whole reason this
 * is safe to offer: correcting a run whose declared voxel size is wrong is a
 * different act, with different consequences, and belongs somewhere harder to
 * reach than a panel.
 *
 * Which is also why anything above the panel has to say when a factor is not
 * one. A stretched picture with an unmarked scale bar is a way to take a wrong
 * measurement and never know.
 *
 * Factors are held by axis name rather than by position, because the space is
 * `t, z, y, x` here and `t, c, z, y, x` elsewhere, and an index would silently
 * scale the wrong thing on a store with a channel axis.
 */
export function stretchTheDisplay(viewer, byAxis) {
  const scales = viewer?.navigationState?.relativeDisplayScales;
  if (!scales) return;
  const names = viewer.navigationState.coordinateSpace.value?.names;
  if (!names) return;
  const factors = new Float64Array(scales.value.factors);
  let moved = false;
  names.forEach((name, index) => {
    const wanted = byAxis[name];
    if (typeof wanted === "number" && wanted > 0 && factors[index] !== wanted) {
      factors[index] = wanted;
      moved = true;
    }
  });
  if (moved) scales.setFactors(factors);
}
