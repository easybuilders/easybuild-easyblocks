##
# Copyright 2009-2020 Ghent University
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
EasyBuild support for building and installing DIRAC, implemented as an easyblock
"""
import os
import shutil

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.tools.build_log import EasyBuildError


class EB_DIRAC(CMakeMake):
    """Support for building/installing DIRAC."""

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def configure_step(self):
        """Custom configuration procedure for DIRAC."""

        # make very sure the install directory isn't there yet, since it may cause problems if it used (forced rebuild)
        if os.path.exists(self.installdir):
            self.log.warning("Found existing install directory %s, removing it to avoid problems", self.installdir)
            try:
                shutil.rmtree(self.installdir)
            except OSError as err:
                raise EasyBuildError("Failed to remove existing install directory %s: %s", self.installdir, err)

        # MPI?
        if self.toolchain.options.get('usempi', None):
            self.cfg.update('configopts', "-DENABLE_MPI=ON")

        # complete configuration with configure_method of parent
        super(EB_DIRAC, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for DIRAC."""
        custom_paths = {
            'files': ['bin/pam-dirac'],
            'dirs': ['share/dirac'],
        }
        super(EB_DIRAC, self).sanity_check_step(custom_paths=custom_paths)
