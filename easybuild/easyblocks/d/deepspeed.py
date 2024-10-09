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
EasyBuild support for building and installing DeepSpeed, implemented as an easyblock

author: Viktor Rehnberg (Chalmers University of Technology)
"""
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
import easybuild.tools.environment as env


class EB_DeepSpeed(PythonPackage):
    """Custom easyblock for DeepSpeed"""

    @staticmethod
    def extra_options():
        """Change some defaults for easyconfig parameters."""
        extra_vars = PythonPackage.extra_options()
        extra_vars['use_pip'][0] = True
        extra_vars['download_dep_fail'][0] = True
        extra_vars['sanity_pip_check'][0] = True

        # Add DeepSpeed specific vars
        extra_vars['ds_build_opts_to_skip'] = [[], "For <val> in list will set DS_BUILD_<val>=0 (default: [])", CUSTOM]
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize DeepSpeed easyblock."""
        super().__init__(*args, **kwargs)

        dep_names = set(dep['name'] for dep in self.cfg.dependencies())

        # enable building with GPU support if CUDA is included as dependency
        if 'CUDA' in dep_names:
            self.with_cuda = True
        else:
            self.with_cuda = False

    @property
    def cuda_compute_capabilities(self):
        return self.cfg['cuda_compute_capabilities'] or build_option('cuda_compute_capabilities')

    def configure_step(self):
        """Set up DeepSpeed config"""
        # require that PyTorch is listed as dependency
        dep_names = set(dep['name'] for dep in self.cfg.dependencies())
        if 'PyTorch' not in dep_names:
            raise EasyBuildError('PyTorch not found as a dependency')

        if self.with_cuda:
            # https://github.com/microsoft/DeepSpeed/issues/3358
            env.setvar('NVCC_PREPEND_FLAGS', '--forward-unknown-opts')

            if self.cuda_compute_capabilities:
                # specify CUDA compute capabilities via $TORCH_CUDA_ARCH_LIST
                env.setvar('TORCH_CUDA_ARCH_LIST', ';'.join(self.cuda_compute_capabilities))

        # By default prebuild all opts with a few exceptions
        # http://www.deepspeed.ai/tutorials/advanced-install/#pre-install-deepspeed-ops
        # > DeepSpeed will only install any ops that are compatible with your machine
        env.setvar('DS_BUILD_OPS', '1')

        # Some may be problematic for different reasons, these are specified in the easyconfig
        for opt in self.cfg['ds_build_opts_to_skip']:
            env.setvar('DS_BUILD_{}'.format(opt), '0')

        super().configure_step()

    def sanity_check_step(self):
        '''Custom sanity check for DeepSpeed.'''
        custom_paths = {
            'files': ['bin/deepspeed'],
            'dirs': [],
        }
        custom_commands = [
            'deepspeed --help',
            'python -m deepspeed.env_report',
        ]

        return super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
