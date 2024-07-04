##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for building and installing Mamba, implemented as an easyblock

@author: Caspar van Leeuwen (SURF)
@author: Kenneth Hoste (HPC-UGent)
"""

import os

from easybuild.easyblocks.a.anaconda import EB_Anaconda


class EB_Mamba(EB_Anaconda):
    """Support for building/installing Mamba."""

    def sanity_check_step(self):
        """
        Custom sanity check for Mamba
        """
        custom_paths = {
            'files': [os.path.join('bin', x) for x in ['2to3', 'conda', 'pydoc', 'python', 'mamba']],
            'dirs': ['etc', 'lib', 'pkgs'],
        }
        # Directly call EB_Anaconda's super, as this sanity_check_step should _overwrite_ Anaconda's (not call it)
        super(EB_Anaconda, self).sanity_check_step(custom_paths=custom_paths)
