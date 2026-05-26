"""Core API subpackage for the LAS X driver.

Contains the 10 core modules that implement the command dispatch
pipeline: utils, errors, readers, settings, prechecks, confirmations,
core, profiles, commands, and session.

These modules were moved from the flat driver/ level as part of the
Phase F restructuring. Compatibility shims at the old driver/ paths
re-export all public names.
"""
