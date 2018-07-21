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
EasyBuild support for installing STAR-CCM+, implemented as an easyblock

@author: Maxime Boissonneault (Compute Canada, Laval University)
"""
from distutils.version import LooseVersion
import os
import stat

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.run import run_cmd
from easybuild.tools.filetools import adjust_permissions


class EB_STARCCM(PackedBinary):
    """Support for installing STAR-CCM+."""

    def __init__(self, *args, **kwargs):
        """Initialize STAR-CCM+-specific variables."""
        super(EB_STARCCM, self).__init__(*args, **kwargs)

    def install_step(self):
        """Custom install procedure for STAR-CCM+."""
        if LooseVersion(self.version) < LooseVersion('12.06.010'):
          cmd = "./STAR-CCM+*.bin -DINSTALLDIR=%s -DINSTALLFLEX=false -DNODOC=true -i silent" % os.path.join(self.installdir,"..")
        else:
          cmd = "./STAR-CCM+*.sh -DINSTALLDIR=%s -DINSTALLFLEX=false -DNODOC=true -i silent" % os.path.join(self.installdir,"..")
        
        run_cmd(cmd, log_all=True, simple=True)

    def make_module_req_guess(self):
        """Custom extra module file entries for STAR-CCM+."""
        guesses = super(EB_STARCCM, self).make_module_req_guess()
        dirs = [
            os.path.join("STAR-CCM+%s" % self.version, "star", "bin")
        ]
        guesses.update({"PATH": dirs})
        return guesses

    def sanity_check_step(self):
        """Custom sanity check for STAR-CCM+."""
        custom_paths = {
           'files': [os.path.join("STAR-CCM+%s" % self.version, "star", "bin", "starccm+") ],
           'dirs': []
        }
        super(EB_STARCCM, self).sanity_check_step(custom_paths=custom_paths)
