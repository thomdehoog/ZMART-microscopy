# Smart Viewer 0.2 histogram and layer-panel UX inventory

This is the inspection record for the Smart Operator histogram/layer work
package. The reference is the separate `thomdehoog/ZMART-viewer` checkout at
version `0.2.0`, commit
`9ff10b04e803fbe2a71a1735a8065a845ea803dd`. The reference production page was
built and inspected in Chromium in both dark and light themes; its source and
relevant browser tests were also read before changing Smart Operator.

The aim is familiar behavior, not a React port or pixel-identical copy. The
Viewer page remains the authority for acquisition composition and measurement;
Smart Operator keeps its own panel state and its existing engine adapter.

## Behavior and visual differences

| Area | Smart Viewer 0.2 reference | Smart Operator before this package | Required Operator change |
| --- | --- | --- | --- |
| Hierarchy | Acquisition header with disclosure, acquisition eye, label, optional close action; indented channel rows share a vertical rule. | Acquisition eye, label, channel count, indented rows and rule; no disclosure. | Add disclosure and retain the compact Operator count; keep overview, focussing, and target as independent groups. |
| Selection | The selected channel row is tinted. The settings card repeats acquisition then eye, swatch, and channel name on the same tint. Selection is kept by stable layer key as config grows. | Row is tinted, but the settings card prints acquisition and channel as one text line without the eye/swatch relationship. Selection is a panel-local index and is lost on remount. | Store selection by stable channel key and repeat the selected row vocabulary above the histogram. |
| Visibility | Acquisition eye applies group visibility; channel state remains separate. Panel-owned state is applied to the engine and browser tests read the managed layers back. | Requested acquisition/channel visibility is already separate and survives the watch session; readiness is polled before applying it. Other panel state is not retained and disagreement is not surfaced. | Preserve the good two-level visibility rule, retain requested channel choices across group hide/show, and expose requested versus engine-observed state without allowing observed state to become a second owner. |
| Colour | A 13 px colour/map swatch is both indicator and control. A fixed-position list shows flat colours, LUT gradients, and a custom picker. | A 13 px flat-colour swatch opens the named flat palette; no custom colour or LUT preview. | Keep the Operator-native flat-colour boundary, add custom colour selection, stable persistence, and Viewer-like chosen feedback. LUT wiring is not invented where the adapter does not support it. |
| Opacity | Slider and editable percent value share the selected channel state and survive scene updates. | Slider plus non-editable percentage readout; value lives only on the current row object. | Make the value editable and persist it by stable channel key across source/config growth. |
| Histogram frame | 60 px histogram on an input-coloured ground. In-window bins are full strength; clipped bins are 25%; blue edge bars mark the window. Resting framing aims for 15%/85% while respecting image range. | Same broad look and edge dimming, but the frame is recomputed from the current window and current measurement only. | Retain the visual language while separating resting frame, operator axis, and window state. |
| Histogram pointer | Six-pixel edge hit zones drag one window edge. A drag elsewhere pans only the brightness axis. Wheel zooms the axis toward the pointer and suppresses page scroll. Double-click restores the resting axis without measuring or moving the window. | Only edge drag exists. Background drag, wheel zoom, and double-click reset do nothing. | Implement and test all four pointer behaviors without changing navigation or source transforms. |
| Axis and window values | Editable axis endpoints sit under the histogram around equal-sized Auto and Log buttons. Editable min/max boxes accompany their sliders. All controls align to the histogram. | Auto/Log sit on a short centred row. Axis endpoints are absent. Min/max are text outputs only. | Add aligned editable axis endpoints and editable min/max/opacity boxes; keep every value clamped and keep the two window edges at least one count apart. |
| Auto | One-shot press. It measures what is on screen through `/api/measure`, updates histogram/window, and reframes the axis. Empty/unavailable measurement leaves the window untouched. It has no pressed state. | Measures `[[0,0],[1,1]]` of the first source. Failure silently falls back to cached metadata; an older response can overwrite a newer action. | Use the adapter's visible-region description when available, keep Viewer responses authoritative, cancel superseded requests, reject stale responses, and show failure without resetting the window. |
| Log | Persistent per-control state. It applies `log1p` to count heights only; bar x positions, widths, brightness axis, and window do not move. | Count heights are logged correctly, but the state is panel-global and is lost on remount. | Persist Log per channel and prove positions stay fixed while heights change. |
| Current feedback | The selected channel is named twice; axis endpoints and editable min/max/opacity values show the current settings. | Selected text and read-only min/max/opacity values are present, but pointer brightness/count and request state are absent. | Add pointer brightness/count feedback and explicit idle/measuring/failure status while retaining the selected-channel cues. |
| Arrival/config growth | App-owned state is matched by stable layer key when config changes; stable live sources are synchronized into existing layers. | Stable source growth uses `addSources` without remounting the Viewer or panel. A shape change rebuilds both; only visibility maps survive. | Keep stable growth in place; persist selection, colour, opacity, window, axis, Log, collapse, and visibility for any necessary panel rebuild. |
| External engine changes | Tests deliberately perturb a live layer and prove the App's next description restores the owned state. | Tests can inspect `layersForMeasurement`, but the panel neither records nor reports a mismatch. | Poll only the local adapter snapshot, record requested and observed values separately, visibly report a mismatch, and deterministically reapply requested state. No network poll is added. |
| Order and coordinates | Group order is presentation state; source transforms are built separately. | `watching-the-run.js` explicitly supplies overview first and focussing last for drawing. | Keep panel order and drawing order explicit and separate. Visibility/order actions must leave all source matrices and canonical Z anchors byte-for-byte unchanged. |

## Reference tests inspected

- `tests/test_layer_panel.py`: selection, histogram truth, edge dragging,
  dimmed clipped bins, editable values, Auto, Log, alignment, colours, opacity.
- `tests/test_layer_groups.py`: acquisition/channel hierarchy, group eyes,
  collapse without visibility change, per-channel settings.
- `tests/test_auto_reads_what_is_on_screen.py`: visible-region Auto, exclusion of
  unimaged ground, empty/off-picture behavior, pyramid choice.
- `tests/test_open_and_close.py`: acquisition arrival and preservation of
  settings on layers that remain open.
- `tests/test_no_setting_is_dropped_on_the_way_to_the_engine.py`: requested
  settings are reapplied to live engine layers rather than merely changing the
  panel.

## Implementation decision

`LayerPanel.jsx` is coupled to the Viewer's React application state, scene
descriptions, LUT registry, volume controls, open/close workflow, and direct
Neuroglancer viewer. Importing it would introduce duplicate authorities and
would cross the Operator engine-adapter boundary. Copying the component would
also create an unmaintainable second frontend.

The package therefore reproduces the proven 2-D interaction contract behind
Smart Operator's existing vanilla-DOM panel and engine handle. Shared concepts
are kept small and explicit: stable channel keys, requested panel state, an
abortable measurement client, histogram axis arithmetic, and an observed-state
snapshot. Neuroglancer details remain in its adapter.

This work does not change source composition, view ownership, XY placement, or
the canonical display-Z transform.
