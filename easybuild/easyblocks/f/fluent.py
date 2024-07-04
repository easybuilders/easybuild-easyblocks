##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for installing FLUENT, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os
import stat
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import adjust_permissions
from easybuild.tools.run import run_cmd


class EB_FLUENT(PackedBinary):
    """Support for installing FLUENT."""

    @staticmethod
    def extra_options():
        extra_vars = PackedBinary.extra_options()
        extra_vars['subdir_version'] = [None, "Version to use to determine installation subdirectory", CUSTOM]
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Custom constructor for FLUENT easyblock, initialize/define class parameters."""
        super(EB_FLUENT, self).__init__(*args, **kwargs)

        subdir_version = self.cfg['subdir_version']
        if subdir_version is None:
            subdir_version = ''.join(self.version.split('.')[:2])

        self.fluent_verdir = 'v%s' % subdir_version

    def install_step(self):
        """Custom install procedure for FLUENT."""
        extra_args = ''
        # only include -noroot flag for older versions
        if LooseVersion(self.version) < LooseVersion('15.0'):
            extra_args += '-noroot'

        cmd = "./INSTALL %s -debug -silent -install_dir %s %s" % (extra_args, self.installdir, self.cfg['installopts'])
        run_cmd(cmd, log_all=True, simple=True)

        adjust_permissions(self.installdir, stat.S_IWOTH, add=False)

    def sanity_check_step(self):
        """Custom sanity check for FLUENT."""
        bindir = os.path.join(self.fluent_verdir, 'fluent', 'bin')
        custom_paths = {
            'files': [os.path.join(bindir, 'fluent%s' % x) for x in ['', '_arch', '_sysinfo']],
            'dirs': [os.path.join(self.fluent_verdir, x) for x in ['aisol', 'CFD-Post']]
        }
        super(EB_FLUENT, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Custom extra module file entries for FLUENT."""
        guesses = super(EB_FLUENT, self).make_module_req_guess()

        guesses.update({
            'PATH': [
                os.path.join(self.fluent_verdir, 'fluent', 'bin'),
                os.path.join(self.fluent_verdir, 'Framework', 'bin', 'Linux64'),
            ],
            'LD_LIBRARY_PATH': [os.path.join(self.fluent_verdir, 'fluent', 'lib')],
        })

        return guesses
