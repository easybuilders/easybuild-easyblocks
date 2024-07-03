##
# Copyright 2013-2024 Ghent University
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
EasyBuild support for building and installing Libint, implemented as an easyblock

@author: Toon Verstraelen (Ghent University)
@author: Ward Poelmans (Ghent University)
"""

import os.path
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.configuremake import DEFAULT_CONFIGURE_CMD, ConfigureMake
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.tools.filetools import change_dir, extract_file
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Libint(CMakeMake):

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for Libint."""
        extra_vars = {
            'libint_compiler_configopts': [True, "Configure options for Libint compiler", CUSTOM],
            'with_fortran': [False, "Enable Fortran support", CUSTOM],
        }
        return CMakeMake.extra_options(extra_vars)

    def configure_step(self):
        """Add some extra configure options."""

        self_version = LooseVersion(self.version)
        if self_version >= '2.6.0':
            # Libint 2.6.0 requires first compiling the Libint compiler,
            # by running configure with appropriate options, followed by 'make export'
            # and unpacking the resulting source tarball;
            # see https://github.com/evaleev/libint/wiki#compiling-libint-compiler

            # CMake is recommended, but configuring with Fortran support doesn't work correctly yet in Libint 2.6.0
            # so stick to traditional configure script for now
            print_msg("configuring Libint compiler...")

            # first run autogen.sh script to generate initial configure script
            run_cmd("./autogen.sh")

            cmd = ' '.join([
                self.cfg['preconfigopts'],
                './configure',
                self.cfg['configopts'],
                self.cfg['libint_compiler_configopts'],
            ])
            run_cmd(cmd)

            print_msg("generating Libint library...")
            run_cmd("make export")

            source_fn = 'libint-%s.tgz' % self.version
            if os.path.exists(source_fn):
                extract_file(source_fn, os.getcwd(), change_into_dir=False)
                change_dir('libint-%s' % self.version)
            else:
                raise EasyBuildError("Could not find generated source tarball after 'make export'!")

        # Libint < 2.7.0 can be configured using configure script,
        # Libint >= 2.7.0 should be configured via cmake
        if self_version < '2.7.0':

            # also build shared libraries (not enabled by default)
            self.cfg.update('configopts', "--enable-shared")

            if self.toolchain.options['pic']:
                # Enforce consistency.
                self.cfg.update('configopts', "--with-pic")

            if self_version >= '2.0' and self_version < '2.1':
                # the code in libint is automatically generated and hence it is in some
                # parts so complex that -O2 or -O3 compiler optimization takes forever
                self.cfg.update('configopts', "--with-cxx-optflags='-O1'")

            elif self_version >= '2.1' and self_version < '2.6.0':
                # pass down $CXXFLAGS to --with-cxxgen-optflags configure option;
                # mainly to avoid warning about it not being set (but $CXXFLAGS is picked up anyway in practice)
                # However this isn't required/supported anymore in the already generated "source",
                # see the above creation of the LibInt compiler/library
                self.cfg.update('configopts', "--with-cxxgen-optflags='%s'" % os.getenv('CXXFLAGS'))

            # --enable-fortran is only a known configure option for Libint library, not for Libint compiler,
            # so only add --enable-fortran *after* configuring & generating Libint compiler
            if self.cfg['with_fortran']:
                self.cfg.update('configopts', '--enable-fortran')

            self.cfg['configure_cmd'] = DEFAULT_CONFIGURE_CMD
            ConfigureMake.configure_step(self)

        else:
            if self.cfg['with_fortran']:
                self.cfg.update('configopts', '-DENABLE_FORTRAN=ON')

            # also build shared libraries (not enabled by default)
            self.cfg.update('configopts', "-DLIBINT2_BUILD_SHARED_AND_STATIC_LIBS=ON")

            # specify current directory as source directory (that contains CMakeLists.txt),
            # since that's the path to the unpacked source tarball for Libint library (created by 'make export')
            super(EB_Libint, self).configure_step(srcdir=os.getcwd())

    def test_step(self):
        """Run Libint test suite for recent versions"""
        if LooseVersion(self.version) >= LooseVersion('2.1') and self.cfg['runtest'] is None:
            self.cfg['runtest'] = 'check'

        super(EB_Libint, self).test_step()

    def sanity_check_step(self):
        """Custom sanity check for Libint."""
        shlib_ext = get_shared_lib_ext()

        if LooseVersion(self.version) >= LooseVersion('2.0'):
            custom_paths = {
                'files': [os.path.join('lib', 'libint2.a'), os.path.join('lib', 'libint2.%s' % shlib_ext)],
                'dirs': [os.path.join('include', 'libint2')],
            }
            if LooseVersion(self.version) >= LooseVersion('2.1'):
                custom_paths['files'].extend([
                    os.path.join('include', 'libint2.h'),
                    os.path.join('include', 'libint2.hpp'),
                ])
                custom_paths['dirs'].extend([
                    os.path.join('share', 'libint'),
                    os.path.join('lib', 'pkgconfig'),
                ])
            else:
                custom_paths['files'].append(os.path.join('include', 'libint2', 'libint2.h'))

            if self.cfg['with_fortran']:
                custom_paths['files'].append(os.path.join('include', 'libint_f.mod'))
        else:
            headers = [os.path.join('include', 'libint', x) for x in ['libint.h', 'hrr_header.h', 'vrr_header.h']]
            libs = [os.path.join('lib', 'libint.a'), os.path.join('lib', 'libint.%s' % shlib_ext)]
            custom_paths = {
                'files': headers + libs,
                'dirs': [],
            }
        super(EB_Libint, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Specify correct CPATH for this installation."""
        guesses = super(EB_Libint, self).make_module_req_guess()
        if LooseVersion(self.version) >= LooseVersion('2.0'):
            libint_include = os.path.join('include', 'libint2')
        else:
            libint_include = os.path.join('include', 'libint')
        guesses.update({
            'CPATH': ['include', libint_include],
        })
        return guesses
