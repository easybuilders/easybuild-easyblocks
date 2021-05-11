##
# Copyright 2013-2019 Ghent University
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
EasyBuild support for building and installing Lumerical, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import glob
import os
import shutil
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.easyblocks.generic.rpm import rebuild_rpm
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_dir
from easybuild.tools.run import run_cmd


class EB_Lumerical(PackedBinary):
    """Support for building/installing Lumerical."""

    def extract_step(self):
        """
        After unpacking the main tar file, we need to unpack the rpm
        inside it.
        """
        super(EB_Lumerical, self).extract_step()

        rpms = glob.glob(os.path.join(self.src[0]['finalpath'], 'rpm_install_files', 'Lumerical-*.rpm'))
        if len(rpms) != 1:
            raise EasyBuildError("Incorrect number of RPMs found, was expecting exactly one: %s", rpms)

        self.log.info("Found RPM: {}".format(rpms[0]))

        cmd = "rpm2cpio %s | cpio -idm " % rpms[0]
        run_cmd(cmd, log_all=True, simple=True)

    def make_installdir(self):
        """Override installdir creation"""
        self.log.warning("Not pre-creating installation directory %s" % self.installdir)
        self.cfg['dontcreateinstalldir'] = True
        super(EB_Lumerical, self).make_installdir()

    def build_step(self):
        """No build step for Lumerical."""
        pass

    def install_step(self):
        """Install Lumerical using copy tree."""
        mj_version = self.version.split('-')[0]
        fdtd_dir = os.path.join(self.cfg['start_dir'], 'opt', 'lumerical', mj_version)

        if not os.path.isdir(fdtd_dir):
            dirs = os.listdir(os.path.join(self.cfg['start_dir'], 'opt', 'lumerical'))
            if len(dirs) != 1:
                raise EasyBuildError("Install: can't determine source directory in {}".format(dirs))
            mj_version = dirs[0]
            # Is this sanity check necessary?
            if mj_version[0] != 'v':
                raise EasyBuildError("Install: directory {} does not start with a 'v'".format(mj_version))

        fdtd_dir = os.path.join(self.cfg['start_dir'], 'opt', 'lumerical', mj_version)
        self.log.info("Found install source directory: {}".format(fdtd_dir))

        copy_dir(fdtd_dir, self.installdir, symlinks=self.cfg['keepsymlinks'])

    def sanity_check_step(self):
        """Custom sanity check for Lumerical."""
        custom_paths = {
            'files': ['bin/fdtd-solutions'],
            'dirs': ['lib'],
        }
        super(EB_Lumerical, self).sanity_check_step(custom_paths=custom_paths)
