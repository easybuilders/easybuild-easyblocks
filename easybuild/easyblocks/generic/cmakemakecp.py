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
EasyBuild support for software configured with CMake but without 'make install' step, implemented as an easyblock

@author: Samuel Moors, Vrije Universiteit Brussel (VUB)
"""
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.makecp import MakeCp
import os


class CMakeMakeCp(CMakeMake, MakeCp):
    """Software configured with CMake but without 'make install' step

    We use the default CMakeMake implementation, and use install_step from MakeCp.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        extra_vars = MakeCp.extra_options(extra_vars)
        return CMakeMake.extra_options(extra_vars=extra_vars)

    def configure_step(self, srcdir=None, builddir=None):
        """Configure build using CMake"""
        return CMakeMake.configure_step(self, srcdir=srcdir, builddir=builddir)

    def install_step(self):
        """Install by copying specified files and directories."""
        if self.cfg.get('separate_build_dir', False):
            if self.separate_build_dir:
                self.cfg['start_dir'] = self.separate_build_dir
            else:
                self.cfg['start_dir'] = os.path.join(self.builddir, 'easybuild_obj')

        return MakeCp.install_step(self)
