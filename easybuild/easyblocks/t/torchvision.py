##
# Copyright 2021-2024 Ghent University
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
@author: Kenneth Hoste (HPC-UGent)
"""
import os

from easybuild.easyblocks.generic.pythonpackage import PythonPackage, det_pylibdir
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_version, get_software_root
import easybuild.tools.environment as env


class EB_torchvision(PythonPackage):
    """Support for building/installing TorchVison."""

    @staticmethod
    def extra_options():
        """Change some defaults for easyconfig parameters."""
        extra_vars = PythonPackage.extra_options()
        extra_vars['use_pip'][0] = True
        extra_vars['download_dep_fail'][0] = True
        extra_vars['sanity_pip_check'][0] = True
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize torchvision easyblock."""
        super(EB_torchvision, self).__init__(*args, **kwargs)

        dep_names = set(dep['name'] for dep in self.cfg.dependencies())

        # require that PyTorch is listed as dependency
        if 'PyTorch' not in dep_names:
            raise EasyBuildError('PyTorch not found as a dependency')

        # enable building with GPU support if CUDA is included as dependency
        if 'CUDA' in dep_names:
            self.with_cuda = True
        else:
            self.with_cuda = False

    def configure_step(self):
        """Set up torchvision config"""

        # Note: Those can be overwritten by e.g. preinstallopts
        env.setvar('BUILD_VERSION', self.version)
        env.setvar('PYTORCH_VERSION', get_software_version('PyTorch'))

        if self.with_cuda:
            # make sure that torchvision is installed with CUDA support by setting $FORCE_CUDA
            env.setvar('FORCE_CUDA', '1')
            # specify CUDA compute capabilities via $TORCH_CUDA_ARCH_LIST
            cuda_cc = self.cfg['cuda_compute_capabilities'] or build_option('cuda_compute_capabilities')
            if cuda_cc:
                env.setvar('TORCH_CUDA_ARCH_LIST', ';'.join(cuda_cc))

        libjpeg_root = get_software_root('libjpeg-turbo')
        if libjpeg_root and 'TORCHVISION_INCLUDE' not in self.cfg['preinstallopts']:
            env.setvar('TORCHVISION_INCLUDE', os.path.join(libjpeg_root, 'include'))

        super(EB_torchvision, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for torchvision."""

        # load module early ourselves rather than letting parent sanity_check_step method do so,
        # so the correct 'python' command is used to by det_pylibdir() below;
        if hasattr(self, 'sanity_check_module_loaded') and not self.sanity_check_module_loaded:
            self.fake_mod_data = self.sanity_check_load_module(extension=self.is_extension)

        custom_commands = []
        custom_paths = {
            'files': [],
            'dirs': [det_pylibdir()],
        }

        # check whether torchvision was indeed built with CUDA support,
        # cfr. https://discuss.pytorch.org/t/notimplementederror-could-not-run-torchvision-nms-with-arguments-from-\
        #      the-cuda-backend-this-could-be-because-the-operator-doesnt-exist-for-this-backend/132352/4
        if self.with_cuda:
            python_code = '\n'.join([
                "import torch, torchvision",
                "if torch.cuda.device_count():",
                "    boxes = torch.tensor([[0., 1., 2., 3.]]).to('cuda')",
                "    scores = torch.randn(1).to('cuda')",
                "    print(torchvision.ops.nms(boxes, scores, 0.5))",
            ])
            custom_commands.append('python -s -c "%s"' % python_code)

        if get_software_root('libjpeg-turbo'):
            # check if torchvision was built with libjpeg support
            # if not, will show error "RuntimeError: encode_jpeg: torchvision not compiled with libjpeg support"
            python_code = '\n'.join([
                "import torch, torchvision",
                "image_tensor = torch.zeros(1, 1, 1, dtype=torch.uint8)",
                "print(torchvision.io.image.encode_jpeg(image_tensor))",
            ])
            custom_commands.append('python -s -c "%s"' % python_code)

        return super(EB_torchvision, self).sanity_check_step(custom_commands=custom_commands, custom_paths=custom_paths)
