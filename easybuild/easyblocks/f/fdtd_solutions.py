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
EasyBuild support for building and installing FDTD Solutions, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import glob
import os
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_dir
from easybuild.tools.run import run_cmd


class EB_FDTD_underscore_Solutions(PackedBinary):
    """Support for building/installing FDTD Solutions."""

    def extract_step(self):
        """
        After unpacking the main tar file, we need to unpack the rpm
        inside it.
        """
        super(EB_FDTD_underscore_Solutions, self).extract_step()

        rpms = glob.glob(os.path.join(self.src[0]['finalpath'], 'rpm_install_files', '*.rpm'))
        if len(rpms) != 1:
            raise EasyBuildError("Incorrect number of RPMs found, was expecting exactly one: %s", rpms)
        cmd = "rpm2cpio %s | cpio -idm " % rpms[0]
        run_cmd(cmd, log_all=True, simple=True)

    def make_installdir(self):
        """Override installdir creation"""
        self.log.warning("Not pre-creating installation directory %s" % self.installdir)
        self.cfg['dontcreateinstalldir'] = True
        super(EB_FDTD_underscore_Solutions, self).make_installdir()

    def build_step(self):
        """No build step for FDTD Solutions."""
        pass

    def install_step(self):
        """Install FDTD Solutions using copy tree."""

        top_dir = os.path.join(self.cfg['start_dir'], 'opt', 'lumerical', 'fdtd')
        if not os.path.exists(top_dir):
            top_dir_glob = os.path.join(self.cfg['start_dir'], 'opt', 'lumerical', 'v[0-9]*')
            v_dirs = glob.glob(top_dir_glob)
            if len(v_dirs) == 1:
                top_dir = v_dirs[0]
            else:
                raise EasyBuildError("Failed to isolate top-level directory using %s", top_dir_glob)

        copy_dir(top_dir, self.installdir, symlinks=self.cfg['keepsymlinks'])

    def sanity_check_step(self):
        """Custom sanity check for FDTD Solutions."""
        custom_paths = {
            'files': ['bin/fdtd-solutions'],
            'dirs': ['lib'],
        }
        super(EB_FDTD_underscore_Solutions, self).sanity_check_step(custom_paths=custom_paths)
