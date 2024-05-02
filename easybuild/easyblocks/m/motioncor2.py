##
# Copyright 2019-2024 Ghent University
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

import glob
import os
import stat

from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_file, mkdir, write_file
from easybuild.tools.modules import get_software_root


class EB_MotionCor2(PackedBinary):
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
        self.motioncor2_verstring = self.version
        if (LooseVersion(self.version) == LooseVersion("1.3.1")):
            self.motioncor2_verstring = "v%s" % self.version

    def prepare_step(self, *args, **kwargs):
        """
        Determine name of MotionCor2 binary to install based on CUDA version.
        """
        super(EB_MotionCor2, self).prepare_step(*args, **kwargs)

        if not get_software_root('CUDA') and not get_software_root('CUDAcore'):
            raise EasyBuildError("CUDA(core) must be a direct (build)dependency of MotionCor2")

        for dep in self.cfg.dependencies():
            if dep['name'] == 'CUDA' or dep['name'] == 'CUDAcore':
                self.cuda_mod_name = dep['short_mod_name']
                self.cuda_name = os.path.dirname(self.cuda_mod_name)
                cuda_ver = dep['version']
                cuda_short_ver = "".join(cuda_ver.split('.')[:2])
                if (LooseVersion(self.version) >= LooseVersion("1.4")):
                    self.motioncor2_bin = 'MotionCor2_%s_Cuda%s' % (self.motioncor2_verstring, cuda_short_ver)
                else:
                    self.motioncor2_bin = 'MotionCor2_%s-Cuda%s' % (self.motioncor2_verstring, cuda_short_ver)
                break

    def install_step(self):
        """
        Install binary and a wrapper that loads correct CUDA version.
        """

        # for versions < 1.4.0 and at least for version 1.4.2 the binary is directly in the builddir
        # for versions 1.4.0 and 1.4.4 the binary is in a subdirectory {self.name}_{self.version}
        if (LooseVersion(self.version) >= LooseVersion("1.4")):
            pattern1 = os.path.join(self.builddir, '%s*' % self.motioncor2_bin)
            pattern2 = os.path.join(self.builddir,
                                    '%s_%s' % (self.name, self.version),
                                    '%s*' % self.motioncor2_bin)
            matches = glob.glob(pattern1) + glob.glob(pattern2)

            if len(matches) == 1:
                src_mc2_bin = matches[0]
            else:
                raise EasyBuildError(
                    "Found multiple, or no, matching MotionCor2 binary named %s*" % self.motioncor2_bin
                )
        else:
            src_mc2_bin = os.path.join(self.builddir, self.motioncor2_bin)
        if not os.path.exists(src_mc2_bin):
            raise EasyBuildError(
                "Specified CUDA version has no corresponding MotionCor2 binary named %s" % self.motioncor2_bin
            )

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
