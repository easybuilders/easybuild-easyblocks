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
EasyBuild support for installing the Intel Fortran compiler suite, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Ward Poelmans (Ghent University)
"""

import os

from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.easyblocks.icc import EB_icc  # @UnresolvedImport
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_ifort(EB_icc, IntelBase):
    """
    Class that can be used to install ifort
    - minimum version suported: 2020.0
    - will fail for all older versions (due to newer silent installer)
    """

    def __init__(self, *args, **kwargs):
        """Constructor, initialize class variables."""
        super().__init__(*args, **kwargs)

        if LooseVersion(self.version) < LooseVersion('2020'):
            raise EasyBuildError(
                f"Version {self.version} of {self.name} is unsupported. Mininum supported version is 2020.0."
            )

        # define list of subdirectories in search paths of module load environment
        # add additional paths to those of ICC only needed for separate ifort installations
        for envar in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
            envar.append(os.path.join(self.comp_libs_subdir, 'compiler/include'))

    def sanity_check_step(self):
        """Custom sanity check paths for ifort."""
        shlib_ext = get_shared_lib_ext()

        binprefix = 'bin'
        binfiles = ['ifort']
        binaries = [os.path.join(binprefix, f) for f in binfiles]

        libprefix = 'lib/intel64'
        libfiles = [f'lib{lib}' for lib in ['ifcore.a', f'ifcore.{shlib_ext}', 'iomp5.a', f'iomp5.{shlib_ext}']]
        libraries = [os.path.join(libprefix, f) for f in libfiles]

        custom_paths = {
            'files': binaries + libraries,
            'dirs': [],
        }

        # make very sure that expected 'compilers_and_libraries_<VERSION>/linux' subdir is there for recent versions,
        # since we rely on it being there in module_load_environment
        if self.comp_libs_subdir:
            custom_paths['dirs'].append(self.comp_libs_subdir)

        custom_commands = ["which ifort"]

        IntelBase.sanity_check_step(self, custom_paths=custom_paths, custom_commands=custom_commands)
