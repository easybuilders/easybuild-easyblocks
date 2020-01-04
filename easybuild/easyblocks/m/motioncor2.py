##
# Copyright 2019-2020 Ghent University
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
EasyBuild support for building and installing MotionCor2, implemented as an easyblock

@author: Ake Sandgren, (HPC2N, Umea University)
"""

import os
import stat

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_file, mkdir, write_file
from easybuild.tools.modules import get_software_root


class EB_MotionCor2(EasyBlock):
    """
    Support for installing MotionCor2
     - creates wrapper that loads the correct version of CUDA before
     - running the actual binary
    """

    def __init__(self, *args, **kwargs):
        """Constructor of MotionCor2 easyblock."""
        super(EB_MotionCor2, self).__init__(*args, **kwargs)

        self.cuda_mod_name, self.cuda_name = None, None
        self.motioncor2_bin = None

    def prepare_step(self, *args, **kwargs):
        """
        Determine name of MotionCor2 binary to install based on CUDA version.
        """
        super(EB_MotionCor2, self).prepare_step(*args, **kwargs)

        if not get_software_root('CUDA'):
            raise EasyBuildError("CUDA must be a direct (build)dependency of MotionCor2")

        for dep in self.cfg.dependencies():
            if dep['name'] == 'CUDA':
                self.cuda_mod_name = dep['short_mod_name']
                self.cuda_name = os.path.dirname(self.cuda_mod_name)
                cuda_ver = dep['version']
                cuda_short_ver = "".join(cuda_ver.split('.')[:2])
                self.motioncor2_bin = 'MotionCor2_%s-Cuda%s' % (self.version, cuda_short_ver)
                break

    def configure_step(self):
        """No configuration, this is binary software"""
        pass

    def build_step(self):
        """No compilation, this is binary software"""
        pass

    def install_step(self):
        """
        Install binary and a wrapper that loads correct CUDA version.
        """

        src_mc2_bin = os.path.join(self.builddir, self.motioncor2_bin)
        if not os.path.exists(src_mc2_bin):
            raise EasyBuildError("Specified CUDA version has no corresponding MotionCor2 binary")

        bindir = os.path.join(self.installdir, 'bin')
        mkdir(bindir)

        dst_mc2_bin = os.path.join(bindir, self.motioncor2_bin)
        copy_file(src_mc2_bin, dst_mc2_bin)

        exe_perms = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        read_perms = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        perms = read_perms | exe_perms

        adjust_permissions(dst_mc2_bin, perms, add=True)

        # Install a wrapper that loads CUDA before starting the binary
        wrapper = os.path.join(bindir, 'motioncor2')
        txt = '\n'.join([
            '#!/bin/bash',
            '',
            '# Wrapper for MotionCor2 binary that loads the required',
            '# version of CUDA',
            'module unload %s' % self.cuda_name,
            'module add %s' % self.cuda_mod_name,
            'exec %s "$@"' % dst_mc2_bin
        ])
        write_file(wrapper, txt)
        adjust_permissions(wrapper, exe_perms, add=True)

    def sanity_check_step(self):
        """
        Custom sanity check for MotionCor2
        """

        custom_paths = {
            'files': [os.path.join('bin', x) for x in ['motioncor2', self.motioncor2_bin]],
            'dirs': []
        }

        super(EB_MotionCor2, self).sanity_check_step(custom_paths)
