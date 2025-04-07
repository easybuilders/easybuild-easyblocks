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
EasyBuild support for building and installing HPCC, implemented as an easyblock

@author: Samuel Moors (Vrije Universiteit Brussel)
"""

import os

from easybuild.easyblocks.hpl import EB_HPL
from easybuild.tools.filetools import copy_file, mkdir


class EB_HPCC(EB_HPL):
    """
    Support for building HPCC (HPC Challenge)
    - create Make.UNKNOWN
    - build with make and install
    """

    def configure_step(self):
        """
        Create Make.UNKNOWN file to build from
        """
        # the build script file should be created in the hpl subdir
        super(EB_HPCC, self).configure_step(subdir='hpl')

    def build_step(self):
        """
        Build with make and correct make options
        """
        # TOPdir should always be ../../.. regardless of what it was in the HPL build script file
        super(EB_HPCC, self).build_step(topdir='../../..')

    def install_step(self):
        """
        Install by copying files to install dir
        """
        srcdir = self.cfg['start_dir']
        destdir = os.path.join(self.installdir, 'bin')
        mkdir(destdir)
        for filename in ["hpcc", "_hpccinf.txt"]:
            srcfile = os.path.join(srcdir, filename)
            copy_file(srcfile, destdir)

    def sanity_check_step(self):
        """
        Custom sanity check for HPL
        """

        custom_paths = {
            'files': ['bin/hpcc', 'bin/_hpccinf.txt'],
            'dirs': []
        }

        custom_commands = ['hpcc']

        super(EB_HPL, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
