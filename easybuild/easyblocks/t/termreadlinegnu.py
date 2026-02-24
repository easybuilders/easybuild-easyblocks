##
# Copyright 2025 Ghent University
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
EasyBuild support for installing Term::ReadLine::Gnu.

@author: Alexander Grund (TU Dresden)
"""

from easybuild.easyblocks.generic.perlmodule import PerlModule
from easybuild.tools.modules import get_software_root


class EB_Term_colon__colon_ReadLine_colon__colon_Gnu(PerlModule):
    """Support for installing the Term::ReadLine::Gnu Perl module."""

    def __init__(self, *args, **kwargs):
        """Set configopts for dependencies"""
        super().__init__(*args, **kwargs)
        # Use the custom --prefix option to pass the installation prefixes of all direct dependencies
        # to avoid it picking up system libraries.
        prefix = ':'.join(get_software_root(dep['name']) for dep in self.cfg.dependencies(runtime_only=True))
        self.cfg.update('configopts', f"--prefix='{prefix}'")
