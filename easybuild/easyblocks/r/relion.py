##
# Copyright 2009-2022 Ghent University
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
EasyBuild support for building and installing RELION, implemented as an easyblock

@author: Jasper Grimm (University of York)
"""
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.modules import get_software_root
from easybuild.tools.config import build_option
from easybuild.tools.build_log import EasyBuildError, print_warning

class EB_RELION(CMakeMake):
    """Support for building/installing RELION."""

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'cuda_texture': [False, "Enable cuda texture", CUSTOM],
            'default_cuda_capability': [None, "Default CUDA capabilitity for building RELION, e.g. '8.6'", CUSTOM],
            'doubleprec_cpu': [True, "Enable double precision (CPU)", CUSTOM],
            'doubleprec_gpu': [False, "Enable double precision (GPU)", CUSTOM],
            'disable_gui': [False, "Build without GUI", CUSTOM],
            'use_mkl': [True, "Use MKL for FFT (if MKL is a depencency)", CUSTOM],
        })
        return extra_vars

    def configure_step(self, *args, **kwargs):
        """Custom configure step for RELION"""
        
        # configure some default options
        self.cfg.update('configopts', '-DCMAKE_SHARED_LINKER="$LIBS"')
        self.cfg.update('configopts', '-DMPI_INCLUDE_PATH="$MPI_INC_DIR"')

        if self.cfg['disable_gui'] or not get_software_root('FLTK'):
            self.cfg.update('configopts', '-DGUI=OFF')

        if get_software_root('MKL') and self.cfg['use_mkl']:
            self.cfg.update('configopts', '-DMKLFFT=ON')

        # check if CUDA is present
        if get_software_root('CUDA'):
            self.cfg.update('configopts', '-DCUDA=ON')
            
            # check cuda_compute_capabilities
            cuda_cc = self.cfg['cuda_compute_capabilities'] or build_option('cuda_compute_capabilities') or []
            if not cuda_cc:
                raise EasyBuildError("Can't build RELION with CUDA support without"
                                     " specifying 'cuda-compute-capabilities'")
            self.cfg.update('configopts', '-DCUDA_ARCH="%s"' % ' '.join(cuda_cc))

            # check default_cuda_capability
            default_cc = self.cfg['default_cuda_capability'] or min(cuda_cc)
            if not self.cfg['default_cuda_capability']:
                print_warning("No default CUDA capability defined! "
                              "Using '%s' taken as minimum from 'cuda_compute_capabilities'" % default_cc)
            self.cfg.update('configopts', '-DDEFAULT_CUDA_ARCH="%s"' % default_cc)

            if self.cfg['cuda_texture']:
                self.cfg.update('configopts', '-DCUDA_TEXTURE=ON')

            if not self.cfg['doubleprec_cpu']:
                self.cfg.update('configopts', '-DDoublePrec_CPU=OFF')
            
            if self.cfg['doubleprec_gpu']:
                self.log.warning("Enabling GPU double precision is not recommnded")
                self.cfg.update('configopts', '-DDoublePrec_ACC=ON')
            else:
                self.cfg.update('configopts', '-DDoublePrec_ACC=OFF')

        else:
            # CPU build
            self.cfg.update('configopts', '-DALTCPU=ON')
            
            if self.cfg['doubleprec_cpu']:
                self.cfg.update('configopts', '-DDoublePrec_CPU=ON')
            else:
                self.cfg.update('configopts', '-DDoublePrec_CPU=OFF')

        super(EB_RELION, self).configure_step(*args, **kwargs)

    def install_step(self, *args, **kwargs):
        """Custom install step for RELION"""
        self.cfg['install_cmd'] = 'make -j %s install' % self.cfg['parallel']

        super(EB_RELION, self).install_step(*args, **kwargs)

    def sanity_check_step(self):
        """Custom sanity check step for RELION."""
        custom_paths = {
            'files': ['bin/relion%s' % x for x in ['', '_autopick', '_batchrun', '_batchrun_mpi']],
            'dirs': [],
        }

        custom_commands = ['relion --help', 'relion --version']

        super(EB_RELION, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
