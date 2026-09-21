# Top plane index, absolute Slice, and mock stack jobs — superseded

This note described the Top and Slice view modes the operator carried on
2026-09-10: Top aligning every stack's first plane at index zero, Slice in
absolute specimen coordinates, and the Z slider under the picture that
walked them. On 2026-09-21 both modes and the slider were removed from the
operator: stacks in the viewer were slow and fragile with them in place, and
we had bitten off more than we could chew.

What stands now is in `NAMED_VIEWS_SIMULATOR.md`: the operator draws one
product of every acquisition, the maximum projection, so a stack lies flat
beside the single planes. The dropdown over the picture names the three ways
that are not built yet, greyed out, and nothing exists behind them.

The mock's stack jobs from this note remain: `Overview stack` (7 planes, 2 µm
step) and `Target stack` (11 planes, 1 µm step), three channels each. They
are what proves a stack arrives and is collapsed to its projection.

The shared viewer still supports Top and Slice for its own use; the operator
simply no longer asks for those products. Products of the two modes written
by earlier runs stay on disk, unused.
