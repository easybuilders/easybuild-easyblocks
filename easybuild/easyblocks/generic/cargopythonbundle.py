##
# Copyright 2018-2024 Ghent University
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
EasyBuild support for installing a bundle of Python packages, where some are built with Rust

@author: Mikael Oehman (Chalmers University of Technology)
"""

from easybuild.easyblocks.generic.cargo import Cargo
from easybuild.easyblocks.generic.pythonbundle import PythonBundle


class CargoPythonBundle(PythonBundle, Cargo):  # PythonBundle must come first to take precedence
    """
    Builds just like PythonBundle with setup for Rust and crates from Cargo easyblock

    The cargo init step will set up the environment variables for rustc and vendor sources
    but all the build steps are triggered like normal.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to Cargo"""
        extra_vars = PythonBundle.extra_options(extra_vars)
        extra_vars = Cargo.extra_options(extra_vars)  # not all extra options here will used here

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Constructor for CargoPythonBundle easyblock."""
        self.check_for_sources = False  # make Bundle allow sources (as crates are treated as sources)
        super(CargoPythonBundle, self).__init__(*args, **kwargs)

    def extract_step(self):
        """Specifically use the overloaded variant from Cargo as is populates vendored sources with checksums."""
        return Cargo.extract_step(self)
