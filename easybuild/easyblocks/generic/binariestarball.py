##
# Copyright 2013 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for installing a tarball of binaries, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os
import shutil
import stat

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions


class BinariesTarball(Tarball):
    """
    Support for installing a tarball of binaries
    """
    @staticmethod
    def extra_options(extra_vars=None):
        """
        Define list of files to be copied during the installation process
        """
        extra_vars = Tarball.extra_options(extra_vars)
        # Allow specification of files to copy explicitly.
        # If files_to_copy is a zero-length list, all files (but not
        # directories, etc.) in start_dir will be copied with their
        # current names.
        extra_vars.update({
            'files_to_copy': [None, "List of optional (source_file, destination_file) tuples", CUSTOM,]
        })
        return extra_vars

    def install_step(self):
        """Install by copying unzipped binaries to 'bin' subdir of installation dir, and fixing permissions."""

        bindir = os.path.join(self.installdir, 'bin')
        items_to_copy = []
        try:
            os.makedirs(bindir)
            if self.cfg['files_to_copy'] is None:
                for item in os.listdir(self.cfg['start_dir']):
                    items_to_copy.append((os.path.join(self.cfg['start_dir'], item), item))
            else:
                items_to_copy.append(os.path.join(self.cfg['start_dir'], item) for item in self.cfg['files_to_copy'])
            for (item, destname) in items_to_copy:
                if os.path.isfile(item):
                    shutil.copy2(item, os.path.join(bindir, destname))
                    # make sure binary has executable permissions
                    adjust_permissions(os.path.join(bindir, destname), stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH, add=True)
                    self.log.debug("Copied %s to %s and fixed permissions", item, bindir)
                else:
                    self.log.warning("%s: not a file. Skipping.", item)
        except OSError, err:
            raise EasyBuildError("Copying binaries to install dir 'bin' failed: %s", err)
