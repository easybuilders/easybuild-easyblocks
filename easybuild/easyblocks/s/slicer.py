#! /usr/bin/env python
##
# Copyright 2020-2026 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##

"""
EasyBuild support for building and installing 3D Slicer with Biomedisa.
@author: Pavel Tomanek (Inuits/UGent) with help of ChatGPT6
"""

import os
import re
import shlex
import stat

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_file, expand_glob_paths, extract_file
from easybuild.tools.filetools import find_glob_pattern, mkdir, open_file, remove_file, resolve_path
from easybuild.tools.filetools import symlink, which, write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.utilities import nub


class EB_Slicer(CMakeMake):
    """Support for building and installing 3D Slicer with the Biomedisa extension."""

    BIOMEDISA_MODULES = (
        'SegmentEditorBiomedisa',
        'SegmentEditorBiomedisaPrediction',
        'SegmentEditorBiomedisaTraining',
    )
    BIOMEDISA_EFFECTS = (
        'Biomedisa Smart Interpolation',
        'Biomedisa Prediction',
        'Biomedisa Training',
    )

    def _cpack_install(self):
        """Generate Slicer's CPack TGZ package and extract it."""
        if not self.separate_build_dir:
            raise EasyBuildError("Slicer requires a separate CMake build directory")

        slicer_build_dir = os.path.join(self.separate_build_dir, 'Slicer-build')
        cpack_dir = os.path.join(self.separate_build_dir, 'cpack-install')
        mkdir(cpack_dir, parents=True)

        cmd = "cpack --config CPackConfig.cmake -G TGZ -B %s" % shlex.quote(cpack_dir)
        run_shell_cmd(cmd, work_dir=slicer_build_dir)
        cpack_archive = find_glob_pattern(os.path.join(cpack_dir, 'Slicer-%s-*.tar.gz' % self.version))

        # A plain CMake install does not install the complete SuperBuild runtime.
        extract_file(
            cpack_archive,
            self.installdir,
            extra_options='--strip-components=1',
            change_into_dir=False,
        )

    def _install_tbb_libraries(self):
        """Copy the internally built TBB runtime, preserving its symlink layout."""
        if self.dry_run:
            self.log.info("Skipping TBB file discovery in extended dry run mode")
            return

        tbb_libdir = os.path.join(self.separate_build_dir, 'tbb-install', 'lib')
        target_libdir = os.path.join(self.installdir, 'lib')
        mkdir(target_libdir, parents=True)
        tbb_libs = expand_glob_paths([os.path.join(tbb_libdir, 'libtbb*.so*')])

        # Copy regular files first. copy_file follows valid symlinks, so create
        # symlinks explicitly rather than replacing them with duplicate binaries.
        for src in sorted(tbb_libs, key=os.path.islink):
            dst = os.path.join(target_libdir, os.path.basename(src))
            if os.path.islink(src):
                # Allow rerunning installation, including over a dangling link.
                if os.path.lexists(dst):
                    remove_file(dst)
                symlink(os.readlink(src), dst, use_abspath_source=False)
            else:
                # Do not copy through a pre-existing destination symlink.
                if os.path.islink(dst):
                    remove_file(dst)
                copy_file(src, dst)

    def _fix_superbuild_rpaths(self):
        """Replace known SuperBuild staging paths with per-file installed paths."""
        if self.dry_run:
            self.log.info("Skipping installed ELF inspection in extended dry run mode")
            return

        slicer_libdir = find_glob_pattern(os.path.join(self.installdir, 'lib', 'Slicer-*'))
        stale_paths = {
            resolve_path(os.path.join(self.separate_build_dir, 'DCMTK-build', 'lib')),
            resolve_path(os.path.join(self.separate_build_dir, 'OpenJPEG-install', 'lib')),
        }
        build_roots = {resolve_path(self.builddir), resolve_path(self.separate_build_dir)}
        rpath_regex = re.compile(r'\((RPATH|RUNPATH)\)\s+[^\n]*?\[([^\]]*)\]')
        inspected = 0
        patched = 0

        for dirpath, _dirnames, filenames in os.walk(self.installdir):
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                if os.path.islink(path) or not os.path.isfile(path):
                    continue

                # Avoid starting an external process for every Python/data file.
                try:
                    with open_file(path, 'rb') as handle:
                        is_elf = handle.read(4) == b'\x7fELF'
                except OSError as err:
                    raise EasyBuildError("Failed to inspect %s: %s", path, err)
                if not is_elf:
                    continue

                inspected += 1
                result = run_shell_cmd(
                    'LC_ALL=C readelf -d %s' % shlex.quote(path),
                    hidden=True,
                    output_file=False,
                    stream_output=False,
                    log_output_on_success=False,
                )
                matches = rpath_regex.findall(result.output)
                if not matches:
                    # Valid static executables/objects may have no dynamic RPATH.
                    continue
                if len(matches) != 1:
                    raise EasyBuildError("Expected a single RPATH/RUNPATH tag in %s, found %s", path, matches)

                tag, rpath = matches[0]
                entries = rpath.split(':')
                # Filter both known staging directories together. A single ELF
                # can contain both; an if/elif implementation misses one of them.
                kept_entries = [entry for entry in entries if not (
                    os.path.isabs(entry) and resolve_path(entry) in stale_paths
                )]

                # Fail rather than silently discard an unknown build dependency.
                for entry in kept_entries:
                    if os.path.isabs(entry):
                        resolved = resolve_path(entry)
                        if any(resolved == root or resolved.startswith(root + os.sep) for root in build_roots):
                            raise EasyBuildError("Unrecognised build-tree RPATH in %s: %s", path, entry)

                if kept_entries == entries:
                    continue

                # $ORIGIN is relative to each ELF, not to the installation root.
                # bin/* needs ../lib/Slicer-X.Y; lib/Slicer-X.Y/* needs $ORIGIN.
                relative_libdir = os.path.relpath(slicer_libdir, dirpath)
                installed_rpath = '$ORIGIN'
                if relative_libdir != '.':
                    installed_rpath += '/' + relative_libdir
                new_rpath = ':'.join(nub([entry for entry in kept_entries if entry] + [installed_rpath]))

                # Preserve DT_RPATH when present, but do not convert an existing
                # DT_RUNPATH to DT_RPATH and change its dynamic-loader semantics.
                force_rpath = '--force-rpath ' if tag == 'RPATH' else ''
                cmd = 'patchelf %s--set-rpath %s %s' % (
                    force_rpath, shlex.quote(new_rpath), shlex.quote(path),
                )
                run_shell_cmd(
                    cmd,
                    hidden=True,
                    output_file=False,
                    stream_output=False,
                    log_output_on_success=False,
                )
                patched += 1

        self.log.info("Inspected %d installed ELF files; updated RPATH in %d", inspected, patched)

    def _install_launcher_wrapper(self):
        """Install a module-aware wrapper that automatically loads Biomedisa."""
        wrapper = """#!/bin/bash
set -euo pipefail

: "${EBROOTBIOMEDISA:?Biomedisa dependency is not loaded; load the Slicer module.}"
SLICER_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
BIOMEDISA_EXT="$EBROOTBIOMEDISA/biomedisa_slicer_extension/biomedisa_extension"

module_paths=()
for module in %s; do
    module_path="$BIOMEDISA_EXT/$module"
    if [ ! -f "$module_path/$module.py" ]; then
        echo "Missing Biomedisa Slicer module: $module_path/$module.py" >&2
        exit 1
    fi
    module_paths+=("$module_path")
done

exec "$SLICER_ROOT/Slicer" --additional-module-paths "${module_paths[@]}" "$@"
""" % ' '.join(self.BIOMEDISA_MODULES)

        wrapper_path = os.path.join(self.installdir, 'bin', 'Slicer')
        mkdir(os.path.dirname(wrapper_path), parents=True)
        write_file(wrapper_path, wrapper)
        adjust_permissions(wrapper_path, stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH, add=True)

    def install_step(self):
        """Install the CPack runtime, complete it, and add the Biomedisa wrapper."""
        self._cpack_install()
        self._install_tbb_libraries()
        self._fix_superbuild_rpaths()
        self._install_launcher_wrapper()

    def sanity_check_step(self):
        """Check the launchers, Python stack, and registered Biomedisa effects."""
        custom_paths = {
            'files': [
                'Slicer',
                'bin/Slicer',
                'bin/SlicerApp-real',
                'bin/SlicerLauncherSettings.ini',
                'lib/libtbb.so.12',
            ],
            'dirs': ['lib/Slicer-%s' % '.'.join(self.version.split('.')[:2])],
        }

        # Module discovery can succeed while its Segment Editor effect fails to
        # register, so verify the effect registry as well as the module names.
        checks = [
            'import slicer, vtk, qt, ctk',
            'import qSlicerSegmentationsEditorEffectsPythonQt as effects',
            'required_modules = set(%r)' % (self.BIOMEDISA_MODULES,),
            'modules = set(slicer.app.moduleManager().factoryManager().instantiatedModuleNames())',
            "assert required_modules <= modules, 'Missing Biomedisa modules: ' + str(required_modules - modules)",
            'required_effects = set(%r)' % (self.BIOMEDISA_EFFECTS,),
            'registered = {effect.name for effect in '
            'effects.qSlicerSegmentEditorEffectFactory.instance().registeredEffects()}',
            "assert required_effects <= registered, 'Missing Biomedisa effects: ' + str(required_effects - registered)",
            "print('Slicer Python and Biomedisa effect registration passed')",
        ]
        launcher = shlex.quote(os.path.join(self.installdir, 'Slicer'))
        wrapper = shlex.quote(os.path.join(self.installdir, 'bin', 'Slicer'))
        # --testing makes Python exceptions produce a non-zero Slicer exit code
        # and disables user settings/slicerrc. No GPU computation is required.
        headless = 'QT_QPA_PLATFORM=offscreen QT_QPA_OFFSCREEN_NO_GLX=1 '
        custom_commands = [
            '%s --launcher-help' % launcher,
            'test "$(command -v Slicer)" -ef %s' % wrapper,
            headless + 'Slicer --testing --no-splash --no-main-window '
            '--python-code %s --exit-after-startup' % shlex.quote('; '.join(checks)),
        ]
        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
