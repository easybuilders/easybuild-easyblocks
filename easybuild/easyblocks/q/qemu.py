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
EasyBuild support for installing QEMU

@author: Mikael Öhman
"""

from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, create_unused_dir, which
from easybuild.tools.run import run_shell_cmd

class EB_QEMU(MesonNinja):
    """
    Support for building and installing QEMU.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to MesonNinja."""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'targets': [[], "targets to build, empty means automatic", CUSTOM],
            'targets_exclude': [[], "targets to build, empty means automatic", CUSTOM],
        })
        return extra_vars


    def configure_step(self, cmd_prefix=''):
        """
        Configure with QEMUs required configure script
        """
        builddir = create_unused_dir(self.builddir, 'easybuild_obj')
        change_dir(builddir)

        preconfigopts = self.cfg['preconfigopts']
        configopts = self.cfg['configopts']

        if self.cfg['targets']:
            targets = '--target-list=' + ','.join(self.cfg['targets'])
        else:
            targets = ''
        if self.cfg['targets_exclude']:
            targets_exclude = '--target-list-exclude=' + ','.join(self.cfg['targets_exclude'])
        else:
            targets_exclude = ''

        cmd = f'{preconfigopts} {self.start_dir}/configure --prefix={self.installdir} ' + \
              f'{targets} {targets_exclude} {configopts} '
        res = run_shell_cmd(cmd)
