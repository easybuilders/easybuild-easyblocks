##
# Copyright 2014 Ghent University
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
# along with EasyBuild. If not, see <http://www.gnu.org/licenses/>.
##
"""
@author: Maxime Boissonneault (Calcul Quebec, Compute Canada)
"""
import os
import re

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd


class EB_VisIt(PackedBinary):
    """Support for installing VisIt"""
    @staticmethod
    def extra_options(extra_vars=None):
        """
        Define list of files or directories to be copied after make
        """
        extra_vars = PackedBinary.extra_options(extra_vars=extra_vars)
        extra_vars["visit_options"] = ['', "Options to pass to the build script", CUSTOM]
        return extra_vars

    def install_step(self):
        """Build by running the command with the inputfiles"""
#        run_cmd("chmod +x %s" % self.src[0]['path'])
        run_cmd("mkdir -p %s/3rdparty" % self.installdir)
        cmd = '%s yes yes | ./build_visit* --prefix %s --thirdparty-path %s/3rdparty %s' % (self.cfg['prebuildopts'], self.installdir, self.installdir, self.cfg["visit_options"])
        run_cmd(cmd, log_all=True, simple=True)

