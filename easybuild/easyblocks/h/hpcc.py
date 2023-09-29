##
# Copyright 2009-2023 Ghent University
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
import shutil

from easybuild.easyblocks.h.hpl import EB_HPL
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, remove_file, symlink
from easybuild.tools.run import run_cmd


class EB_HPCC(EB_HPL):
    """
    Support for building HPCC (HPC Challenge)
    - create Make.UNKNOWN
    - build with make and install
    """

    def configure_step(self):
        """
        Create Make.UNKNOWN file to build from
        - provide subdir argument so this can be reused in HPCC easyblock
        """
        super(EB_HPCC, self).configure_step(subdir='hpl')

    def build_step(self):
        """
        Build with make and correct make options
        """
        super(EB_HPCC, self).build_step(topdir='../../..')

    def install_step(self):
        """
        Install by copying files to install dir
        """
        srcdir = self.cfg['start_dir']
        destdir = os.path.join(self.installdir, 'bin')
        filename = 'hpcc'
        try:
            os.makedirs(destdir)
            srcfile = os.path.join(srcdir, filename)
            shutil.copy2(srcfile, destdir)
        except OSError as err:
            raise EasyBuildError("Copying %s to installation dir %s failed: %s", srcfile, destdir, err)

    def sanity_check_step(self):
        """
        Custom sanity check for HPL
        """

        custom_paths = {
            'files': ["bin/hpcc"],
            'dirs': []
        }

        super(EB_HPL, self).sanity_check_step(custom_paths)
