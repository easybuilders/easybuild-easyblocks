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
EasyBuild support for building NCCL, implemented as an easyblock

@author: Simon Branford (University of Birmingham)
"""
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.config import build_option


class EB_NCCL(ConfigureMake):
    """Support for building NCCL."""

    @staticmethod
    def extra_options():
        extra_vars = ConfigureMake.extra_options()
        extra_vars.update({
            'ptx': [[], 'List of strings of CUDA compute architectures for which PTX code is generated.', CUSTOM],
        })
        return extra_vars

    def configure_step(self):
        """NCCL has no configure step"""
        pass

    def build_step(self):
        """Build NCCL"""
        # NCCL builds for all supported CUDA compute capabilities by default
        # If cuda_compute_capabilities or ptx are specified then we override this with the selected options

        # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
        # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
        # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
        cuda_cc = build_option('cuda_compute_capabilities') or self.cfg['cuda_compute_capabilities']
        if cuda_cc or self.cfg['ptx']:
            nvcc_gencode = []
            for cc in cuda_cc:
                add = cc.replace('.', '')
                nvcc_gencode.append('-gencode=arch=compute_%s,code=sm_%s' % (add, add))
            for ptx in self.cfg['ptx']:
                add = ptx.replace('.', '')
                nvcc_gencode.append('-gencode=arch=compute_%s,code=compute_%s' % (add, add))
            self.cfg.update('buildopts', 'NVCC_GENCODE="%s"' % ' '.join(nvcc_gencode))

        super(EB_NCCL, self).build_step()

    def install_step(self):
        """Install NCCL"""
        self.cfg.update('installopts', "PREFIX=%s" % self.installdir)

        super(EB_NCCL, self).install_step()
