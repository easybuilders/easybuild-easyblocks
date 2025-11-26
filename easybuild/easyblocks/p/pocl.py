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
EasyBuild support for pocl, implemented as an easyblock

@author: Petr Král (INUITS)
@author: Kenneth Hoste (Ghent University)
"""
import os

from easybuild.easyblocks.generic.cmakeninja import CMakeNinja
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_pocl(CMakeNinja):
    """Support for building pocl."""

    def configure_step(self, *args, **kwargs):
        """
        Custom configure step for pocl

        Sets come custom configure options to use provided LLVM dependency,
        disable attempt to find an ICD loader, always build libOpenCL.so

        Tries to configure without setting LLC_HOST_CPU option to 'native',
        but if that fails, uses it to avoid host CPU auto-detection (which may fail on recent CPUs)
        """

        # disable attempt to find an ICD loader
        self.cfg.update('configopts', '-DENABLE_ICD=0')

        self.cfg.update('configopts', '-DINSTALL_OPENCL_HEADERS=1')

        if get_software_root('CUDA'):
            self.cfg.update('configopts', '-DENABLE_CUDA=1')

        # make sure we use Clang provided as dependency
        clang_root = get_software_root('Clang')
        if clang_root:
            self.cfg.update('configopts', '-DWITH_LLVM_CONFIG=' + os.path.join(clang_root, 'bin', 'llvm-config'))
            self.cfg.update('configopts', '-DSTATIC_LLVM=ON')

        # avoid that failing CMake command is fatal, and that we obtain full result for cmake command being run
        orig_fail_on_error = kwargs.get('fail_on_error')
        orig_return_full_cmd_result = kwargs.get('return_full_cmd_result')
        kwargs['fail_on_error'] = False
        kwargs['return_full_cmd_result'] = True

        res = CMakeNinja.configure_step(self, *args, **kwargs)
        if res.exit_code == 0:
            return res.output
        else:
            # cleanup of options being passed to CMakeNinja.configure_step
            if orig_fail_on_error is None:
                del kwargs['fail_on_error']
            else:
                kwargs['fail_on_error'] = orig_fail_on_error

            if orig_return_full_cmd_result is None:
                del kwargs['return_full_cmd_result']
            else:
                kwargs['return_full_cmd_result'] = orig_return_full_cmd_result

            self.cfg.update('configopts', '-DLLC_HOST_CPU=native')
            return CMakeNinja.configure_step(self, *args, **kwargs)

    def sanity_check_step(self):
        """Custom sanity check for pocl."""

        shlib_ext = get_shared_lib_ext()

        custom_paths = {
            'files': [os.path.join('bin', 'poclcc'), os.path.join('lib', f'libOpenCL.{shlib_ext}')],
            'dirs': [os.path.join('include', 'CL'), os.path.join('lib', 'pkgconfig')],
        }

        custom_commands = ["poclcc -h"]

        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
