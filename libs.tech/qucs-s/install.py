#!/usr/bin/env python3

########################################################################
#
# Copyright 2024-2026 IHP PDK Authors
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

"""Install the SG13CMOS5L Qucs-S support files into the user's Qucs-S workspace.

Three things are set up:

  * user_lib      symlinked into $HOME/[.qucs|QucsWorkspace]/user_lib
  * examples      copied into $HOME/[.qucs|QucsWorkspace]/<project>
  * symbols       registered in the Qucs-S settings, so the PDK devices show up
                  in the component palette

Requires the PDK_ROOT environment variable, or falls back to deriving it from
this script's own location.
"""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

PDK_DEFAULT = "ihp-sg13cmos5l"
EXAMPLES_PROJECT = "IHP-Open-PDK-SG13CMOS5L-Examples_prj"
WORKSPACE_TOKEN = "<qucs_workspace>"

# Qucs-S keeps its settings here; the PDK component search path lives in the
# [XmlCompPaths] section as an indexed QSettings list.
QUCS_CONF = Path.home() / ".config" / "qucs" / "qucs_s.conf"
XML_COMP_SECTION = "[XmlCompPaths]"
PATHS_SECTION = "[Paths]"

log = logging.getLogger("install")


def resolve_pdk_root() -> Path:
    """PDK_ROOT if set, else three levels up from this script."""
    env = os.environ.get("PDK_ROOT")
    if env:
        return Path(env)
    # <root>/<pdk>/libs.tech/qucs-s/install.py -> <root>
    derived = Path(__file__).resolve().parents[3]
    log.warning("PDK_ROOT is not set, assuming %s", derived)
    return derived


def is_program_installed(program: str) -> bool:
    return shutil.which(program) is not None


def symlink_dir_contents(source: Path, dest: Path) -> None:
    """Symlink every file in source into dest, leaving existing names alone."""
    dest.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source.iterdir()):
        if not entry.is_file():
            continue
        target = dest / entry.name
        if target.exists() or target.is_symlink():
            print(f"  skipping existing: {target}")
            continue
        target.symlink_to(entry)
        print(f"  linked: {target} -> {entry}")


def copy_examples(source: Path, dest: Path, workspace: str) -> None:
    """Copy the example schematics, substituting the workspace placeholder.

    The upstream SG13G2 script shelled out to `sed -i` for this, which only
    worked because the workspace strings happen to begin and end with the
    slashes sed then used as its delimiters.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source.iterdir()):
        if not entry.is_file():
            continue
        target = dest / entry.name
        if entry.suffix == ".sch":
            target.write_text(entry.read_text().replace(WORKSPACE_TOKEN, workspace))
        else:
            shutil.copy(entry, target)
        print(f"  copied: {target}")


def link_spiceinit(pdk_spiceinit: Path) -> None:
    """Point $HOME/.spiceinit at this PDK's version.

    Only one can win, and the SG13G2 and SG13CMOS5L versions set different model
    search paths, so say so loudly instead of skipping in silence.
    """
    home_spiceinit = Path.home() / ".spiceinit"
    if home_spiceinit.is_symlink() and home_spiceinit.resolve() == pdk_spiceinit.resolve():
        print(f"  {home_spiceinit} already points here")
        return
    if home_spiceinit.exists() or home_spiceinit.is_symlink():
        current = os.readlink(home_spiceinit) if home_spiceinit.is_symlink() else "a regular file"
        log.warning(
            "%s already exists (%s) and was left alone. It sets the ngspice model "
            "search path, so simulations may resolve against a different PDK. "
            "Point it at %s if that is not what you want.",
            home_spiceinit, current, pdk_spiceinit,
        )
        return
    home_spiceinit.symlink_to(pdk_spiceinit)
    print(f"  linked: {home_spiceinit} -> {pdk_spiceinit}")


def register_path(directory: Path, section: str, conf: Path = QUCS_CONF) -> None:
    """Add a directory to one of the Qucs-S QSettings path lists, idempotently.

    Two lists matter for a PDK:

      [XmlCompPaths]  where the device symbols (symbols/*.xml) are found, which
                      is what puts the PDK devices in the component palette
      [Paths]         the subcircuit search path, which is what lets the
                      netlister expand the user_lib components

    Without the second one the schematics open but netlist to nothing, so both
    are registered here rather than left as a manual GUI step.

    Edited as text rather than through configparser: the file also holds
    @ByteArray(...) values whose escaping must survive untouched.
    """
    wanted = str(directory)

    if not conf.exists():
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(f"{section}\n1\\path={wanted}\nsize=1\n")
        print(f"  created {conf} with {section} -> {wanted}")
        return

    lines = conf.read_text().splitlines()
    try:
        start = lines.index(section)
    except ValueError:
        lines += ["", section, f"1\\path={wanted}", "size=1"]
        conf.write_text("\n".join(lines) + "\n")
        print(f"  added {section} to {conf}")
        return

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("["):
            end = i
            break

    paths, size_at = {}, None
    for i in range(start + 1, end):
        key, _, value = lines[i].partition("=")
        key = key.strip()
        if key.endswith("\\path"):
            paths[int(key.split("\\", 1)[0])] = value.strip()
        elif key == "size":
            size_at = i

    if wanted in paths.values():
        print(f"  {section}: {wanted} already registered")
        return

    index = max(paths, default=0) + 1
    # size_at is always inside the section, so inserting at `end` does not move it
    lines.insert(end, f"{index}\\path={wanted}")
    if size_at is not None:
        lines[size_at] = f"size={index}"
    else:
        lines.insert(end + 1, f"size={index}")
    conf.write_text("\n".join(lines) + "\n")
    print(f"  {section}: registered {wanted} as entry {index}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install SG13CMOS5L Qucs-S PDK files")
    parser.add_argument("--no-qucs-check", action="store_true",
                        help="Skip the check that the qucs-s binary exists")
    parser.add_argument("--no-symbol-register", action="store_true",
                        help="Do not touch the Qucs-S settings file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--no-qucs-workspace", action="store_true",
                       help="Only set up .qucs, skip QucsWorkspace")
    group.add_argument("--no-qucs-dir", action="store_true",
                       help="Only set up QucsWorkspace, skip .qucs")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(format="%(levelname)s: %(message)s")
    args = parse_args()

    if not args.no_qucs_check and not is_program_installed("qucs-s"):
        log.error("qucs-s is not installed")
        return 1

    pdk = os.environ.get("PDK", PDK_DEFAULT)
    pdk_root = resolve_pdk_root()
    pdk_dir = pdk_root / pdk
    qucs_dir = pdk_dir / "libs.tech" / "qucs-s"

    if not qucs_dir.is_dir():
        log.error("%s does not exist. Check PDK_ROOT and PDK.", qucs_dir)
        return 1
    print(f"Installing from {qucs_dir}\n")

    workspaces = ["QucsWorkspace"] if args.no_qucs_dir else \
                 [".qucs"] if args.no_qucs_workspace else [".qucs", "QucsWorkspace"]

    user_libs = []
    for workspace in workspaces:
        home_ws = Path.home() / workspace
        print(f"Preparing {home_ws}")
        symlink_dir_contents(qucs_dir / "user_lib", home_ws / "user_lib")
        user_libs.append(home_ws / "user_lib")
        copy_examples(qucs_dir / "examples", home_ws / EXAMPLES_PROJECT, workspace)
        pdk_link = home_ws / pdk
        if not (pdk_link.exists() or pdk_link.is_symlink()):
            pdk_link.symlink_to(pdk_dir)
            print(f"  linked: {pdk_link} -> {pdk_dir}")
        print()

    print("Configuring ngspice")
    link_spiceinit(pdk_dir / "libs.tech" / "ngspice" / ".spiceinit")
    print()

    if args.no_symbol_register:
        print("Skipping Qucs-S settings registration (--no-symbol-register)")
        print("  the device palette and the example schematics will not resolve until")
        print("  you add these by hand under File -> Application Settings:")
        print(f"    components: {qucs_dir / 'symbols'}")
        for path in user_libs:
            print(f"    locations:  {path}")
    else:
        print("Registering the PDK in the Qucs-S settings")
        register_path(qucs_dir / "symbols", XML_COMP_SECTION)
        for path in user_libs:
            register_path(path, PATHS_SECTION)
        print("  note: close Qucs-S before running this, it rewrites its settings on exit")
    print()

    print("Done. The OSDI models these devices need are built in the sibling ihp-sg13g2:")
    print(f"  cd {pdk_root}/ihp-sg13g2/libs.tech/verilog-a && ./openvaf-compile-va.sh\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
