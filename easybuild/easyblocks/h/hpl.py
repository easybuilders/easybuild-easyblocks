##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for building and installing HPL, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, copy_file, mkdir, remove_file, symlink
from easybuild.tools.run import run_shell_cmd


class EB_HPL(ConfigureMake):
    """
    Support for building HPL (High Performance Linpack)
    - create Make.UNKNOWN
    - build with make and install
    """

    def configure_step(self, subdir=None):
        """
        Create Make.UNKNOWN file to build from
        - provide subdir argument so this can be reused in HPCC easyblock
        """

        basedir = self.cfg['start_dir']
        if subdir:
            makeincfile = os.path.join(basedir, subdir, 'Make.UNKNOWN')
            setupdir = os.path.join(basedir, subdir, 'setup')
        else:
            makeincfile = os.path.join(basedir, 'Make.UNKNOWN')
            setupdir = os.path.join(basedir, 'setup')

        change_dir(setupdir)

        cmd = "/bin/bash make_generic"

        run_shell_cmd(cmd)

        remove_file(makeincfile)
        symlink(os.path.join(setupdir, 'Make.UNKNOWN'), makeincfile)

        # go back
        change_dir(self.cfg['start_dir'])

    def build_step(self, topdir=None):
        """
        Build with make and correct make options
        - provide topdir argument so this can be reused in HPCC easyblock
        """

        for envvar in ['MPICC', 'LIBLAPACK_MT', 'CPPFLAGS', 'LDFLAGS', 'CFLAGS']:
            # environment variable may be defined but empty
            if os.getenv(envvar, None) is None:
                raise EasyBuildError("Required environment variable %s not found (no toolchain used?).", envvar)

        # build dir
        if not topdir:
            topdir = self.cfg['start_dir']
        extra_makeopts = 'TOPdir="%s" ' % topdir

        # compilers
        extra_makeopts += 'CC="%(mpicc)s" MPICC="%(mpicc)s" LINKER="%(mpicc)s" ' % {'mpicc': os.getenv('MPICC')}

        # libraries: LAPACK and FFTW
        extra_makeopts += 'LAlib="%s" ' % os.getenv('LIBLAPACK_MT')

        # HPL options
        extra_makeopts += 'HPL_OPTS="%s " ' % os.getenv('CPPFLAGS')

        # linker flags
        extra_makeopts += 'LINKFLAGS="%s %s %s" ' % (os.getenv('CFLAGS'), os.getenv('LDFLAGS'), os.getenv('LIBS', ''))

        # C compilers flags
        extra_makeopts += "CCFLAGS='$(HPL_DEFS) %s' " % os.getenv('CFLAGS')

        # set options and build
        self.cfg.update('buildopts', extra_makeopts)
        super(EB_HPL, self).build_step()

    def install_step(self):
        """
        Install by copying files to install dir
        """
        srcdir = os.path.join(self.cfg['start_dir'], 'bin', 'UNKNOWN')
        destdir = os.path.join(self.installdir, 'bin')
        mkdir(destdir)
        for filename in ["xhpl", "HPL.dat"]:
            srcfile = os.path.join(srcdir, filename)
            copy_file(srcfile, destdir)

    def sanity_check_step(self):
        """
        Custom sanity check for HPL
        """

        custom_paths = {
            'files': ["bin/xhpl"],
            'dirs': []
        }

        super(EB_HPL, self).sanity_check_step(custom_paths)
