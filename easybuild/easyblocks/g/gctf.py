##
# Copyright 2019-2024 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (https://ugent.be/hpc/en),
# with support of Ghent University (https://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (https://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (https://www.ewi-vlaanderen.be/en).
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
# along with EasyBuild.  If not, see <https://www.gnu.org/licenses/>.
##
"""
EasyBuild support for building and installing Gctf, implemented as an easyblock

@author: Ake Sandgren, (HPC2N, Umea University)
"""

import os
import stat

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_file, mkdir
from easybuild.tools.filetools import symlink, write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools import LooseVersion


class EB_Gctf(EasyBlock):
    """
    Support for installing Gctf
     - creates wrapper that loads the correct version of CUDA before
     - running the actual binary
    """

    def __init__(self, *args, **kwargs):
        """Constructor of Gctf easyblock."""
        super(EB_Gctf, self).__init__(*args, **kwargs)

        self.cuda_mod_name, self.cuda_name = None, None
        self.gctf_bin = None
        self.cfg['unpack_options'] = '--strip-components=1'

    def prepare_step(self, *args, **kwargs):
        """
        Determine name of Gctf binary to install based on CUDA version.
        """
        super(EB_Gctf, self).prepare_step(*args, **kwargs)

        if not get_software_root('CUDA'):
            raise EasyBuildError("CUDA must be a direct (build)dependency of Gctf")

        for dep in self.cfg.dependencies():
            if dep['name'] == 'CUDA':
                self.cuda_mod_name = dep['short_mod_name']
                self.cuda_name = os.path.dirname(self.cuda_mod_name)
                cuda_ver = dep['version']
                cuda_short_ver = ".".join(cuda_ver.split('.')[:2])
                sm_ver = 20
                if LooseVersion(cuda_ver) >= LooseVersion('8.0'):
                    sm_ver = 30

                self.gctf_bin = 'Gctf-v%s_sm_%s_cu%s_x86_64' % (self.version, sm_ver, cuda_short_ver)
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

        src_gctf_bin = os.path.join(self.builddir, 'bin', self.gctf_bin)
        if not os.path.exists(src_gctf_bin):
            raise EasyBuildError("Specified CUDA version has no corresponding Gctf binary")

        bindir = os.path.join(self.installdir, 'bin')
        mkdir(bindir)

        dst_gctf_bin = os.path.join(bindir, self.gctf_bin)
        copy_file(src_gctf_bin, dst_gctf_bin)

        exe_perms = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        read_perms = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        perms = read_perms | exe_perms

        adjust_permissions(dst_gctf_bin, perms, add=True)

        # Install a wrapper that loads CUDA before starting the binary
        wrapper = os.path.join(bindir, 'Gctf')
        txt = '\n'.join([
            '#!/bin/bash',
            '',
            '# Wrapper for Gctf binary that loads the required',
            '# version of CUDA',
            'module unload %s' % self.cuda_name,
            'module add %s' % self.cuda_mod_name,
            'exec %s "$@"' % dst_gctf_bin
        ])
        write_file(wrapper, txt)
        adjust_permissions(wrapper, exe_perms, add=True)
        symlink('Gctf', os.path.join(bindir, 'gctf'), use_abspath_source=False)

    def sanity_check_step(self):
        """
        Custom sanity check for Gctf
        """

        custom_paths = {
            'files': [os.path.join('bin', x) for x in ['Gctf', self.gctf_bin]],
            'dirs': []
        }

        super(EB_Gctf, self).sanity_check_step(custom_paths)
