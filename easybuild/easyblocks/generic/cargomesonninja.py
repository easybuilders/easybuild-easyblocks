##
# Copyright 2018-2026 Ghent University
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
EasyBuild support for installing software with Meson & Ninja that internally uses Cargo.

@author: Mikael Oehman (Chalmers University of Technology)
"""

from easybuild.easyblocks.generic.cargo import Cargo
from easybuild.easyblocks.generic.mesonninja import MesonNinja


class CargoMesonNinja(MesonNinja, Cargo):  # MesonNinja must come first to take precedence
    """
    Support for building and installing software with 'meson' and 'ninja',
    but with Cargo environment variables set.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to Cargo"""
        extra_vars = MesonNinja.extra_options(extra_vars)
        extra_vars = Cargo.extra_options(extra_vars)  # not all extra options here will used here

        return extra_vars

    def extract_step(self):
        """Specifically use the overloaded variant from Cargo as is populates vendored sources with checksums."""
        return Cargo.extract_step(self)

    def configure_step(self):
        """Run configure for Cargo and PythonPackage"""
        Cargo.configure_step(self)
        MesonNinja.configure_step(self)
