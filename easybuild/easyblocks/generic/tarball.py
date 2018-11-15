##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for installing (precompiled) software which is supplied as a tarball,
implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.filetools import copy_dir, rmtree2


class Tarball(EasyBlock):
    """
    Precompiled software supplied as a tarball:
    - will unpack binary and copy it to the install dir
    """

    def configure_step(self):
        """
        Dummy configure method
        """
        pass

    def build_step(self):
        """
        Dummy build method: nothing to build
        """
        pass

    def install_step(self, src=None):
        """Install by copying from specified source directory (or 'start_dir' if not specified)."""
        rmtree2(self.installdir)
        copy_dir(src or self.cfg['start_dir'], self.installdir, symlinks=self.cfg['keepsymlinks'])

    def sanity_check_rpath(self):
        """Skip the rpath sanity check, this is binary software"""
        self.log.info("RPATH sanity check is skipped when using %s easyblock (derived from Tarball)",
                      self.__class__.__name__)
