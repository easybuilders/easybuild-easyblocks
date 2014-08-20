##
# Copyright 2009-2013 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
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
EasyBuild support for software that is configured with CMake, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Ward Poelmans (Ghent University)
"""

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.framework.easyconfig import MANDATORY


class CMakeCP(CMakeMake, MakeCp):
    """
    Support for configuring build with CMake instead of traditional configure script
    and copyting the resulted files to the install dir instead of doing make install
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """
        Define list of files or directories to be copied after make
        """
        extra = {
            'files_to_copy': [{}, "List of files or dirs to copy", MANDATORY],
        }
        if extra_vars is None:
            extra_vars = {}
        extra.update(extra_vars)
        return CMakeMake.extra_options(extra_vars=extra)

    def configure_step(self, cmd_prefix='', srcdir=None, builddir=None):
        """Configure build using cmake"""
        return CMakeMake.configure_step(self, cmd_prefix=cmd_prefix, srcdir=srcdir, builddir=builddir)

    def install_step(self):
        """Install by copying specified files and directories."""
        return MakeCp.install_step(self)
