##
# Copyright 2009-2023 Ghent University
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
import re
from distutils.version import LooseVersion

import easybuild.tools.environment as env
from easybuild.framework.easyblock import DEFAULT_BIN_LIB_SUBDIRS, EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_linked_libs_raw


class GoPackage(EasyBlock):
    """Builds and installs a Go package, and provides a dedicated module file."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to Go packages."""
        if extra_vars is None:
            extra_vars = {}
        extra_vars.update({
            'modulename': [None, "Module name of the Go package, when building non-native module", CUSTOM],
            'forced_deps': [None, "Force specific version of Go package, when building non-native module", CUSTOM],
        })
        return extra_vars

    def prepare_step(self, *args, **kwargs):
        """Go-specific preparations."""
        super(GoPackage, self).prepare_step(*args, **kwargs)

        if get_software_root('Go') is None:
            raise EasyBuildError("Failed to pick go command to use. Is it listed in dependencies?")

        if LooseVersion(get_software_version('Go')) < LooseVersion("1.11"):
            raise EasyBuildError("Go version < 1.11 doesn't support installing modules from go.mod")

    def configure_step(self):
        """Configure Go package build/install."""

        # enforce use of go modules
        env.setvar('GO111MODULE', 'on', verbose=False)
        # set bin folder
        env.setvar('GOBIN', os.path.join(self.installdir, 'bin'), verbose=False)

        # creates log entries for go being used, for debugging
        run_cmd("go version", verbose=False, trace=False)
        run_cmd("go env", verbose=False, trace=False)

    def build_step(self):
        """If Go package is not native go module, lets try to make the module."""

        go_mod_file = 'go.mod'
        go_sum_file = 'go.sum'

        if not os.path.exists(go_mod_file) or not os.path.isfile(go_mod_file):
            self.log.warn("go.mod not found! This is not natively supported go module. Trying to init module.")

            if self.cfg['modulename'] is None:
                raise EasyBuildError("Installing non-native go module. You need to specify 'modulename' in easyconfig")

            # for more information about migrating to go modules
            # see: https://blog.golang.org/migrating-to-go-modules

            # go mod init
            cmd = ' '.join(['go', 'mod', 'init', self.cfg['modulename']])
            run_cmd(cmd, log_all=True, simple=True)

            if self.cfg['forced_deps']:
                for dep in self.cfg['forced_deps']:
                    # go get specific dependencies which locks them in go.mod
                    cmd = ' '.join(['go', 'get', '%s@%s' % dep])
                    run_cmd(cmd, log_all=True, simple=True)

            # note: ... (tripledot) used below is not a typo, but go wildcard pattern
            # which means: anything you can find in this directory, including all subdirectories
            # see: 'go help packages' or https://golang.org/pkg/cmd/go/internal/help/
            # see: https://stackoverflow.com/a/28031651/2047157

            # building and testing will add packages to go.mod
            run_cmd('go build ./...', log_all=True, simple=True)
            run_cmd('go test ./...', log_all=True, simple=True)

            # tidy up go.mod
            run_cmd('go mod tidy', log_all=True, simple=True)

            # build and test again, to ensure go mod tidy didn't removed anything needed
            run_cmd('go build ./...', log_all=True, simple=True)
            run_cmd('go test ./...', log_all=True, simple=True)

            self.log.warn('Include generated go.mod and go.sum via patch to ensure locked dependencies '
                          'and run this easyconfig again.')
            run_cmd('cat go.mod', log_all=True, simple=True)
            run_cmd('cat go.sum', log_all=True, simple=True)

        if not os.path.exists(go_sum_file) or not os.path.isfile(go_sum_file):
            raise EasyBuildError("go.sum not found! This module has no locked dependency versions.")

    def install_step(self):
        """Install Go package to a custom path"""

        # actually install Go package
        cmd = ' '.join([
            self.cfg['preinstallopts'],
            'go',
            'install',
            # print commands as they are executed,
            # including downloading and installing of package deps as listed in the go.mod file
            '-x',
            self.cfg['installopts'],
        ])
        run_cmd(cmd, log_all=True, log_ok=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for Go package."""

        # Check if GoPackage produced binary and can run help on it
        custom_paths = {
            'files': ['bin/%s' % self.name.lower()],
            'dirs': [],
        }
        custom_commands = ['%s --help' % self.name.lower()]

        super(GoPackage, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def sanity_check_rpath(self, rpath_dirs=None):
        """Sanity check binaries/libraries w.r.t. RPATH linking."""

        self.log.info("Checking RPATH linkage for binaries/libraries...")

        fails = []

        # hard reset $LD_LIBRARY_PATH before running RPATH sanity check
        orig_env = env.unset_env_vars(['LD_LIBRARY_PATH'])

        self.log.debug("$LD_LIBRARY_PATH during RPATH sanity check: %s", os.getenv('LD_LIBRARY_PATH', '(empty)'))
        self.log.debug("List of loaded modules: %s", self.modules_tool.list())

        not_found_regex = re.compile(r'(\S+)\s*\=\>\s*not found')
        readelf_rpath_regex = re.compile('(RPATH)', re.M)

        # List of libraries that should be exempt from the RPATH sanity check;
        # For example, libcuda.so.1 should never be RPATH-ed by design,
        # see https://github.com/easybuilders/easybuild-framework/issues/4095
        filter_rpath_sanity_libs = build_option('filter_rpath_sanity_libs')
        msg = "Ignoring the following libraries if they are not found by RPATH sanity check: %s"
        self.log.info(msg, filter_rpath_sanity_libs)

        if rpath_dirs is None:
            rpath_dirs = self.cfg['bin_lib_subdirs'] or self.bin_lib_subdirs()

        if not rpath_dirs:
            rpath_dirs = DEFAULT_BIN_LIB_SUBDIRS
            self.log.info("Using default subdirectories for binaries/libraries to verify RPATH linking: %s",
                          rpath_dirs)
        else:
            self.log.info("Using specified subdirectories for binaries/libraries to verify RPATH linking: %s",
                          rpath_dirs)

        for dirpath in [os.path.join(self.installdir, d) for d in rpath_dirs]:
            if os.path.exists(dirpath):
                self.log.debug("Sanity checking RPATH for files in %s", dirpath)

                for path in [os.path.join(dirpath, x) for x in os.listdir(dirpath)]:
                    self.log.debug("Sanity checking RPATH for %s", path)

                    out = get_linked_libs_raw(path)

                    if out is None:
                        msg = "Failed to determine dynamically linked libraries for %s, "
                        msg += "so skipping it in RPATH sanity check"
                        self.log.debug(msg, path)
                    else:
                        # check whether all required libraries are found via 'ldd'
                        matches = re.findall(not_found_regex, out)
                        if len(matches) > 0:  # Some libraries are not found via 'ldd'
                            # For each match, check if the library is in the exception list
                            for match in matches:
                                if match in filter_rpath_sanity_libs:
                                    msg = "Library %s not found for %s, but ignored "
                                    msg += "since it is on the rpath exception list: %s"
                                    self.log.info(msg, match, path, filter_rpath_sanity_libs)
                                else:
                                    fail_msg = "Library %s not found for %s; " % (match, path)
                                    fail_msg += "RPATH linking is enabled, but not implemented for Go packages."
                                    fail_msg += "See https://github.com/easybuilders/easybuild-easyconfigs/issues/17516"
                                    self.log.warning(fail_msg)
                                    fails.append(fail_msg)
                        else:
                            self.log.debug("Output of 'ldd %s' checked, looks OK", path)
            else:
                self.log.debug("Not sanity checking files in non-existing directory %s", dirpath)

        env.restore_env_vars(orig_env)

        return fails
