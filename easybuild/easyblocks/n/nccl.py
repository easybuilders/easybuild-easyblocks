##
# Copyright 2021-2025 Ghent University
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
EasyBuild support for building NCCL, implemented as an easyblock

@author: Simon Branford (University of Birmingham)
@author: Lara Peeters (Gent University)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.config import build_option
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.tools.filetools import copy_file


class EB_NCCL(ConfigureMake):
    """Support for building NCCL."""

    def configure_step(self):
        """NCCL has no configure step"""
        pass

    def build_step(self):
        """Build NCCL"""
        # NCCL builds for all supported CUDA compute capabilities by default
        # If cuda_compute_capabilities is specified then we override this with the selected options

        # list of CUDA compute capabilities to use can be specifed in three ways (where 3 overrules 2 overrules 1):
        # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
        # (2) via the EasyBuild environment variable EASYBUILD_CUDA_COMPUTE_CAPABILITIES;
        # (3) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
        cuda_cc = build_option('cuda_compute_capabilities') or self.cfg['cuda_compute_capabilities']

        nvcc_gencode = []
        for cc in cuda_cc:
            add = cc.replace('.', '')
            nvcc_gencode.append('-gencode=arch=compute_%s,code=sm_%s' % (add, add))

        if nvcc_gencode:
            self.cfg.update('buildopts', 'NVCC_GENCODE="%s"' % ' '.join(nvcc_gencode))

        # Set PREFIX to correctly generate nccl.pc
        self.cfg.update('buildopts', "PREFIX=%s" % self.installdir)

        super(EB_NCCL, self).build_step()

    def install_step(self):
        """Install NCCL"""
        self.cfg.update('installopts', "PREFIX=%s" % self.installdir)

        copy_file(os.path.join(self.cfg['start_dir'], 'LICENSE.txt'), os.path.join(self.installdir, 'LICENSE.txt'))

        super(EB_NCCL, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check paths for NCCL"""
        custom_paths = {
            'files': ['include/nccl.h', 'lib/libnccl.%s' % get_shared_lib_ext(), 'lib/libnccl_static.a',
                      'lib/pkgconfig/nccl.pc'],
            'dirs': [],
        }

        super(EB_NCCL, self).sanity_check_step(custom_paths=custom_paths)
