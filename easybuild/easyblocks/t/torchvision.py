##
# Copyright 2021-2021 Ghent University
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
EasyBuild support for building and installing torchvision, implemented as an easyblock

@author: Alexander Grund (TU Dresden)
"""

from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root, get_software_version
import easybuild.tools.environment as env


class EB_torchvision(PythonPackage):
    """Support for building/installing TorchVison."""

    @staticmethod
    def extra_options():
        """Change some defaults."""
        extra_vars = PythonPackage.extra_options()
        extra_vars['use_pip'][0] = True
        extra_vars['download_dep_fail'][0] = True
        extra_vars['sanity_pip_check'][0] = True
        return extra_vars

    def configure_step(self):
        """Set up torchvision config"""
        if not get_software_root('PyTorch'):
            raise EasyBuildError('PyTorch not found as a dependency')

        # Note: Those can be overwritten by e.g. preinstallopts
        env.setvar('BUILD_VERSION', self.version)
        env.setvar('PYTORCH_VERSION', get_software_version('PyTorch'))
        if get_software_root('CUDA'):
            cuda_cc = self.cfg['cuda_compute_capabilities'] or build_option('cuda_compute_capabilities')
            if cuda_cc:
                env.setvar('TORCH_CUDA_ARCH_LIST', ';'.join(cuda_cc))

        super(EB_torchvision, self).configure_step()
