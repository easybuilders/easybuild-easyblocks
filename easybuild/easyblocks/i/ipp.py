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
EasyBuild support for installing the Intel Performance Primitives (IPP) library, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Lumir Jasiok (IT4Innovations)
@author: Damian Alvarez (Forschungszentrum Juelich GmbH)
@author: Jan Andre Reuter (Forschungszentrum Juelich GmbH)
"""

from easybuild.tools import LooseVersion
import os

from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS
from easybuild.tools.systemtools import get_platform_name
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_ipp(IntelBase):
    """
    Support for installing Intel Integrated Performance Primitives library
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if LooseVersion(self.version) < '2021':
            raise EasyBuildError(
                f"Version {self.version} of {self.name} is unsupported. Mininum supported version is 2021.0."
            )

        platform_name = get_platform_name()
        if platform_name.startswith('x86_64'):
            self.arch = "intel64"
        elif platform_name.startswith('i386') or platform_name.startswith('i686'):
            if LooseVersion(self.version) >= '2022.0':
                raise EasyBuildError(f"ipp is not supported on {platform_name} starting with 2022.0.0")
            self.arch = 'ia32'
        else:
            raise EasyBuildError("Failed to determine system architecture based on %s", platform_name)

    def prepare_step(self, *args, **kwargs):
        kwargs['requires_runtime_license'] = False
        super().prepare_step(*args, **kwargs)

    def install_step(self):
        """
        Actual installation
        - create silent cfg file
        - execute command
        """
        silent_cfg_names_map = None
        silent_cfg_extras = {
            'ARCH_SELECTED': self.arch.upper()
        }

        super(EB_ipp, self).install_step(silent_cfg_names_map=silent_cfg_names_map, silent_cfg_extras=silent_cfg_extras)

    def sanity_check_step(self):
        """Custom sanity check paths for IPP."""
        shlib_ext = get_shared_lib_ext()

        dirs = [os.path.join('ipp', x) for x in ['bin', 'include', os.path.join('tools', 'intel64')]]
        ipp_libs = ['cc', 'ch', 'core', 'cv', 'dc', 'i', 's', 'vm']

        custom_paths = {
            'files': [
                os.path.join('ipp', 'lib', 'intel64', 'libipp%s') % y for x in ipp_libs
                for y in ['%s.a' % x, '%s.%s' % (x, shlib_ext)]
            ],
            'dirs': dirs,
        }

        super(EB_ipp, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_step(self, *args, **kwargs):
        """
        Set paths for module load environment based on the actual installation files
        """
        major_minor_version = '.'.join(self.version.split('.')[:2])
        if LooseVersion(major_minor_version) > '2022.0':
            include_path = os.path.join('ipp', major_minor_version, 'include')
            lib_path = os.path.join('ipp', major_minor_version, 'lib')
            cmake_prefix_path = os.path.join('ipp', major_minor_version)
            cmake_module_path = os.path.join('ipp', major_minor_version, 'lib', 'cmake')
        else:
            include_path = os.path.join('ipp', self.version, 'include')
            lib_path = os.path.join('ipp', self.version, 'lib', self.arch)
            cmake_prefix_path = os.path.join('ipp', self.version)
            cmake_module_path = os.path.join('ipp', self.version, 'lib', 'cmake')

        self.module_load_environment.PATH = []
        self.module_load_environment.LD_LIBRARY_PATH = [lib_path]
        self.module_load_environment.LIBRARY_PATH = self.module_load_environment.LD_LIBRARY_PATH
        self.module_load_environment.CMAKE_PREFIX_PATH = os.path.join(cmake_prefix_path)
        self.module_load_environment.CMAKE_MODULE_PATH = os.path.join(cmake_module_path)
        self.module_load_environment.set_alias_vars(MODULE_LOAD_ENV_HEADERS, include_path)

        return super().make_module_step(*args, **kwargs)

    def make_module_extra(self):
        """Overwritten from Application to add extra txt"""
        major_minor_version = '.'.join(self.version.split('.')[:2])

        txt = super().make_module_extra()

        ipproot = os.path.join(self.installdir, 'ipp', major_minor_version)
        txt += self.module_generator.set_environment('IPPROOT', ipproot)
        txt += self.module_generator.set_environment('IPP_TARGET_ARCH', self.arch)

        return txt
