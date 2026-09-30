# ZMART Controller

[![python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)](pyproject.toml)
[![tests](https://img.shields.io/badge/tests-pytest-blue)](#testing)


The **ZMART Controller** provides a small universal schema for driving a microscope from Python. 
You build you workflow on this schema and it runs on any microscope that has a ZMART-driver plugged into it. 
The is part of the **ZMART** (ZMB`s Microscopy-Agnostic Research Toolkit) tools we use for smart microscopy
at the Center for Microscopy and Image Analysis (ZMB), University of Zurich.  


## The Problem

Every microscope comes with its own programming interface, so workflow that is build for one microscope
does not work on another. 

This provide a real obstacle sharing our workflows and deploying them one all the microscopes we want.


## The Solution

The ZMART controller lives between your workflow and the microscope:

1. **One universal interface.** A short list of plain commands to move xyz,
    get and set a state of the microscope, and acquire an images.

2. **A schema, not a driver.** It provide consistent interoperable vocabulary
   that ZMART-driver plugin to. The drivers take care of interacting with the microscope, enforcing limits
and provide a single absolute coordinate systems that corresponds to the space in which you observer the specimen


```
  ┌──────────────────────────────────────────────────────────────┐
  │  your notebook, script or AI agent      (the workflow)       │
  └──────────────────────────────┬───────────────────────────────┘
                     commands    │    answers and refusals, unchanged
  ┌──────────────────────────────┴───────────────────────────────┐
  │  ZMART Controller                        (this package)      │
  │                                                              │
  │  simple vocabolary interoperable vocabulary                  │
  └───────┬──────────────────────┬──────────────────────┬────────┘
          │                      │                      │
  ┌───────┴───────┐      ┌───────┴───────┐      ┌───────┴───────┐
  │   driver A    │      │   driver B    │      │  your driver  │
  └───────┬───────┘      └───────┬───────┘      └───────┬───────┘
          │                      │                      │
  ┌───────┴───────┐      ┌───────┴───────┐      ┌───────┴───────┐
  │ microscope A  │      │ microscope B  │      │      ...      │
  │ own software  │      │ own software  │      │               │
  └───────────────┘      └───────────────┘      └───────────────┘
```

Note: we are aware of the useq schema from micro managar and the model hardware standart of antropic. We might switch because both have real upsides, but currently the useq-schema is not interoperable enough for our needs and the model hardware standaard is not released to the public yet.


### The vocabulary

Everything you can say to a microscope:

```python
import zmart_controller

# 1) See which microscopes are available, and connect to one
zmart_controller.get_instruments()
zmart_controller.set_instrument(instrument=Dict)

# 2) Learn about the connected setup
zmart_controller.get_info()

# 3) Discover the motors, then read or move the position (micrometers)
zmart_controller.get_actuators()
zmart_controller.get_xyz()
zmart_controller.set_xyz(x, y, z, with_actuators=Dict)

# 4) Capture the instrument settings, and apply them again later
zmart_controller.get_state()
zmart_controller.set_state(Dict)

# 5) Capture and save an image with the current settings and position
zmart_controller.get_acquisition_options()
zmart_controller.acquire(acquisition_type=String, position_label=String, options=Dict)

# 6) Run a routine the microscope offers (for example autofocus)
zmart_controller.get_procedures()
zmart_controller.run_procedure(Dict)

# 7) Close the connection
zmart_controller.disconnect()
```

Every command answers with the same two things:

```python
{"success": True, "report": {...}}
```

`success` says whether the driver did what you asked. `report` is whatever the
driver has to say about it: a position, a saved-file record, a state. When
something goes unexpected the answer is `success: False` and further details can be read in "report". 
We have not defined a vocabulary for error messages at this point.


### What is no longer your problem

Because the controller is this simple, a whole class of problems stops being
yours as soon as you write against it:

- **In an experiment**, you never touch vendor code, units, stage conventions
  or safety limits. If a move is unsafe, the driver refuses and you see why.
  
- **In a driver**, you never think about workflows, other microscopes or the
  controller's internals. You implement one function per command the controller ask for.
  
- **In the controller**, there is nothing to maintain. It keeps no state,
  caches nothing and refuses nothing of its own, so it cannot drift out of step
  with a microscope.

## Try it yourself 

 < here should be links to tutorials >
 - install and test it with a mock driver
 - build your own workflow on top of the driver
 - build driver functions the plug in the the ZMART-controller
 
### Status
This is version 0.1. We are currently using this in workflows for smart microscopy at the ZMB for Leica and Evident.
We are considering exapanding this to Nikon, Zeiss and the MesoSPIM platform.

## Status and Author
Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).

## License
MIT License. See LICENSE file for details.
