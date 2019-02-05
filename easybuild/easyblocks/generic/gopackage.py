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

from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd
from easybuild.tools.modules import get_software_root

class GoPackage(ExtensionEasyBlock):
    """
    Install a Go package as a separate module, or as an extension.
    """

    def configure_step(self):
        """Custom configure: fetch the sources of the dependencies."""
        if not get_software_root("Go"):
            raise EasyBuildError("Go packages require to have a Go module in the builddependencies.")
        cmd = "env GOPATH=%s go get -d ./..." % (self.builddir)
        run_cmd(cmd)

    def build_step(self):
        """Build the Go packages."""
        cmd = "env GOPATH=%s go build ./..." % (self.builddir)
        run_cmd(cmd)

    def install_step(self):
        """Install procedure for Go packages."""
        cmd = "env GOBIN=%s GOPATH=%s go install ./..." % (self.installdir, self.builddir)
        run_cmd(cmd)

    def make_module_req_guess(self):
        """Add the installation directory to PATH."""
        guesses = super(GoPackage, self).make_module_req_guess()
        guesses['PATH'] = ['']
        return guesses

    def make_module_req_guess(self):
        """Customized dictionary of paths to look for with PERL*LIB."""

        guesses = super(GoPackage, self).make_module_req_guess()
        guesses.update({
            "PATH" : [''],
        })
        return guesses
