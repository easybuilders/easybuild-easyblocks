##
# Copyright 2020 NVIDIA
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
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
EasyBuild support for XALT, implemented as an easyblock
@author: Scott McMillan (NVIDIA)
"""
import os
import re

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import check_os_dependency, get_shared_lib_ext


class EB_XALT(ConfigureMake):
    """Support for building and installing XALT."""

    @staticmethod
    def extra_options():
        extra_vars = {
            'config_py': [None, "XALT site filter file", MANDATORY],
            'syshost': ['hardcode:cluster', "System name", CUSTOM],
            'transmission': ['syslog', "", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def configure_step(self):
        """Custom configuration step for XALT."""

        # Remove the subdir from the install prefix to resolve the
        # following configure error.  XALT automatically creates a
        # versioned directory hierarchy.
        #
        #    Do not install XALT with 2.7.27 as part of the
        #    prefix.  It will lead to many many problems with future
        #    installs of XALT
        #
        #    Executables built with the current version of XALT
        #    will not work with future installs of XALT!!!
        #
        #    If you feel that you know better than the developer
        #    of XALT then you can configure XALT with the configure
        #    --with-IrefuseToInstallXALTCorrectly=yes and set the prefix
        #    to include the version
        self.installdir = os.path.normpath(re.sub(self.install_subdir, '', self.installdir))

        # XALT site filter config file is mandatory
        if not self.cfg['config_py']:
            raise EasyBuildError('XALT site filter config must be specified. '
                                 'Use "--try-amend=config_py=<file>"')
        self.cfg.update('configopts', '--with-config=%s' % self.cfg['config_py'])

        if self.cfg['syshost']:
            self.cfg.update('configopts', '--with-syshostConfig=%s' % self.cfg['syshost'])

        if self.cfg['transmission']:
            self.cfg.update('configopts', '--with-transmission=%s' % self.cfg['transmission'])

        super(EB_XALT, self).configure_step()

        # Reassemble the default install path
        self.installdir = os.path.join(self.installdir, self.install_subdir)

    def make_module_req_guess(self):
        """ Limit default guess paths """
        return {'COMPILER_PATH': 'bin',
                'PATH': 'bin'}
