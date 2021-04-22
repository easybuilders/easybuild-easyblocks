##
# Copyright 2020-2021 Forschungszentrum Juelich GmbH
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

import os

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.systemtools import get_shared_lib_ext


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

    def _aocc_guess_clang_version(self):
        map_aocc_to_clang_ver = {
            '2.3.0': '11.0.0',
            '3.0.0': '12.0.0',
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

    def install_step(self):
        # EULA for AOCC must be accepted via --accept-eula-for EasyBuild configuration option,
        # or via 'accept_eula = True' in easyconfig file
        self.check_accepted_eula(more_info='http://developer.amd.com/wordpress/media/files/AOCC_EULA.pdf')

        # AOCC is based on Clang. Try to guess the clangversion from the AOCC version
        # if clangversion is not specified in the easyconfig
        if self.clangversion is None:
            self.clangversion = self._aocc_guess_clang_version()

        super(EB_AOCC, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for AOCC, based on sanity check for Clang."""
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [
                'bin/clang', 'bin/clang++', 'bin/flang', 'bin/lld', 'bin/llvm-ar', 'bin/llvm-as', 'bin/llvm-config',
                'bin/llvm-link', 'bin/llvm-nm', 'bin/llvm-symbolizer', 'bin/opt', 'bin/scan-build', 'bin/scan-view',
                'include/clang-c/Index.h', 'include/llvm-c/Core.h', 'lib/clang/%s/include/omp.h' % self.clangversion,
                'lib/clang/%s/include/stddef.h' % self.clangversion, 'lib/libc++.%s' % shlib_ext,
                'lib/libc++abi.%s' % shlib_ext, 'lib/libclang.%s' % shlib_ext, 'lib/libomp.%s' % shlib_ext,
            ],
            'dirs': ['include/llvm', 'lib/clang/%s/lib' % self.clangversion, 'lib32'],
        }

        custom_commands = [
            "clang --help",
            "clang++ --help",
            "flang --help",
            "llvm-config --cxxflags",
        ]
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

    def make_module_req_guess(self):
        """
        A dictionary of possible directories to look for.
        Include C_INCLUDE_PATH and CPLUS_INCLUDE_PATH as an addition to default ones
        """
        guesses = super(EB_AOCC, self).make_module_req_guess()
        guesses['C_INCLUDE_PATH'] = ['include']
        guesses['CPLUS_INCLUDE_PATH'] = ['include']
        return guesses
