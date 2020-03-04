##
# Copyright 2009-2019 Ghent University
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
EasyBuild support for Hypre, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Mikael OEhman (Chalmers University of Technology)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Hypre(ConfigureMake):
    """Support for building Hypre."""

    def configure_step(self):
        """Configure Hypre build after setting extra configure options."""

        self.cfg.update('configopts', '--with-MPI-include=%s' % os.getenv('MPI_INC_DIR'))

        # Only supports external libraries when building a shared library.
        self.cfg.update('configopts', '--enable-shared')

        # While there are a --with-{blas|lapack}-libs flag, it's not useable, because of how Hypre treats it.
        # We need to patch the code anyway to prevent it from building its own BLAS packages.

        super(EB_Hypre, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for Hypre."""

        custom_paths = {
                        'files': ['lib/libHYPRE.' + get_shared_lib_ext()],
                        'dirs': ['include']
                       }

        super(EB_Hypre, self).sanity_check_step(custom_paths=custom_paths)
