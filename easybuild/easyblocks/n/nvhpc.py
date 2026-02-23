##
# Copyright 2024-2026 Ghent University
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
EasyBuild support for installing NVIDIA HPC SDK as a full toolchain

@author: Alex Domingo (Vrije Universiteit Brussel)
"""
from easybuild.easyblocks.generic.nvidiabase import NvidiaBase
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_version


class EB_NVHPC(NvidiaBase):
    """
    Support for installing the NVIDIA HPC SDK (NVHPC)
    Including compilers, MPI and math libraries
    """

    def prepare_step(self, *args, **kwargs):
        """Prepare environment for installation."""
        super().prepare_step(*args, **kwargs)

        # Mandatory options for NVHPC with nvidia-compilers
        nvcomp_dependency_version = get_software_version('nvidia-compilers')
        if nvcomp_dependency_version:
            if nvcomp_dependency_version != self.version:
                error_msg = "Version of NVHPC does not match version of nvidia-compilers in dependency list"
                raise EasyBuildError(error_msg)

            nvhpc_options = [
                'module_nvhpc_own_mpi',
                'module_add_nccl',
                'module_add_nvshmem',
                'module_add_math_libs',
            ]
            for opt in nvhpc_options:
                if not self.cfg[opt]:
                    self.log.debug(f"Option '{opt}' forced enabled in {self.name}-{self.version} with nvidia-compilers")
                self.cfg[opt] = True

        self._update_nvhpc_environment()
