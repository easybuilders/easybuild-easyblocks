# -*- coding: utf-8 -*-
##
# Copyright 2018-2025 Ghent University
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
EasyBuild support for installing Sentaurus

@author: Mikael Öhman (Chalmers University of Techonology)
"""

import glob
import os
import stat

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import create_unused_dir, adjust_permissions, write_file
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.build_log import EasyBuildError


INSTALL_TEMPLATE = """
SourceDir: {0}
SiteId: {1}
SiteAdmin: EasyBuild
SiteContact: easybuild@(none)
PRODUCTS: sentaurus
RELEASES: {2}
PLATFORMS: common linux64
#####
sentaurus,{2} {{
DESCRIPTION: TCAD Sentaurus
TYPE:
POSTINST: tcad/{2}/install_sentaurus
EULA: 1
ESTPLATFORMS: linux64 common
VERSION: {2}
PLATFORMS:
TARGETDIR: {3}
}}
"""


class EB_Sentaurus(Binary):
    """
    Support for installing Sentaurus
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to MesonNinja."""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'siteid': [None, "site id from your Synopsys license key certificate", CUSTOM],
            'license_server': [None, "license server as 'port@hostname'", CUSTOM],
        })
        return extra_vars

    def build_step(self):
        """
        Unpack sources with synopsys "installer".
        """
        # Batch installer accepts the EULA, must tell user:
        synopsys_eula = 'See license of the Synopsys product you are installing.'
        self.check_accepted_eula(name='Synopsys', more_info=synopsys_eula)

        # Check early to inform user it is required for license
        self.siteid = self.cfg['siteid'] or os.getenv('EB_SENTAURUS_SITEID')
        if self.siteid is None:
            raise EasyBuildError("siteid is required but not specified")

        self.stagingdir = create_unused_dir(self.builddir, 'staging')

        unpacker = glob.glob('SynopsysInstaller*.run')
        if len(unpacker) != 1:
            print('Did not find exactly one installer, unknown how to proceed')
        unpacker = unpacker[0]
        adjust_permissions(unpacker, stat.S_IXUSR)
        run_shell_cmd(f'./{unpacker} -dir staging')

    def install_step(self):
        """
        Install step
        """
        install_template = INSTALL_TEMPLATE.format(
            self.builddir,
            self.siteid,
            self.version,
            self.installdir,
        )
        write_file('install_template.txt', install_template)
        run_shell_cmd(f'{self.stagingdir}/batch_installer -config install_template.txt -target {self.installdir}')

    def make_module_extra(self, *args, **kwargs):
        """
        Add license variable to Sentaurus module
        """
        mod = super().make_module_extra()
        mod += self.module_generator.append_paths('PATH', 'sentaurus/current/bin/')

        license_server = self.cfg['license_server'] or os.getenv('EB_SENTAURUS_LICENSE_SERVER', None)
        if license_server:
            mod += self.module_generator.set_environment('SNPSLMD_LICENSE_FILE', license_server)

        return mod

    def sanity_check_step(self):
        """Custom sanity check for Sentaurus."""
        custom_paths = {
            'files': [f'sentaurus/current/bin/{x}' for x in ['sse', 'sprocess', 'sdevice', 'svisual']],
            'dirs': [],
        }
        super(Binary, self).sanity_check_step(custom_paths=custom_paths)
