##
# Copyright 2009-2020 Ghent University
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
EasyBuild support for Go packages, implemented as an EasyBlock

@author: Pavel Grochal (INUITS)
"""
import os
from distutils.version import LooseVersion

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import which
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd


class GoPackage(EasyBlock):
    """Builds and installs a Go package, and provides a dedicated module file."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to Go packages."""
        if extra_vars is None:
            extra_vars = {}
        extra_vars.update({
            'modulename': [None, "Module name of the go package, when building non-native module", CUSTOM],
            'forced_deps': [None, "Force specific version of go package, when building non-native module", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables."""
        super(GoPackage, self).__init__(*args, **kwargs)
        self.go_cmd = None

    def prepare_go(self):
        """Go-specific preperations."""

        go = None
        go_root = get_software_root('Go')
        if go_root:
            bin_go = os.path.join(go_root, 'bin', 'go')
            if os.path.exists(bin_go) and os.path.samefile(which('go'), bin_go):
                # if Go is listed as a (build) dependency, use 'go' command provided that way
                go = os.path.join(go_root, 'bin', 'go')
                self.log.debug("Retaining 'go' command for Go dependency: %s", go)
        if go:
            self.go_cmd = go
        else:
            raise EasyBuildError("Failed to pick go command to use. Is it listed in dependencies?")

        go_version = get_software_version('Go')
        if LooseVersion(go_version) < LooseVersion("1.11"):
            raise EasyBuildError("Go version < 1.11 doesn't support installing modules from go.mod")

        # enforce use of go modules
        env.setvar('GO111MODULE', 'on', verbose=False)
        # set bin folder
        env.setvar('GOBIN', os.path.join(self.installdir, 'bin'), verbose=False)

    def configure_step(self):
        """Configure Go package build/install."""

        if self.go_cmd is None:
            self.prepare_go()

        # creates log entries for go being used, for debugging
        run_cmd("%s version" % self.go_cmd, verbose=False, trace=False)
        run_cmd("%s env" % self.go_cmd, verbose=False, trace=False)

    def build_step(self):
        """If Go package is not native go module, lets try to make the module."""

        go_mod_file = os.path.join('./', 'go.mod')
        go_sum_file = os.path.join('./', 'go.sum')

        if not os.path.exists(go_mod_file) or not os.path.isfile(go_mod_file):
            self.log.warn("go.mod not found! This is not natively supported go module. Trying to init module.")

            if self.cfg['modulename'] is None:
                raise EasyBuildError("Installing non-native go module. You need to specify 'modulename' in easyconfig")

            # for more information about migrating to go modules
            # see: https://blog.golang.org/migrating-to-go-modules

            # go mod init
            cmd = ' '.join([self.go_cmd, 'mod init', self.cfg['modulename']])
            run_cmd(cmd, log_all=True, simple=True)

            if self.cfg['forced_deps']:
                for dep in self.cfg['forced_deps']:
                    # go get specific dependencies which locks them in go.mod
                    cmd = ' '.join([self.go_cmd, 'get %s@%s' % dep])
                    run_cmd(cmd, log_all=True, simple=True)

            # go build ./...
            cmd = ' '.join([self.go_cmd, 'build ./...'])
            run_cmd(cmd, log_all=True, simple=True)

            # go test ./...
            cmd = ' '.join([self.go_cmd, 'test ./...'])
            run_cmd(cmd, log_all=True, simple=True)

            # go mod tidy
            cmd = ' '.join([self.go_cmd, 'mod tidy'])
            run_cmd(cmd, log_all=True, simple=True)

            # go build ./... again
            cmd = ' '.join([self.go_cmd, 'build ./...'])
            run_cmd(cmd, log_all=True, simple=True)

            # go test ./... again
            cmd = ' '.join([self.go_cmd, 'test ./...'])
            run_cmd(cmd, log_all=True, simple=True)

            self.log.warn('Include generated go.mod and go.sum via patch to ensure locked dependencies '
                          'and run this easyconfig again.')
            cmd = 'cat go.mod'
            run_cmd(cmd, log_all=True, simple=True)

            cmd = 'cat go.sum'
            run_cmd(cmd, log_all=True, simple=True)

        if not os.path.exists(go_sum_file) or not os.path.isfile(go_sum_file):
            raise EasyBuildError("go.sum not found! This module has no locked dependency versions.")

    def install_step(self):
        """Install Go package to a custom path"""

        # actually install Go package
        cmd = ' '.join(
            [self.cfg['preinstallopts'], self.go_cmd, 'install', self.cfg['installopts']])
        run_cmd(cmd, log_all=True, log_ok=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for Go package."""

        # Go Package should produce something into bin directory
        custom_paths = {
            'files': [],
            'dirs': ['bin'],
        }

        super(GoPackage, self).sanity_check_step(custom_paths=custom_paths)
