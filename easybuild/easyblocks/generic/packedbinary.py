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
EasyBlock for binary applications that need unpacking, e.g., binary applications shipped as a .tar.gz file

@author: Jens Timmerman (Ghent University)
"""
import os

from easybuild.framework.easyblock import EasyBlock
from easybuild.easyblocks.generic.binary import Binary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, copy


class PackedBinary(Binary, EasyBlock):
    """Support for installing packed binary software.
    Just unpack the sources in the install dir
    """

    def extract_step(self):
        """Unpack the source"""
        EasyBlock.extract_step(self)

    def install_step(self):
        """Copy all unpacked source files/directories to install directory, one-by-one."""
        change_dir(self.builddir)
        for src in os.listdir(self.builddir):
            srcpath = os.path.join(self.builddir, src)
            # we only handle the case of a single file and no install_cmd here
            if os.path.isfile(srcpath) and self.cfg.get('install_cmd', None) is None:
                copy(srcpath, self.installdir)
            else:
                if os.path.isdir(srcpath):
                    self.cfg['start_dir'] = src
                elif os.path.isfile(srcpath):
                    self.cfg['start_dir'] = self.builddir
                else:
                    raise EasyBuildError("Path %s is not a file nor a directory?", srcpath)
                Binary.install_step(self)
