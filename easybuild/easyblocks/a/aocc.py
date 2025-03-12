##
# Copyright 2020-2025 Forschungszentrum Juelich GmbH
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
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
Support for installing AOCC, implemented as an easyblock.

@author: Sebastian Achilles (Forschungszentrum Juelich GmbH)
"""

import glob
import os
import re
import stat
import tempfile

from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, move_file, write_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext, get_cpu_architecture

# Wrapper script definition
WRAPPER_TEMPLATE = """#!/bin/bash

# Patch argv[0] to the actual compiler so that the correct driver is used internally
(exec -a "$0" {compiler_name} --gcc-toolchain=$EBROOTGCCCORE "$@")
"""

AOCC_MINIMAL_CPP_EXAMPLE = """
#include <iostream>

int main(){ std::cout << "It works!" << std::endl; }
"""

AOCC_MINIMAL_FORTRAN_EXAMPLE = """
program main
end program main
"""


class EB_AOCC(PackedBinary):
    """
    Support for installing the AOCC compilers
    """

    @staticmethod
    def extra_options():
        extra_vars = {
            'clangversion': [None, "Clang Version on which AOCC is based on (10.0.0 or 11.0.0 or ...)", CUSTOM],
        }
        return PackedBinary.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Easyblock constructor, define custom class variables specific to AOCC."""
        super(EB_AOCC, self).__init__(*args, **kwargs)

        self.clangversion = self.cfg['clangversion']
        # AOCC is based on Clang. Try to guess the clangversion from the AOCC version
        # if clangversion is not specified in the easyconfig
        if self.clangversion is None:
            self.clangversion = self._aocc_guess_clang_version()

        self._gcc_prefix = None

        # Bypass the .mod file check for GCCcore installs
        self.cfg['skip_mod_files_sanity_check'] = True

    def _aocc_guess_clang_version(self):
        map_aocc_to_clang_ver = {
            '2.3.0': '11.0.0',
            '3.0.0': '12.0.0',
            '3.1.0': '12.0.0',
            '3.2.0': '13.0.0',
            '4.0.0': '14.0.6',
            '4.1.0': '16.0.3',
            '4.2.0': '16.0.3',
            '5.0.0': '17.0.6',
        }

        if self.version in map_aocc_to_clang_ver:
            return map_aocc_to_clang_ver[self.version]
        else:
            error_lines = [
                "AOCC is based on Clang. Guessing Clang version in easyblock failed.",
                "You should either:",
                "- specify `clangversion` in the easyconfig;",
                "- extend `map_aocc_to_clang_ver` in the easyblock;",
            ]
            raise EasyBuildError('\n'.join(error_lines))

    def _create_compiler_wrappers(self, compilers_to_wrap):
        if not compilers_to_wrap:
            return

        orig_compiler_tmpl = f"{os.path.join(self.installdir, 'bin')}/{{}}.orig"

        def create_wrapper(wrapper_comp):
            """Create for a particular compiler, with a particular name"""
            wrapper_f = os.path.join(self.installdir, 'bin', wrapper_comp)
            compiler_name = orig_compiler_tmpl.format(wrapper_comp)
            write_file(wrapper_f, WRAPPER_TEMPLATE.format(compiler_name=compiler_name))

            perms = stat.S_IXUSR | stat.S_IRUSR | stat.S_IXGRP | stat.S_IRGRP | stat.S_IXOTH | stat.S_IROTH
            adjust_permissions(wrapper_f, perms)

        # Rename original compilers and prepare wrappers to pick up GCCcore as GCC toolchain for the compilers
        for comp in compilers_to_wrap:
            actual_compiler = os.path.join(self.installdir, 'bin', comp)
            if os.path.isfile(actual_compiler):
                move_file(actual_compiler, orig_compiler_tmpl.format(comp))
            else:
                raise EasyBuildError(f"Cannot make wrapper for '{actual_compiler}', file does not exist")

            if not os.path.exists(actual_compiler):
                create_wrapper(comp)
                self.log.info(f"Wrapper for {comp} successfully created")
            else:
                raise EasyBuildError(f"Cannot make wrapper for '{actual_compiler}', original compiler was not renamed!")

    def _create_compiler_config_files(self, compilers_to_add_config_file):
        """For each of the compiler suites, add a .cfg file which points to the correct GCCcore as the GCC toolchain."""
        if not compilers_to_add_config_file:
            return

        bin_dir = os.path.join(self.installdir, 'bin')
        prefix_str = '--gcc-install-dir=%s' % self.gcc_prefix
        for comp in compilers_to_add_config_file:
            with open(os.path.join(bin_dir, '%s.cfg' % comp), 'w') as f:
                f.write(prefix_str)

    def _sanity_check_gcc_prefix(self):
        """Check if the GCC prefix is correct."""
        compilers_to_check = [
            'clang',
            'clang++',
            'clang-%s' % LooseVersion(self.clangversion).version[0],
            'clang-cpp',
            'flang',
        ]

        rgx = re.compile('Selected GCC installation: (.*)')
        for comp in compilers_to_check:
            cmd = "%s -v" % os.path.join(self.installdir, 'bin', comp)
            res = run_shell_cmd(cmd, fail_on_error=False)
            mch = rgx.search(res.output)
            if mch is None:
                self.log.debug(res.output)
                raise EasyBuildError("Failed to extract GCC installation path from output of `%s`", cmd)
            gcc_prefix = mch.group(1)
            if gcc_prefix != self.gcc_prefix:
                raise EasyBuildError(
                    "GCC installation path `%s` does not match expected path `%s`", gcc_prefix, self.gcc_prefix
                    )

    @property
    def gcc_prefix(self):
        """Set the GCC prefix for the build."""
        if not self._gcc_prefix:
            arch = get_cpu_architecture()
            gcc_root = get_software_root('GCCcore')
            gcc_version = get_software_version('GCCcore')
            # If that doesn't work, try with GCC
            if gcc_root is None:
                gcc_root = get_software_root('GCC')
                gcc_version = get_software_version('GCC')
            # If that doesn't work either, print error and exit
            if gcc_root is None:
                raise EasyBuildError("Can't find GCC or GCCcore to use")

            pattern = os.path.join(gcc_root, 'lib', 'gcc', '%s-*' % arch, '%s' % gcc_version)
            matches = glob.glob(pattern)
            if not matches:
                raise EasyBuildError("Can't find GCC version %s for architecture %s in %s", gcc_version, arch, pattern)
            self._gcc_prefix = os.path.abspath(matches[0])
            self.log.debug("Using %s as the gcc install location", self._gcc_prefix)

        return self._gcc_prefix

    def install_step(self):
        # EULA for AOCC must be accepted via --accept-eula-for EasyBuild configuration option,
        # or via 'accept_eula = True' in easyconfig file
        self.check_accepted_eula(more_info='http://developer.amd.com/wordpress/media/files/AOCC_EULA.pdf')

        super(EB_AOCC, self).install_step()

    def post_processing_step(self):
        """
        For AOCC <5.0.0:
        Create wrappers for the compilers to make sure compilers picks up GCCcore as GCC toolchain.
        For AOCC >= 5.0.0:
        Create [compiler-name].cfg files to point the compiler to the correct GCCcore as GCC toolchain.
        For compilers not supporting this option, wrap the compilers using the old method.
        """
        compilers_to_wrap = []
        compilers_to_add_config_files = []

        if LooseVersion(self.version) < LooseVersion("5.0.0"):
            compilers_to_wrap += [
                f'clang-{LooseVersion(self.clangversion).version[0]}',
            ]
            if not self.cfg['keepsymlinks']:
                compilers_to_wrap += [
                    'clang',
                    'clang++',
                    'clang-cpp',
                    'flang',
                ]
        else:
            compilers_to_add_config_files += [
                'clang',
                'clang++',
                'clang-cpp'
            ]
            compilers_to_wrap += [
                'flang'
            ]

        self._create_compiler_config_files(compilers_to_add_config_files)
        self._create_compiler_wrappers(compilers_to_wrap)
        super(EB_AOCC, self).post_processing_step()

    def sanity_check_step(self):
        """Custom sanity check for AOCC, based on sanity check for Clang."""

        # Clang v16+ only use the major version number for the resource dir
        resdir_version = self.clangversion
        if LooseVersion(self.clangversion) >= LooseVersion('16.0.0'):
            resdir_version = LooseVersion(self.clangversion).version[0]

        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [
                'bin/clang', 'bin/clang++', 'bin/flang', 'bin/lld', 'bin/llvm-ar', 'bin/llvm-as', 'bin/llvm-config',
                'bin/llvm-link', 'bin/llvm-nm', 'bin/llvm-symbolizer', 'bin/opt', 'bin/scan-build', 'bin/scan-view',
                'include/clang-c/Index.h', 'include/llvm-c/Core.h', 'lib/clang/%s/include/omp.h' % resdir_version,
                'lib/clang/%s/include/stddef.h' % resdir_version, 'lib/libclang.%s' % shlib_ext,
                'lib/libomp.%s' % shlib_ext,
            ],
            'dirs': ['include/llvm', 'lib/clang/%s/lib' % resdir_version, 'lib32'],
        }

        custom_commands = [
            "clang --help",
            "clang++ --help",
            "clang-%s --help" % LooseVersion(self.clangversion).version[0],
            "clang-cpp --help",
            "flang --help",
            "llvm-config --cxxflags",
        ]

        self._sanity_check_gcc_prefix()

        # Check if clang++ can actually compile programs. This can fail if the wrong driver is picked up by LLVM.
        tmpdir = tempfile.mkdtemp()
        write_file(os.path.join(tmpdir, 'minimal.cpp'), AOCC_MINIMAL_CPP_EXAMPLE)
        minimal_cpp_compiler_cmd = "cd %s && clang++ minimal.cpp -o minimal_cpp" % tmpdir
        custom_commands.append(minimal_cpp_compiler_cmd)
        # Check if flang can actually compile programs. This can fail if the wrong driver is picked up by LLVM.
        write_file(os.path.join(tmpdir, 'minimal.f90'), AOCC_MINIMAL_FORTRAN_EXAMPLE)
        minimal_f90_compiler_cmd = "cd %s && flang minimal.f90 -o minimal_f90" % tmpdir
        custom_commands.append(minimal_f90_compiler_cmd)

        super(EB_AOCC, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Custom variables for AOCC module."""
        txt = super(EB_AOCC, self).make_module_extra()
        # we set the symbolizer path so that asan/tsan give meanfull output by default
        asan_symbolizer_path = os.path.join(self.installdir, 'bin', 'llvm-symbolizer')
        txt += self.module_generator.set_environment('ASAN_SYMBOLIZER_PATH', asan_symbolizer_path)
        # setting the AOCChome path
        txt += self.module_generator.set_environment('AOCChome', self.installdir)
        return txt
