##
# Copyright 2012-2024 Ghent University
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
EasyBlock for installing code-server, implemented as an easyblock
@author: Alan O'Cais (Juelich Supercomputing Centre)
"""

from easybuild.framework.easyblock import EasyBlock
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.systemtools import AARCH64, X86_64, get_cpu_architecture


class EB_code_minus_server(PackedBinary, EasyBlock):
    """
    Support for installing code-server.
    """

    def __init__(self, *args, **kwargs):
        """ Init the easyblock adding a new mapped_arch template var """
        myarch = get_cpu_architecture()
        if myarch == X86_64:
            self.mapped_arch = 'amd64'
        elif myarch == AARCH64:
            self.mapped_arch = 'arm64'
        else:
            raise EasyBuildError("Architecture %s is not supported for code-server on EasyBuild", myarch)

        super(EB_code_minus_server, self).__init__(*args, **kwargs)

        self.cfg.template_values['mapped_arch'] = self.mapped_arch
        self.cfg.generate_template_values()

    def install_step(self):
        """Custom install step for code-server."""
        install_cmd = self.cfg.get('install_cmd', None)
        if install_cmd is None:
            cmd = 'cp -a code-server-%s-linux-%s/* %s' % (self.version, self.mapped_arch, self.installdir)
            # set the install command to a default
            self.log.info("For %s, using default installation command '%s'..." % (self.name, cmd))
            self.cfg['install_cmd'] = cmd
        super(EB_code_minus_server, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for code-server."""
        custom_paths = {
            'files': ['bin/code-server'],
            'dirs': ['bin', 'lib', 'node_modules'],
        }

        custom_commands = ["code-server --help"]

        res = super(EB_code_minus_server, self).sanity_check_step(
            custom_paths=custom_paths,
            custom_commands=custom_commands
        )

        return res

    def make_module_extra(self):
        """Add the default directories to the PATH."""
        txt = EasyBlock.make_module_extra(self)
        return txt
