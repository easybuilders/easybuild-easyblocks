##
# Copyright 2009-2023 Ghent University
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
"""

from distutils.version import LooseVersion
import os

from easybuild.easyblocks.generic.intelbase import IntelBase, ACTIVATION_NAME_2012, LICENSE_FILE_NAME_2012
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.systemtools import get_platform_name
from easybuild.tools.systemtools import get_shared_lib_ext

class EB_ipp(IntelBase):
    """
    Support for installing Intel Integrated Performance Primitives library
    """
    def prepare_step(self, *args, **kwargs):
        """Since oneAPI there is no license required."""
        if LooseVersion(self.version) >= LooseVersion('2021'):
            kwargs['requires_runtime_license'] = False
        super(EB_ipp, self).prepare_step(*args, **kwargs)

    def make_installdir(self):
        """Do not create installation directory, install script handles that already."""
        if LooseVersion(self.version) >= LooseVersion('2021'):
            super(EB_ipp, self).make_installdir(dontcreate=True)

    def install_step(self):
        """
        Actual installation
        - create silent cfg file
        - execute command
        """

        platform_name = get_platform_name()
        if platform_name.startswith('x86_64'):
            self.arch = "intel64"
        elif platform_name.startswith('i386') or platform_name.startswith('i686'):
            self.arch = 'ia32'
        else:
            raise EasyBuildError("Failed to determine system architecture based on %s", platform_name)

        silent_cfg_names_map = None
        silent_cfg_extras = None

        if LooseVersion(self.version) < LooseVersion('8.0'):
            silent_cfg_names_map = {
                'activation_name': ACTIVATION_NAME_2012,
                'license_file_name': LICENSE_FILE_NAME_2012,
            }

        # in case of IPP 9.x, we have to specify ARCH_SELECTED in silent.cfg
        if LooseVersion(self.version) >= LooseVersion('9.0') \
           and LooseVersion(self.version) < LooseVersion('2021'):
            silent_cfg_extras = {
                'ARCH_SELECTED': self.arch.upper()
            }

        """If installing from OneAPI, install only Intel IPP component"""
        if LooseVersion(self.version) >= LooseVersion('2021'):
            self.install_components = ['intel.oneapi.lin.ipp.devel']

        super(EB_ipp, self).install_step(silent_cfg_names_map=silent_cfg_names_map, silent_cfg_extras=silent_cfg_extras)

    def sanity_check_step(self):
        """Custom sanity check paths for IPP."""
        shlib_ext = get_shared_lib_ext()

        if LooseVersion(self.version) < LooseVersion('2021'):
            dirs = [os.path.join('ipp', x) for x in ['bin', 'include', os.path.join('tools', 'intel64')]]
        else:
            dirs = [os.path.join('ipp', self.version, x)
                    for x in ['include', os.path.join('tools', 'intel64')]]

        if LooseVersion(self.version) < LooseVersion('8.0'):
            dirs.extend([
                os.path.join('compiler', 'lib', 'intel64'),
                os.path.join('ipp', 'interfaces', 'data-compression'),
            ])
        elif LooseVersion(self.version) < LooseVersion('9.0'):
            dirs.extend([
                os.path.join('composerxe', 'lib', 'intel64'),
            ])

        ipp_libs = ['cc', 'ch', 'core', 'cv', 'dc', 'i', 's', 'vm']
        if LooseVersion(self.version) < LooseVersion('9.0'):
            ipp_libs.extend(['ac', 'di', 'j', 'm', 'r', 'sc', 'vc'])

        if LooseVersion(self.version) < LooseVersion('2021'):
            custom_paths_version = '.'
        else:
            custom_paths_version = self.version

        custom_paths = {
            'files': [
                os.path.join('ipp', custom_paths_version, 'lib', 'intel64', 'libipp%s') % y for x in ipp_libs
                for y in ['%s.a' % x, '%s.%s' % (x, shlib_ext)]
            ],
            'dirs': dirs,
        }

        super(EB_ipp, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """
        A dictionary of possible directories to look for
        """
        guesses = super(EB_ipp, self).make_module_req_guess()

        if LooseVersion(self.version) >= LooseVersion('2021'):
            lib_path = [os.path.join('ipp', self.version, 'lib', self.arch), \
               os.path.join('compiler', '*', 'linux', 'lib'), \
               os.path.join('compiler', '*', 'linux', 'compiler', 'lib', 'intel64_lin')]
            include_path = os.path.join('ipp', self.version, 'include')
        else:
            if LooseVersion(self.version) >= LooseVersion('9.0'):
                lib_path = [os.path.join('ipp', 'lib', self.arch), os.path.join('lib', self.arch)]
                include_path = os.path.join('ipp', 'include')

        guesses.update({
            'LD_LIBRARY_PATH': lib_path,
            'LIBRARY_PATH': lib_path,
            'CPATH': [include_path],
            'INCLUDE': [include_path],
        })

        return guesses
