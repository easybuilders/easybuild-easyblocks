# -*- coding: utf-8 -*-
##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for building and installing Go packages, implemented as an easyblock

@author: Bob Dröge (University of Groningen)
"""
import os
import shutil

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd
from easybuild.tools.modules import get_software_root

class GoPackage(Tarball):
    """
    Install a Go package as a separate module, or as an extension.
    """

    def install_step(self):
        """Install procedure for Go packages."""
        if not get_software_root("Go"):
            raise EasyBuildError("Go packages require to have a Go module in the (build)dependencies.")
        cmd = "env GOBIN=%s GOPATH=%s go get ./..." % (self.installdir, self.builddir)
        run_cmd(cmd)

    def make_module_req_guess(self):
        """Add the installation directory to PATH."""
        guesses = super(GoPackage, self).make_module_req_guess()
        guesses['PATH'] = ['']
        return guesses
