##
# Copyright 2013-2020 Ghent University
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
@author: Sergey Chulkov (University of Lincoln)
"""

import os.path
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.tools.filetools import change_dir, extract_file, mkdir
from easybuild.tools.run import run_cmd

EXPORTED_LIBRARY_BASE_NAME = "libint-cp2k"
EXPORTED_LIBRARY_FULL_NAME = EXPORTED_LIBRARY_BASE_NAME + ".tgz"
DEFAULT_BUILD_DIR_NAME = "build"


# As of version 2.6.0 the Autoconf build is deprecated.
# Starting from version 2.7.0 only CMake can be used to build the generated library.
# However Autoconf is still needed to build the Libint compiler.
class EB_Libint_CMake(CMakeMake):

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for Libint."""
        extra_vars = {
            'libint_compiler_configopts': [True, "Configure options for Libint compiler", CUSTOM],
        }
        return CMakeMake.extra_options(extra_vars)

    def configure_step(self):
        # a top-level directory where the source tarball is unpacked
        basedir = os.getcwd()

        if LooseVersion(self.version) >= LooseVersion('2.6'):
            # Libint 2.6.0 requires first compiling the Libint compiler,
            # by running configure with appropriate options, followed by 'make export'
            # and unpacking the resulting source tarball;
            # see https://github.com/evaleev/libint/wiki#compiling-libint-compiler

            # CMake is recommended, but configuring with Fortran support doesn't work correctly yet in Libint 2.6.0
            # so stick to traditional configure script for now
            print_msg("configuring Libint compiler...")
            self.cfg.update('libint_compiler_configopts', "--with-libint-exportdir=" + EXPORTED_LIBRARY_BASE_NAME)

            # first run autogen.sh script to generate initial configure script
            run_cmd(os.path.join(".", "autogen.sh"), log_all=True, simple=True)

            # make a separate directory where the libint compiler will be built
            mkdir(DEFAULT_BUILD_DIR_NAME, parents=False)
            change_dir(DEFAULT_BUILD_DIR_NAME)

            cmd = ' '.join([
                os.path.join("..", "configure"),
                self.cfg['libint_compiler_configopts'],
            ])
            run_cmd(cmd, log_all=True, simple=True)

            print_msg("generating Libint library...")
            run_cmd("make export", log_all=True, simple=True)

            if not os.path.exists(EXPORTED_LIBRARY_FULL_NAME):
                raise EasyBuildError("Could not find generated source tarball after 'make export'!")
        else:
            raise EasyBuildError("Please use 'EB_Libint' easyblock for Libint < 2.6.0")

        # extract EXPORTED_LIBRARY_FULL_NAME tarball from the current directory into the top-level directory
        extract_file(os.path.join(os.getcwd(), EXPORTED_LIBRARY_FULL_NAME), basedir, change_into_dir=False)

        # a directory where the generated library is unpacked
        srcdir = os.path.join(basedir, EXPORTED_LIBRARY_BASE_NAME)
        # a directory where the generated library is going to be built
        builddir = os.path.join(srcdir, DEFAULT_BUILD_DIR_NAME)

        print_msg("compiling generated Libint library...")
        super(EB_Libint_CMake, self).configure_step(srcdir=srcdir, builddir=builddir)

    def test_step(self):
        """Run Libint test suite for recent versions"""
        if LooseVersion(self.version) >= LooseVersion('2.6') and self.cfg['runtest'] is None:
            self.cfg['runtest'] = 'check'

        super(EB_Libint_CMake, self).test_step()

    def make_module_req_guess(self):
        """Specify correct CPATH for this installation."""
        guesses = super(EB_Libint_CMake, self).make_module_req_guess()
        libint_include = os.path.join('include', 'libint2')
        guesses.update({
            'CPATH': ['include', libint_include],
        })
        return guesses
