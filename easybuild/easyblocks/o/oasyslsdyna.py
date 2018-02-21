##
# Copyright 2009-2017 Ghent University
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
EasyBuild support for building and installing Oasys LS Dyna, implemented as an easyblock

@author: Maxime Boissonneault (Compute Canada, Universite Laval)

"""
import fileinput
import os
import re
import shutil
import sys
import tempfile
from distutils.version import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.run import run_cmd


class EB_OasysLSDyna(PackedBinary):
    """Support for building/installing OasysLSDyna."""

    def __init__(self,*args,**kwargs):
        """Enable building in install dir."""
        super(EB_OasysLSDyna, self).__init__(*args, **kwargs)

    def install_step(self):
        cmd = "echo -e \"%s\" | ./setup.csh" % ('\\n'.join(['FULL', 'Y', self.installdir, 'Y', 'N', 'Y', self.installdir, 'Y']))
        run_cmd(cmd, log_all=True, simple=True)


    def sanity_check_step(self):
        """Custom sanity check for OasysLSDyna."""
        custom_paths = {
            'files': ['oasys'],
            'dirs': [],
        }

        super(EB_OasysLSDyna, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Correctly prepend PATH."""

        txt = super(EB_OasysLSDyna, self).make_module_extra()

        return txt
