##
# Copyright 2017-2026 Ghent University
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

@author: Viktor Rehnberg (Chalmers University of Technology)
@author: Alexander Grund (TU Dresden)
"""
import os
import tempfile

from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.modules import get_software_root
import easybuild.tools.environment as env


class EB_DeepSpeed(PythonPackage):
    """Custom easyblock for DeepSpeed"""

    @staticmethod
    def extra_options():
        """Add extra options for DeepSpeed."""
        return PythonPackage.extra_options({
            'jit_only_ops': [[], "The listed DeepSpeed OPs won't be precompiled. "
                             "JIT compilation at runtime is still possible", CUSTOM],
            'evoformer_gpu_arch': [None, "The GPU architecture to use for Evoformer OPs."
                                   "If not specified, the lowest from cuda_compute_capabilities will be used, "
                                   "which might cause reduced performance on newer GPUs.", CUSTOM],
        })

    def set_cache_dirs(self):
        # Don't write to $HOME
        triton_dir = tempfile.mkdtemp(suffix='-tt_home')
        env.setvar('TRITON_HOME', triton_dir)
        env.setvar('TRITON_CACHE_DIR', os.path.join(triton_dir, 'cache'))

    def configure_step(self):
        """Set up DeepSpeed config"""
        dep_names = self.cfg.dependency_names()
        if 'PyTorch' not in dep_names:
            raise EasyBuildError('PyTorch is required as a dependency')

        env.setvar('DS_ENABLE_NINJA', '1' if get_software_root('Ninja') else '0')
        if 'CUDA' in dep_names:
            env.setvar('DS_ACCELERATOR', 'cuda')
            # https://github.com/microsoft/DeepSpeed/issues/3358
            env.setvar('NVCC_PREPEND_FLAGS', '--forward-unknown-opts')

            cuda_ccs = self.cfg.get_cuda_cc_template_value('cuda_cc_semicolon_sep')
            if cuda_ccs:
                env.setvar('TORCH_CUDA_ARCH_LIST', cuda_ccs)
                evoformer_gpu_arch = self.cfg.get('evoformer_gpu_arch')
                if not evoformer_gpu_arch:
                    evoformer_gpu_arch = cuda_ccs.split(';')[0]
                env.setvar('DS_EVOFORMER_GPU_ARCH', evoformer_gpu_arch)

        # By default prebuild all ops with a few exceptions
        # http://www.deepspeed.ai/tutorials/advanced-install/#pre-install-deepspeed-ops
        # > DeepSpeed will only install any ops that are compatible with your machine
        env.setvar('DS_BUILD_OPS', '1')

        # Some may be problematic for different reasons, these are specified in the easyconfig
        if not any(op in self.cfg['jit_only_ops'] for op in ('TRANSFORMER', 'STOCHASTIC_TRANSFORMER')):
            # See https://github.com/deepspeedai/DeepSpeed/issues/949
            print_warning('The "Transformer" and "Stochastic Transformer" OPs cannot be precompiled at the same time. '
                          'Skipping the stochastic transformer OP.')
            self.cfg.update('jit_only_ops', 'STOCHASTIC_TRANSFORMER')
        for opt in self.cfg['jit_only_ops']:
            env.setvar('DS_BUILD_{}'.format(opt), '0')

        self.cfg.update('installopts', "--config-setting='--build-option=build_ext'")
        self.cfg.update('installopts', "--config-setting='--build-option=-j%(parallel)s'")
        self.set_cache_dirs()
        super().configure_step()

    def sanity_check_step(self):
        '''Custom sanity check for DeepSpeed.'''
        self.set_cache_dirs()
        custom_paths = {
            'files': ['bin/deepspeed'],
            'dirs': [],
        }
        custom_commands = [
            'deepspeed --help',
            'python -m deepspeed.env_report',
            f'[ "$(ds_report | grep -c "\\[NO\\]")" -eq "{len(self.cfg["jit_only_ops"])}" ]'
        ]
        return super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
