#!/usr/bin/env python3

########################################################################
#
# Copyright 2026 IHP PDK Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
########################################################################

"""Check that every Qucs-S component resolves to a real ngspice device.

The Qucs-S symbols and user libraries name their devices as bare strings, which
ngspice only resolves at simulation time through the `sourcepath` set in
.spiceinit. Nothing fails at edit time, so a component naming a device this PDK
does not have looks fine until someone tries to simulate it.

This walks symbols/*.xml and user_lib/*.lib, collects every device name they
reference, and checks each one against the .subckt and .model definitions under
libs.tech/ngspice/models.

Needs no simulator, so it is cheap enough to run in CI.

Usage:
    ./check_device_coverage.py [--pdk-root DIR] [--pdk NAME]
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Bare SPICE primitives and directives, not PDK devices.
PRIMITIVES = {"D", "Q", "R", "C", "L", "M", "V", "I", "SUB"}

MODEL_PARAM = re.compile(r'<Parameter\s+name="model"[^>]*default_value="([^"]*)"')
SPICE_MODEL = re.compile(r'<SpiceModel\s+value="([^"]*)"')
SPICE_BLOCK = re.compile(r"<Spice>(.*?)</Spice>", re.S)
DEFINITION = re.compile(r"^\s*\.(subckt|model)\s+(\S+)", re.I | re.M)
SOURCEPATH = re.compile(r"^\s*setcs\s+sourcepath\s*=\s*\((.*?)\)", re.I | re.M)


def sourcepath_dirs(pdk_dir: Path) -> list[Path]:
    """The directories ngspice will search, as declared by the PDK's .spiceinit.

    Standard cells live under libs.ref/<pdk>_stdcell/spice rather than
    libs.tech/ngspice/models, so reading the real sourcepath is what keeps this
    check from flagging them.
    """
    spiceinit = pdk_dir / "libs.tech" / "ngspice" / ".spiceinit"
    dirs, seen = [], set()
    if spiceinit.is_file():
        for group in SOURCEPATH.findall(spiceinit.read_text(errors="replace")):
            for token in group.split():
                if not token.startswith("$PDK_ROOT"):
                    continue
                # $PDK_ROOT/$PDK/... and $PDK_ROOT/<literal-pdk>/... both appear
                rest = token.split("/", 2)[2] if token.count("/") >= 2 else ""
                path = pdk_dir / rest
                if rest and path.is_dir() and path not in seen:
                    seen.add(path)
                    dirs.append(path)
    models = pdk_dir / "libs.tech" / "ngspice" / "models"
    if models.is_dir() and models not in seen:
        dirs.insert(0, models)
    return dirs


def defined_devices(dirs: list[Path]) -> set[str]:
    """Every .subckt and .model name reachable on the sourcepath."""
    names = set()
    for directory in dirs:
        for pattern in ("*.lib", "*.spice", "*.cir"):
            for lib in sorted(directory.glob(pattern)):
                text = lib.read_text(errors="replace")
                names.update(m.group(2).lower() for m in DEFINITION.finditer(text))
    return names


def devices_from_symbols(symbols_dir: Path) -> dict[str, str]:
    """Map symbol file -> device it references.

    The `model` parameter's default is authoritative when present; components
    whose SpiceModel is a bare primitive (D, Q, ...) carry the real device name
    only there.
    """
    found = {}
    for xml in sorted(symbols_dir.glob("*.xml")):
        text = xml.read_text(errors="replace")
        match = MODEL_PARAM.search(text) or SPICE_MODEL.search(text)
        if match and match.group(1):
            found[xml.name] = match.group(1)
    return found


def devices_from_user_lib(user_lib_dir: Path) -> dict[str, str]:
    """Map "<lib>:<subckt>" -> the PDK device its X-line instantiates.

    Each <Spice> block wraps one PDK device in a subckt, e.g.
        .SUBCKT IHP_..._ntap1 gnd P1 P2 w=... l=...
        X1 P1 P2 ntap1 w={w} l={l}
    so the device is the last token before the first key=value parameter.
    """
    found = {}
    for lib in sorted(user_lib_dir.glob("*.lib")):
        for block in SPICE_BLOCK.findall(lib.read_text(errors="replace")):
            subckt = None
            for raw in block.splitlines():
                line = raw.strip()
                if line.lower().startswith(".subckt"):
                    subckt = line.split()[1]
                elif line.upper().startswith("X") and subckt:
                    tokens = line.split()[1:]
                    named = [i for i, t in enumerate(tokens) if "=" in t]
                    device = tokens[named[0] - 1] if named else tokens[-1]
                    found[f"{lib.stem}:{subckt}"] = device
    return found


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT"),
                        help="IHP-Open-PDK checkout (default: $PDK_ROOT)")
    parser.add_argument("--pdk", default=None,
                        help="PDK directory name (default: inferred from this script's path)")
    parser.add_argument("--qucs-dir", default=here, type=Path,
                        help="qucs-s directory to check (default: this one)")
    args = parser.parse_args()

    if not args.pdk_root:
        print("error: PDK_ROOT is not set and --pdk-root was not given", file=sys.stderr)
        return 2
    pdk = args.pdk or here.parents[1].name
    pdk_dir = Path(args.pdk_root) / pdk
    if not pdk_dir.is_dir():
        print(f"error: {pdk_dir} does not exist", file=sys.stderr)
        return 2

    dirs = sourcepath_dirs(pdk_dir)
    defined = defined_devices(dirs)
    print(f"Checking {args.qucs_dir}")
    print(f"against  {len(defined)} devices on the {pdk} ngspice sourcepath:")
    for directory in dirs:
        print(f"           {directory}")
    print()

    referenced = {}
    referenced.update(devices_from_symbols(args.qucs_dir / "symbols"))
    referenced.update(devices_from_user_lib(args.qucs_dir / "user_lib"))

    missing = {
        where: device
        for where, device in sorted(referenced.items())
        if device not in PRIMITIVES and device.lower() not in defined
    }

    print(f"{len(referenced)} component references checked")
    if not missing:
        print("all resolve to a device in this PDK")
        return 0

    print(f"\n{len(missing)} reference(s) do not resolve:")
    for where, device in missing.items():
        print(f"  {where}: {device}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
