##
# Copyright 2024-2025 Ghent University
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
EasyBuild support for installing NVIDIA HPC SDK compilers

@author: Alex Domingo (Vrije Universiteit Brussel)
"""
from easybuild.easyblocks.generic.nvidiabase import NvidiaBase
from easybuild.tools.build_log import EasyBuildError


class EB_nvidia_minus_compilers(NvidiaBase):
    """
    Support for installing the NVIDIA HPC SDK (NVHPC) compilers
    i.e. nvc, nvcc, nvfortran

    Support for MPI or numeric libraries is disabled.
    """

    def prepare_step(self, *args, **kwargs):
        """Prepare environment for installation."""
        super().prepare_step(*args, **kwargs)

        # Unsupported NVHPC options in nvidia-compilers are forced disabled
        disabled_nvhpc_options = [
            'module_add_math_libs',
            'module_add_nccl',
            'module_add_nvshmem',
            'module_byo_compilers',
            'module_nvhpc_own_mpi',
        ]
        for nvhpc_opt in disabled_nvhpc_options:
            if self.cfg[nvhpc_opt]:
                raise EasyBuildError(f"Option '{nvhpc_opt}' not supported in {self.name}-{self.version}")
            self.cfg[nvhpc_opt] = False

        self._update_nvhpc_environment()
