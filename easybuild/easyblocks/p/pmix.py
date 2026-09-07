##
# Copyright 2013-2026 Ghent University
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
EasyBuild support for building and installing PMIx, implemented as an easyblock

@author: Alexander Grund (TU Dresden)
"""

import re
from typing import Set

from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root_env_var_name

from easybuild.easyblocks.generic.configuremake import ConfigureMake


class EB_PMIx(ConfigureMake):
    """Support for building "Process Management for Exascale Environments": PMI Exascale (PMIx)"""

    def configure_step(self):
        """Set configure options for dependencies"""
        dependencies: Set[str] = self.cfg.dependency_names()

        if 'Autotools' in dependencies:
            preconfigopts = self.cfg.get('preconfigopts', '')
            if 'autogen' not in preconfigopts:
                self.cfg['preconfigopts'] = './autogen.pl && ' + preconfigopts

        # Vebose build
        self.cfg['buildopts'] = 'V=1 ' + self.cfg.get('buildopts', '')

        configopts: str = self.cfg['configopts']

        def has_option(option: str) -> bool:
            """Check if option is enabled or disabled"""
            prefixes = [f'--{p}-' for p in ('with', 'without', 'enable', 'disable')]
            opt_name = option
            for prefix in prefixes:
                if option.startswith(prefix):
                    opt_name = option[len(prefix):]
                    break
            return re.search(rf'({"|".join(prefixes)}){opt_name}\b', configopts)

        if 'hwloc' not in dependencies:
            raise EasyBuildError("'hwloc' must be used as a dependency")
        if 'libev' in dependencies and 'libevent' in dependencies:
            raise EasyBuildError("Cannot have both 'libevent' and 'libev' as dependencies")

        known_dependencies = [
            'hwloc',
            'libevent',
            'munge',
            'zlib',
        ]
        version = LooseVersion(self.version)

        if '4.0.0' <= version < '4.2.3' or '5' <= version < '5.0.5':
            known_dependencies.append('cxi')

        if '5.0.0' <= version < '5.0.5':
            known_dependencies.append('alps')

        if version < '4.2.6' or '5' <= version < '5.0.1':
            # Different option name
            known_dependencies.append(('plibltdl', 'libltdl'))
        else:
            known_dependencies.append('libltdl')

        if version < '5.0.10':
            known_dependencies.append('libev')
        else:
            known_dependencies.append(('zlibng', 'zlib-ng'))

        for dependency in known_dependencies:
            if isinstance(dependency, str):
                opt_name = dependency
            else:
                opt_name, dependency = dependency
            if has_option(opt_name):
                self.log.info('Not adding configure option for %s as it is already passed in `configopts`.', opt_name)
            else:
                if dependency in dependencies:
                    self.log.info('Enabling use of ' + dependency)
                    configopts += f' --with-{opt_name}="${get_software_root_env_var_name(dependency)}"'
                else:
                    self.log.info('Disabling use of %s which is not a dependency.', dependency)
                    configopts += f' --without-{opt_name}'

        for option in ('--enable-pmix-binaries', '--with-pic'):
            if not has_option(option):
                configopts += f' {option}'

        if not has_option('hwloc'):
            raise EasyBuildError("Missing required dependency: hwloc")
        if not has_option('libevent') and not has_option('libev'):
            raise EasyBuildError("Either libevent or libev is required.")

        self.cfg['configopts'] = configopts

        super().configure_step()

    def sanity_check_step(self):
        """Set (default) sanity check paths."""
        custom_paths = {
            'files': ['bin/pevent', 'bin/plookup', 'bin/pmix_info', 'bin/pps'],
            'dirs': ['etc', 'include', 'lib', 'share']
        }
        super().sanity_check_step(custom_paths=custom_paths)
