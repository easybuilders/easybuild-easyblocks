##
# Copyright 2013 Ghent University
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
EasyBuild support for building and installing FEKO, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import glob
import os
import shutil
from easybuild.easyblocks.generic.binary import Binary
from easybuild.easyblocks.generic.rpm import rebuild_rpm
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import rmtree2
from easybuild.tools.run import run_cmd, run_cmd_qa


class EB_FEKO(Binary):
    """Support for building/installing FEKO."""

    def build_step(self):
        """No build step for FEKO."""
        pass

    def install_step(self):
        """Install FEKO by running the command."""
        cmd = "cd %s && ./hwFEKO* -i silent -DUSER_INSTALL_DIR=%s -r %s/installation_responses.txt" % (self.builddir, self.installdir, self.installdir)
        run_cmd(cmd, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for FEKO."""
        custom_paths = {
            'files': ['altair/feko/bin/feko_parallel', 'installation_responses.txt'],
            'dirs': ['altair/feko/bin']
        }
        super(EB_FEKO, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Add bin folder for feko to the module"""

        txt = super(EB_FEKO, self).make_module_extra()

        txt += self.module_generator.prepend_paths('PATH', "altair/feko/bin")

        return txt

