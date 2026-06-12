# Microscope-Agnostic Layer Design

This layer is the vendor-neutral interface between smart-microscopy workflows
and microscope-specific integrations.

It is intentionally small. Workflows should ask for microscope operations in
domain terms; vendor drivers should remain free to handle the messy details of
their control software, logging, confirmations, limits, and calibration.

Status: under construction. The Leica Navigator Expert driver is working and
hardware-tested; this layer is not yet the production API used by the workflow.

## Goal

The goal is one stable workflow-facing surface for operations that are common
across microscope backends:

- connect to a microscope session;
- read and move stage position;
- apply named acquisition states or jobs;
- read and apply safety limits;
- acquire data and return a structured result;
- expose enough metadata for reproducible workflow outputs.

Vendor-specific behavior remains below this layer. For example, the Leica
driver's hybrid API/log confirmation strategy belongs in the Leica driver, not
in workflow code.

## Boundaries

Code belongs here when the same concept is useful across microscope vendors.

Code does not belong here when it depends on a specific control suite, file
format, hardware quirk, or validation probe. Those pieces stay in the vendor
driver, calibration, limits, or workflow folders.

## Current Shape

The current repository already has the pieces this layer should eventually
connect:

- `microscopes/driver/vendor/leica/navigator_expert/` contains the tested Leica
  integration.
- `microscopes/calibration/` contains microscope-specific calibration logic.
- `microscopes/limits/` contains safety-limit data and helpers.
- `microscopes/shared/` contains reusable, microscope-independent utilities.
- `workflows/target_acquisition/` is the current workflow consumer.

The next step is not to add a large abstraction. It is to extract the smallest
interface that the target-acquisition workflow actually needs, then implement a
Leica adapter behind it.

## Design Rules

- Keep the public surface small and explicit.
- Let drivers own source-specific evidence and confirmation details.
- Keep workflows free of vendor imports.
- Return structured results rather than loose dictionaries.
- Keep units explicit at the boundary.
- Add a new method only when a workflow needs it and a vendor adapter can test it.

## Non-Goals

- This is not a replacement for Micro-Manager or a hardware-device framework.
- This does not hide all vendor differences.
- This does not make untested microscope backends appear supported.
- This should not duplicate the Leica driver's confirmation or state-reader
  machinery.

## Acceptance Bar

The layer becomes production-ready only when:

- the target-acquisition workflow can run through it without importing the Leica
  driver directly;
- the Leica adapter passes the same offline and hardware gates as the direct
  driver path;
- the API is documented in the folder README;
- adding a second vendor would require a new adapter, not workflow rewrites.
