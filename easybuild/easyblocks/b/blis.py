##
# Copyright 2013-2025 Ghent University
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
EasyBuild support for BLIS and AOCL-BLAS, implemented as an easyblock

@author: Samuel Moors (Vrije Universiteit Brussel)
"""
import re

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_BLIS(ConfigureMake):
    """Support for building and installing BLIS and AOCL-BLAS."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters."""
        extra_vars = {
            'cpu_architecture': ['auto', 'CPU architecture (default is autodetect)', CUSTOM],
        }

        return ConfigureMake.extra_options(extra_vars)

    def configure_step(self):
        """Custom configopts."""

        if self.toolchain.options.get('openmp', None):
            self.cfg.update('configopts', '--enable-threading=openmp')

        self.cfg.update('configopts', f'--enable-cblas --enable-shared CC="$CC" {self.cfg["cpu_architecture"]}')

        output = super().configure_step()

        if self.cfg['cpu_architecture'] == 'auto':
            failed_detect_str = r'Unable to automatically detect hardware type'
            if re.search(failed_detect_str, output):
                raise EasyBuildError(failed_detect_str)

    def make_module_extra(self):
        """Extra environment variables."""
        mod = super().make_module_extra()
        mod += self.module_generator.prepend_paths(MODULE_LOAD_ENV_HEADERS, ['include/blis'])
        return mod

    def sanity_check_step(self):
        """Custom sanity check paths."""

        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': ['include/blis/cblas.h', 'include/blis/blis.h'],
            'dirs': [],
        }
        if self.name == 'BLIS':
            custom_paths['files'].extend(['lib/libblis.a', f'lib/libblis.{shlib_ext}'])
        elif self.name == 'AOCL-BLAS':
            custom_paths['files'].extend(['lib/libblis-mt.a', f'lib/libblis-mt.{shlib_ext}'])

        super().sanity_check_step(custom_paths=custom_paths)
