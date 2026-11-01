/**
 * Step 10 — Run protocol.
 *
 * The run without presses. Every step above has been settled on this sample
 * and confirmed -- green -- and this one walks them in turn over the whole
 * scan area: the focus map measured when there is none on this sample yet,
 * the overview scanned, the objects detected, the gates applied, the scan
 * areas placed, the targets acquired. What it was told is written out at the
 * end as the protocol, the file the next sample's session is opened with.
 *
 * Its box holds this press and, after a run, the run's numbers. The press
 * is greyed while any step above stands orange: an orange step is one made
 * under settings that have since changed, and a run that started over it
 * would be a run over something nobody looked at. The step itself is never
 * orange -- it has no settings, it runs.
 *
 * `run.ts` walks the steps; `channel.ts` holds the box.
 */

import { staleSteps } from "zmart-interface/api";
import type { TaStep } from "../../types.ts";
import { protocolChannel } from "./channel.ts";
import { afterTheProtocolPress, protocolBlockers, runProtocol } from "./run.ts";

export const runProtocolStep: TaStep = {
  id: "protocol",
  title: "Run protocol",
  btn: "Run protocol",
  panels: [],
  ms: 0,
  mode: "protocol",
  ready: (run, page) => {
    const stale = staleSteps(page.steps(), run.done, run.stale);
    if (stale.length) return `confirm ${stale.map((s) => s.title).join(", ")} first`;
    /* And what a later step would stop on: said now, not at step 8. */
    const blockers = protocolBlockers(page);
    return blockers.length ? blockers[0] : null;
  },
  /* This step walks the others, so it is not run through the page like
     them: its press walks the steps itself (`run.walk` says while it does),
     and the walk's Interrupt is the framework's. Saying `walks` is also what
     tells the framework that an edit above this step leaves it neither done
     nor orange -- it has no settings of its own to confirm. `whileWalking`
     is said beside the walk's Interrupt, in whichever step's box it stands. */
  walks: { press: runProtocol, whileWalking: "running the protocol" },
  again: "Rerun protocol",
  afterThePress: afterTheProtocolPress,
  /* The protocol's box says what the run came to in its own line. */
  noHint: true,
  channel: protocolChannel,
};
