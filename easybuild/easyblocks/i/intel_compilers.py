# #
# Copyright 2021-2021 Ghent University
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
# #
"""
EasyBuild support for installing Intel compilers, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.tools.build_log import EasyBuildError, print_msg


class EB_intel_minus_compilers(IntelBase):
    """
    Support for installing Intel compilers, starting with verion 2021.x (oneAPI)
    """

    def __init__(self, *args, **kwargs):
        """
        Easyblock constructor: check version
        """
        super(EB_intel_minus_compilers, self).__init__(*args, **kwargs)

        # this easyblock is only valid for recent versions of the Intel compilers (2021.x, oneAPI)
        if LooseVersion(self.version) < LooseVersion('2021'):
            raise EasyBuildError("Invalid version %s, should be >= 2021.x" % self.version)

        self.compilers_subdir = os.path.join('compiler', self.version, 'linux')

    def prepare_step(self, *args, **kwargs):
        """
        Prepare environment for installing.

        Specify that oneAPI versions of Intel compilers don't require a runtime license.
        """
        # avoid that IntelBase trips over not having license info specified
        kwargs['requires_runtime_license'] = False

        super(EB_intel_minus_compilers, self).prepare_step(*args, **kwargs)

    def configure_step(self):
        """Configure installation."""

        # redefine $HOME for install step, to avoid that anything is stored in $HOME/intel
        # (like the 'installercache' database)
        self.cfg['preinstallopts'] += " HOME=%s " % self.builddir

    def install_step(self):
        """
        Install step: install each 'source file' one by one.
        Installing the Intel compilers could be done via a single installation file (HPC Toolkit),
        or with separate installation files (patch releases of the C++ and Fortran compilers).
        """
        srcs = self.src[:]
        cnt = len(srcs)
        for idx, src in enumerate(srcs):
            print_msg("installing part %d/%s (%s)..." % (idx + 1, cnt, src['name']))
            self.src = [src]
            super(EB_intel_minus_compilers, self).install_step()

    def sanity_check_step(self):
        """
        Custom sanity check for Intel compilers.
        """

        classic_compiler_cmds = ['icc', 'icpc', 'ifort']
        oneapi_compiler_cmds = [
            'dpcpp',  # Intel oneAPI Data Parallel C++ compiler
            'icx',  # oneAPI Intel C compiler
            'icpx',  # oneAPI Intel C++ compiler
            'ifx',  # oneAPI Intel Fortran compiler
        ]
        bindir = os.path.join(self.compilers_subdir, 'bin')
        classic_compiler_paths = [os.path.join(bindir, x) for x in oneapi_compiler_cmds]
        oneapi_compiler_paths = [os.path.join(bindir, 'intel64', x) for x in classic_compiler_cmds]

        custom_paths = {
            'files': classic_compiler_paths + oneapi_compiler_paths,
            'dirs': [self.compilers_subdir],
        }

        all_compiler_cmds = classic_compiler_cmds + oneapi_compiler_cmds
        custom_commands = ["which %s" % c for c in all_compiler_cmds]
        custom_commands.extend("%s --version | grep %s" % (c, self.version) for c in all_compiler_cmds)

        super(EB_intel_minus_compilers, self).sanity_check_step(custom_paths=custom_paths,
                                                                custom_commands=custom_commands)

    def make_module_req_guess(self):
        """
        Paths to consider for prepend-paths statements in module file
        """
        libdirs = [
            'lib',
            os.path.join('lib', 'x64'),
            os.path.join('compiler', 'lib', 'intel64_lin'),
        ]
        libdirs = [os.path.join(self.compilers_subdir, x) for x in libdirs]
        guesses = {
            'PATH': [
                os.path.join(self.compilers_subdir, 'bin'),
                os.path.join(self.compilers_subdir, 'bin', 'intel64'),
            ],
            'LD_LIBRARY_PATH': libdirs,
            'LIBRARY_PATH': libdirs,
        }
        return guesses
