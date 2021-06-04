##
# Copyright 2009-2021 Ghent University
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
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Hypre(ConfigureMake):
    """Support for building Hypre."""

    def __init__(self, *args, **kwargs):
        """Easyblock constructor."""

        super(EB_Hypre, self).__init__(*args, **kwargs)

        self.config_shared = False
        self.config_static = False

    def configure_step(self):
        """Configure Hypre build after setting extra configure options."""

        if '--enable-shared' in self.cfg['configopts']:
            self.config_shared = True
            ext_libs = 'LIB%s'
        else:
            self.config_static = True
            ext_libs = '%s_STATIC_LIBS'

        # Use BLAS/LAPACK from EB
        for dep in ["BLAS", "LAPACK"]:
            blas_libs = ' '.join(os.getenv(ext_libs % dep).split(','))
            blas_libs = blas_libs.replace('-l', '')  # Remove any '-l' as those are prepended for shared builds
            self.cfg.update('configopts', '--with-%s-libs="%s"' % (dep.lower(), blas_libs))
            self.cfg.update('configopts', '--with-%s-lib-dirs="%s"' % (dep.lower(),
                                                                       os.getenv('%s_LIB_DIR' % dep)))

        # Use MPI implementation from EB
        self.cfg.update('configopts', '--with-MPI-include=%s' % os.getenv('MPI_INC_DIR'))

        super(EB_Hypre, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for Hypre."""

        # Add static and shared libs depending on configopts
        hypre_libs = list()
        if self.config_shared:
            shlib_ext = get_shared_lib_ext()
            hypre_libs.append(os.path.join('lib', 'libHYPRE.%s' % shlib_ext))
        if self.config_static:
            hypre_libs.append(os.path.join('lib', 'libHYPRE.a'))

        custom_paths = {
            'files': hypre_libs,
            'dirs': ['include']
        }

        super(EB_Hypre, self).sanity_check_step(custom_paths=custom_paths)
