##
# Copyright 2009-2019 Ghent University
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
from easybuild.tools.modules import get_software_version


class EB_MotionCor2(EasyBlock):
    """
    Support for installing MotionCor2
     - creates wrapper that loads the correct version of CUDA before
     - running the actual binary
    """

    def __init__(self, *args, **kwargs):
        super(EB_MotionCor2, self).__init__(*args, **kwargs)

    def extract_step(self):
        """Extract the files"""
        super(EB_MotionCor2, self).extract_step()

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

        cuda_mod_name = ""
        for dep in self.toolchain.dependencies:
            if dep['name'] == 'CUDA':
                cuda_mod_name = dep['short_mod_name']
                cuda_name = cuda_mod_name.split('/')[0]
                break

        if cuda_mod_name == "":
            raise EasyBuildError("CUDA must be a direct dependency of MotionCor2")
        cuda_ver = get_software_version('CUDA')
        self.motioncor2_bin = 'MotionCor2_%s-Cuda%s' % (self.version, "".join(cuda_ver.split('.')[:2]))

        src_mc2_bin = os.path.join(self.builddir, self.motioncor2_bin)
        if not os.path.exists(src_mc2_bin):
            raise EasyBuildError("Specified CUDA version has no corresponding MotionCor2 binary")

        bindir = os.path.join(self.installdir, 'bin')
        mkdir(bindir)

        dst_mc2_bin = os.path.join(bindir, self.motioncor2_bin)
        copy_file(src_mc2_bin, dst_mc2_bin)
        adjust_permissions(dst_mc2_bin, stat.S_IRWXU, add=True)

        # Install a wrapper that loads CUDA before starting the binary
        wrapper = os.path.join(bindir, 'motioncor2')
        txt = '\n'.join([
            '#!/bin/bash',
            '',
            '# Wrapper for MotionCor2 binary that loads the required',
            '# version of CUDA',
            'module unload %s' % cuda_name,
            'module add %s' % cuda_mod_name,
            'exec %s "$@"' % dst_mc2_bin
        ])
        write_file(wrapper, txt)
        adjust_permissions(wrapper, stat.S_IRWXU, add=True)

    def sanity_check_step(self):
        """
        Custom sanity check for MotionCor2
        """

        custom_paths = {
                        'files': [os.path.join('bin', x) for x in ['motioncor2', self.motioncor2_bin]],
                        'dirs': []
                       }

        super(EB_MotionCor2, self).sanity_check_step(custom_paths)
