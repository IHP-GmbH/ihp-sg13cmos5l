# Using Qucs-S with SG13CMOS5L

[Qucs-S](https://ra3xdh.github.io) is a schematic capture front end that drives
Ngspice, Xyce and friends. This directory provides the SG13CMOS5L device symbols,
component libraries and example schematics, ported from the equivalent
`ihp-sg13g2` directory and pruned to the devices this PDK actually has.

## Install

```bash
export PDK_ROOT=/path/to/IHP-Open-PDK
export PDK=ihp-sg13cmos5l
./install.py
```

`PDK_ROOT` must point at the `IHP-Open-PDK` checkout that contains
`ihp-sg13cmos5l`, which is not necessarily the one you use for SG13G2 work. If it
is unset the script falls back to deriving it from its own location.

The installer:

- symlinks `user_lib/` into `$HOME/.qucs/user_lib` and `$HOME/QucsWorkspace/user_lib`
- copies `examples/` into `$HOME/[.qucs|QucsWorkspace]/IHP-Open-PDK-SG13CMOS5L-Examples_prj`
- points `$HOME/.spiceinit` at this PDK's Ngspice settings
- registers `symbols/` and the installed `user_lib` directories in
  `$HOME/.config/qucs/qucs_s.conf`

That last step is what makes the devices appear in the component palette and lets
the netlister expand the library components. **Close Qucs-S before running the
installer**, since it rewrites its settings file on exit. Use
`--no-symbol-register` to skip it and configure the paths by hand instead; the
script prints the exact values to enter.

The devices need OSDI compact models, which are a build product of the sibling
SG13G2 rather than a tracked file:

```bash
cd $PDK_ROOT/ihp-sg13g2/libs.tech/verilog-a && ./openvaf-compile-va.sh
```

## Using both PDKs at once

Both PDKs install into the same `$HOME/[.qucs|QucsWorkspace]/user_lib` and skip
names that are already there, so identically named libraries would mean whichever
PDK was installed first silently wins. The libraries here are therefore named
`IHP_SG13CMOS5L_*` rather than SG13G2's `IHP_PDK_*`, and the symbols carry
`library="IHP SG13CMOS5L devices"`, so the two coexist and the palette says which
is which.

This matters more than it looks: the two PDKs use *identical* subckt names
(`sg13_lv_nmos`, `rsil`, `nmoscl_2`, ...), so a schematic built from the wrong
library still netlists and still simulates. Which PDK you actually simulated is
decided by `$PDK` and the `sourcepath` in `.spiceinit`, not by anything visible
in the schematic.

## Contents

`symbols/` holds 25 device definitions (`.xml`) plus the 13 geometry files
(`.sym`) they reference:

- MOSFETs: `nmos`, `pmos`, `nmosHV`, `pmosHV` and their RF variants
- resistors and taps: `rsil`, `rhigh`, `rppd`, `ntap1`, `ptap1`
- diodes: `dantenna`, `dpantenna`
- ESD: `diodevdd_2kv/4kv`, `diodevss_2kv/4kv`, `nmoscl_2`, `nmoscl_4`
- other: `bondpad`, `pnpMPA`, `svaricap`, `sub`

`user_lib/` holds the same devices as legacy Qucs library components, which is
what the example schematics instantiate.

Not present, because the devices are not in this PDK: `cap_cmim`, `cap_rfcmim`,
the `npn13G2*` HBTs, `schottky_nbl1`, `isolbox`, the moscaps and inductors. The
MoM capacitor `cap_cmomi` is a different model here (Metal1..Metal4 rather than
Metal1..Metal5) and arrives together with the device itself.

Standard-cell symbols are not provided yet.

## Checking

`check_device_coverage.py` verifies that every component in `symbols/` and
`user_lib/` names a device that actually exists on this PDK's Ngspice
`sourcepath`. Qucs-S resolves those names only at simulation time, so a stale
component looks fine in the editor and fails much later.

```bash
./check_device_coverage.py
```

It needs no simulator. Run it against SG13G2 to see what it catches:

```bash
./check_device_coverage.py --pdk ihp-sg13g2 --qucs-dir $PDK_ROOT/ihp-sg13g2/libs.tech/qucs-s
```

To check the examples end to end, netlist and simulate them headlessly:

```bash
qucs-s -n -i dc_lv_nmos.sch -o dc_lv_nmos.cir --ngspice
ngspice -b dc_lv_nmos.cir
```

Verified with Qucs-S `s25.2.0` and `ngspice-46`: all eight examples netlist and
simulate without errors.
