##
# Copyright 2009-2025 Ghent University
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
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.systemtools import AARCH32, AARCH64, X86_64, get_cpu_architecture
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC


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

    def go_microarch_opt(self):
        """
        Microarchitecture optimization support
        see https://go.dev/wiki/MinimumRequirements#architectures
        """
        if LooseVersion(get_software_version('Go')) < LooseVersion("1.18"):
            self.log.debug("Go version %s does not support microarchitecture optimization", self.version)
            return None

        optarch = build_option('optarch') or ''
        if isinstance(optarch, dict):
            # optarch specified by compiler family
            optarch = optarch.get(self.toolchain.comp_family(), '')
        optarch = optarch.upper()

        microarch = None
        opt_level = None

        if get_cpu_architecture() == AARCH32:
            # default to VFPv1, default if cross compiling
            microarch = "GOARM"
            opt_level = "6"
            if 'VFPV3' in optarch:
                # use VFPv3; usually Cortex-A cores
                opt_level = "7"
            elif 'VFP' in optarch:
                # use VFPv1 only; usually ARM11 or better (VFPv2 or better is also supported)
                opt_level = "6"
            elif optarch == OPTARCH_GENERIC:
                opt_level = "5"
            elif optarch:
                opt_level = None

        elif get_cpu_architecture() == AARCH64:
            if LooseVersion(get_software_version('Go')) < LooseVersion("1.23"):
                self.log.debug(
                    "Go version %s does not support microarchitecture optimization for %s", self.version, AARCH64
                )
                return None

            # default to v8.0, default in Go for AARCH64
            microarch = "GOARM64"
            opt_level = "v8.0"
            # Allowed values are v8.{0-9} and v9.{0-5}. This may be followed by an option specifying extensions
            # implemented by target hardware. Example: GOARM64=v8.0,lse
            if optarch.startswith("v8.") or optarch.startswith("v9."):
                opt_level = optarch
            elif optarch == OPTARCH_GENERIC:
                opt_level = "v8.0"
            elif optarch:
                opt_level = None

        elif get_cpu_architecture() == X86_64:
            # default to x86-64-v3 with AVX2
            microarch = "GOAMD64"
            opt_level = "v3"
            if optarch.endswith("V4") or 'AVX512' in optarch:
                opt_level = "v4"
            elif optarch.endswith("V3") or 'AVX' in optarch:
                opt_level = "v3"
            elif optarch.endswith("V2") or 'SSE4' in optarch or 'SSE3' in optarch:
                opt_level = "v2"
            elif optarch == OPTARCH_GENERIC or optarch.endswith("V1"):
                opt_level = "v1"
            elif optarch:
                opt_level = None

        if microarch and opt_level is None:
            warn_msg = f"Unknown optarch setting given for Go architecture ({microarch}): {optarch}."
            warn_msg += f" Building '{self.name}' with auto-detection in Go."
            self.log.warning(warn_msg)
            print_warning(warn_msg)
            return None

        self.log.debug(f"Setting 'optarch={optarch}' converted to Go environment variable '{microarch}:{opt_level}'")
        return (microarch, opt_level)

    def prepare_step(self, *args, **kwargs):
        """Go-specific preparations."""
        super().prepare_step(*args, **kwargs)

        if get_software_root('Go') is None:
            raise EasyBuildError("Failed to pick go command to use. Is it listed in dependencies?")

        if LooseVersion(get_software_version('Go')) < LooseVersion("1.11"):
            raise EasyBuildError("Go version < 1.11 doesn't support installing modules from go.mod")

    def configure_step(self):
        """Configure Go package build/install."""

        # Move compiled .a files into builddir, else they pollute $HOME/go
        env.setvar('GOPATH', self.builddir, verbose=False)
        # enforce use of go modules
        env.setvar('GO111MODULE', 'on', verbose=False)
        # set bin folder
        env.setvar('GOBIN', os.path.join(self.installdir, 'bin'), verbose=False)
        # microarchitecture
        microarch = self.go_microarch_opt()
        if microarch is not None:
            env.setvar(*microarch, verbose=False)

        # creates log entries for go being used, for debugging
        run_shell_cmd("go version", hidden=True)
        run_shell_cmd("go env", hidden=True)

    def build_step(self):
        """If Go package is not native go module, lets try to make the module."""

        go_mod_file = 'go.mod'
        go_sum_file = 'go.sum'

        if not os.path.exists(go_mod_file) or not os.path.isfile(go_mod_file):
            self.log.warning("go.mod not found! This is not natively supported go module. Trying to init module.")

            if self.cfg['modulename'] is None:
                raise EasyBuildError("Installing non-native go module. You need to specify 'modulename' in easyconfig")

            # for more information about migrating to go modules
            # see: https://blog.golang.org/migrating-to-go-modules

            # go mod init
            cmd = ' '.join(['go', 'mod', 'init', self.cfg['modulename']])
            run_shell_cmd(cmd)

            if self.cfg['forced_deps']:
                for dep in self.cfg['forced_deps']:
                    # go get specific dependencies which locks them in go.mod
                    cmd = ' '.join(['go', 'get', '%s@%s' % dep])
                    run_shell_cmd(cmd)

            # note: ... (tripledot) used below is not a typo, but go wildcard pattern
            # which means: anything you can find in this directory, including all subdirectories
            # see: 'go help packages' or https://golang.org/pkg/cmd/go/internal/help/
            # see: https://stackoverflow.com/a/28031651/2047157

            # building and testing will add packages to go.mod
            run_shell_cmd('go build ./...')
            run_shell_cmd('go test ./...')

            # tidy up go.mod
            run_shell_cmd('go mod tidy')

            # build and test again, to ensure go mod tidy didn't removed anything needed
            run_shell_cmd('go build ./...')
            run_shell_cmd('go test ./...')

            self.log.warning('Include generated go.mod and go.sum via patch to ensure locked dependencies '
                             'and run this easyconfig again.')
            run_shell_cmd('cat go.mod')
            run_shell_cmd('cat go.sum')

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
        run_shell_cmd(cmd)

    def sanity_check_step(self):
        """Custom sanity check for Go package."""

        # Check if GoPackage produced binary and can run help on it
        custom_paths = {
            'files': ['bin/%s' % self.name.lower()],
            'dirs': [],
        }
        custom_commands = ['%s --help' % self.name.lower()]

        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def sanity_check_rpath(self, rpath_dirs=None):
        super().sanity_check_rpath(rpath_dirs=rpath_dirs, check_readelf_rpath=False)
