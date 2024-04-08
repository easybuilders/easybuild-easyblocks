##
# Copyright 2019-2024 Ghent University
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
EasyBuild support for software that uses
CMake configure step and Ninja build install.

@author: Kenneth Hoste (Ghent University)
@author: Pavel Grochal (INUITS)
"""
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.mesonninja import MesonNinja


class CMakeNinja(CMakeMake, MesonNinja):
    """Support for configuring with CMake, building and installing with MesonNinja."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to CMakeNinja."""
        extra_vars = CMakeMake.extra_options(extra_vars)
        extra_vars['generator'][0] = 'Ninja'
        extra_vars.update({
            key: value for key, value in MesonNinja.extra_options().items()
            if key.startswith('build_') or key.startswith('install_')
        })
        return extra_vars

    def configure_step(self, *args, **kwargs):
        """Configure using CMake."""
        CMakeMake.configure_step(self, *args, **kwargs)

    def build_step(self, *args, **kwargs):
        """Build using MesonNinja."""
        MesonNinja.build_step(self, *args, **kwargs)

    def install_step(self, *args, **kwargs):
        """Install using MesonNinja."""
        MesonNinja.install_step(self, *args, **kwargs)
