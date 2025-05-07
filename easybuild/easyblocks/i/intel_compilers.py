# #
# Copyright 2021-2025 Ghent University
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
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.easyblocks.tbb import get_tbb_gccprefix
from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS
from easybuild.tools.run import run_shell_cmd


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

    @property
    def compilers_subdir(self):
        compilers_subdir = self.get_versioned_subdir('compiler')
        if LooseVersion(self.version) < LooseVersion('2024'):
            compilers_subdir = os.path.join(compilers_subdir, 'linux')
        return compilers_subdir

    @property
    def tbb_subdir(self):
        return self.get_versioned_subdir('tbb')

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

        oneapi_compiler_cmds = [
            'dpcpp',  # Intel oneAPI Data Parallel C++ compiler
            'icx',  # oneAPI Intel C compiler
            'icpx',  # oneAPI Intel C++ compiler
            'ifx',  # oneAPI Intel Fortran compiler
        ]
        bindir = os.path.join(self.compilers_subdir, 'bin')
        oneapi_compiler_paths = [os.path.join(bindir, x) for x in oneapi_compiler_cmds]
        if LooseVersion(self.version) >= LooseVersion('2025'):
            classic_compiler_cmds = []
        elif LooseVersion(self.version) >= LooseVersion('2024'):
            classic_compiler_cmds = ['ifort']
            classic_bindir = bindir
        else:
            classic_compiler_cmds = ['icc', 'icpc', 'ifort']
            classic_bindir = os.path.join(bindir, 'intel64')
        classic_compiler_paths = [os.path.join(classic_bindir, x) for x in classic_compiler_cmds]

        custom_paths = {
            'files': classic_compiler_paths + oneapi_compiler_paths,
            'dirs': [self.compilers_subdir],
        }

        all_compiler_cmds = classic_compiler_cmds + oneapi_compiler_cmds
        custom_commands = ["which %s" % c for c in all_compiler_cmds]

        # only for 2021.x versions do all compiler commands have the expected version;
        # for example: for 2022.0.1, icc has version 2021.5.0, icpx has 2022.0.0
        if LooseVersion(self.version) >= LooseVersion('2022.0'):
            custom_commands.extend("%s --version" % c for c in all_compiler_cmds)
        else:
            custom_commands.extend("%s --version | grep %s" % (c, self.version) for c in all_compiler_cmds)

        super(EB_intel_minus_compilers, self).sanity_check_step(custom_paths=custom_paths,
                                                                custom_commands=custom_commands)

    def make_module_step(self, *args, **kwargs):
        """
        Set paths for module load environment based on the actual installation files
        """
        tbb_lib_prefix = os.path.join(self.tbb_subdir, 'lib', 'intel64')
        tbb_lib_gccdir = get_tbb_gccprefix(os.path.join(self.installdir, tbb_lib_prefix))

        self.module_load_environment.PATH = [os.path.join(self.compilers_subdir, path) for path in (
            'bin',
            os.path.join('bin', 'intel64'),
        )]
        self.module_load_environment.LD_LIBRARY_PATH = [
            os.path.join(self.compilers_subdir, 'lib'),
            os.path.join(self.compilers_subdir, 'lib', 'x64'),
            os.path.join(self.compilers_subdir, 'compiler', 'lib', 'intel64_lin'),
            os.path.join(tbb_lib_prefix, tbb_lib_gccdir),
        ]
        self.module_load_environment.LIBRARY_PATH = self.module_load_environment.LD_LIBRARY_PATH
        self.module_load_environment.MANPATH = [
            os.path.join(os.path.dirname(self.compilers_subdir), 'documentation', 'en', 'man', 'common'),
            os.path.join(self.compilers_subdir, 'share', 'man'),
        ]
        self.module_load_environment.OCL_ICD_FILENAMES = [os.path.join(self.compilers_subdir, path) for path in (
            os.path.join('lib', 'x64', 'libintelocl.so'),
            os.path.join('lib', 'libintelocl.so'),
        )]
        self.module_load_environment.TBBROOT = [self.tbb_subdir]

        # include paths to headers (e.g. CPATH)
        self.module_load_environment.set_alias_vars(MODULE_LOAD_ENV_HEADERS, os.path.join(self.tbb_subdir, 'include'))

        return super().make_module_step(*args, **kwargs)

    def make_module_extra(self):
        """Additional custom variables for intel-compiler"""
        txt = super(EB_intel_minus_compilers, self).make_module_extra()

        # On Debian/Ubuntu, /usr/include/x86_64-linux-gnu, or whatever dir gcc uses, needs to be included
        # in $CPATH for Intel C compiler
        res = run_shell_cmd("gcc -print-multiarch", hidden=True)
        multiarch_out = res.output.strip()
        if res.exit_code == 0 and multiarch_out:
            multi_arch_inc_dir_cmd = '|'.join([
                "gcc -E -Wp,-v -xc /dev/null 2>&1",
                f"grep {multiarch_out}$",
                "grep -v /include-fixed/",
            ])
            res = run_shell_cmd(multi_arch_inc_dir_cmd, hidden=True)
            multiarch_inc_dir = res.output.strip()
            if res.exit_code == 0 and multiarch_inc_dir:
                # system location must be appended at the end, so use append_paths
                for envar in self.module_load_environment.alias_vars(MODULE_LOAD_ENV_HEADERS):
                    self.log.info(
                        f"Adding multiarch include path '{multiarch_inc_dir}' to ${envar} in generated module file"
                    )
                    # system location must be appended at the end, so use append_paths
                    txt += self.module_generator.append_paths(envar, [multiarch_inc_dir], allow_abs=True)

        return txt
