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
EasyBuild support for installing the Intel Fortran compiler suite, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Ward Poelmans (Ghent University)
"""

import os
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.easyblocks.icc import EB_icc  # @UnresolvedImport
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_ifort(EB_icc, IntelBase):
    """
    Class that can be used to install ifort
    - minimum version suported: 2020.x
    - will fail for all older versions (due to newer silent installer)
    """

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
        # since we rely on it being there in make_module_req_guess
        if self.comp_libs_subdir:
            custom_paths['dirs'].append(self.comp_libs_subdir)

        custom_commands = ["which ifort"]

        IntelBase.sanity_check_step(self, custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_req_guess(self):
        """
        Additional paths to consider for prepend-paths statements in module file
        """
        guesses = super(EB_ifort, self).make_module_req_guess()
        # This enables the creation of fortran 2008 bindings in MPI
        guesses['CPATH'].append('include')

        return guesses
