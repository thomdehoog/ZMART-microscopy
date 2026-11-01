# Plan: an easy install, and a start button

*Status: a draft for review, 1 November 2026. Nothing has been changed yet.*

## In short

Installing ZMART today means knowing about conda environments, five
repositories, branches, analysis environments and a setting called
`ZMART_INTERFACE_WORKFLOWS`. That is fine for checking the blocks together,
which is what `install.py` is for, but it is too much for someone who wants
to use the microscope.

This plan adds two things to ZMART Microscopy:

1. **One installer, `setup_zmart.py`,** that asks two plain questions and
   does everything else, for people who do not write code and for people who
   do.
2. **A start button:** a file you double-click (and an icon on the desktop)
   that opens the operator window, already pointed at our workflows.

`install.py` stays as it is: it remains the test bench that installs branches
and runs the checks.

## Who gets what

| | Does not write code | Writes code |
|---|---|---|
| The operator window | yes | yes |
| The analysis environments the window uses | yes | yes |
| Jupyter, and the notebooks in `workflows/coders/notebooks/` | no | yes |
| The analysis environments the notebooks use | no | yes |
| On the desktop | **Start ZMART** | **Start ZMART** and **Start ZMART notebooks** |

## The installer

From a copy of ZMART Microscopy, with conda installed (Miniforge, conda-forge
only):

```
python setup_zmart.py
```

It asks:

1. **Do you write code?** No: the operator window. Yes: the window, and the
   notebooks with Jupyter.
2. **Which microscope is this computer for?** For now: the mock microscope
   (to try ZMART without a microscope) or the Leica. More come with the
   drivers plan, which gives each microscope its own folder here.

Then, without further questions, it:

- creates one conda environment, `zmart`, from conda-forge;
- installs the blocks at the **released versions this copy of ZMART
  Microscopy names**, never at a branch, so every computer installed from the
  same copy runs the same code;
- installs the driver for the chosen microscope;
- makes the analysis environments that the chosen path uses, reusing any that
  already exist;
- remembers where our workflows are, so nobody sets
  `ZMART_INTERFACE_WORKFLOWS` by hand;
- puts the start icons on the desktop;
- ends with one sentence saying what was installed and how to start it.

When something goes wrong, it stops with a sentence that says what to do
("conda was not found: install Miniforge from ..., then run this again"),
not a list of error messages.

**Updating** is running `setup_zmart.py` again, after updating the copy of
ZMART Microscopy. Nothing changes on a computer until then, so a microscope
only changes when someone decides it should.

## The start button

One small file per system, in the top folder of ZMART Microscopy:

| System | File | How it is started |
|---|---|---|
| Windows | `Start ZMART.bat` | double-click, or the desktop icon |
| macOS | `Start ZMART.command` | double-click |
| Linux | `start-zmart.sh` | from a terminal, or the desktop icon |

Each one:

1. finds the `zmart` environment;
2. points the interface at `workflows/non-coders/interface`;
3. opens the operator window.

If the environment is not there, it says "ZMART is not installed on this
computer yet: run setup_zmart.py first" and waits for a key, so the message
does not flash past. For coders, **Start ZMART notebooks** does the same and
opens Jupyter in `workflows/coders/notebooks/`.

## Where the versions are written down

A small file, `releases.toml`, names the version of each block this copy of
ZMART Microscopy installs, for example:

```toml
zmart-controller = "v0.4.0rc8"
zmart-viewer = "v0.5.0rc10"
zmart-analysis = "v0.6.0rc8"
zmart-interface = "v0.2.0rc1"
zmart-drivers = "v0.7.0b9"
```

It is changed at a release, after the checks in `tests/` and the walk have
passed with exactly these versions. The drivers plan later lets one
microscope pin its own driver version, in its own folder.

## Steps

1. Write `releases.toml` with the versions of the next release.
2. Write `setup_zmart.py`: the two questions, the environment, the blocks,
   the driver, the analysis environments, the remembered workflows folder,
   and the desktop icons (Windows first).
3. Write the three start files.
4. Write a short "Install ZMART" page in the README: the three commands a new
   person needs, and nothing else.
5. Check it on a Windows computer that has never had ZMART on it, once as a
   non-coder and once as a coder, and on the ZMB workstations with their
   approved-folder rules (AppLocker).

## Questions to decide

1. Windows first, with the macOS and Linux start files simple at the start:
   is that right?
2. Should the installer wait for the drivers plan, or start now with the mock
   microscope and the Leica only, as written here?
3. Does the installer go on the ZMB workstations into
   `C:\ProgramData\MinicondaZMB`, as the interface's install guide asks, and
   should it choose that folder by itself there?
