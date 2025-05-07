# #
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
# #
"""
EasyBuild support for install the Intel C/C++ compiler suite, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Ward Poelmans (Ghent University)
@author: Fokko Masselink
"""

import os
import re
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.intelbase import IntelBase, COMP_ALL
from easybuild.easyblocks.tbb import get_tbb_gccprefix
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


def get_icc_version():
    """Obtain icc version string via 'icc --version'."""
    cmd = "icc --version"
    res = run_shell_cmd(cmd)

    ver_re = re.compile(r"^icc \(ICC\) (?P<version>[0-9.]+) [0-9]+$", re.M)
    version = ver_re.search(res.output).group('version')

    return version


class EB_icc(IntelBase):
    """
    Support for installing icc
    - minimum version suported: 2020.0
    """

    def __init__(self, *args, **kwargs):
        """Constructor, initialize class variables."""
        super(EB_icc, self).__init__(*args, **kwargs)

        self.comp_libs_subdir = ""

        # need to make sure version is an actual version
        # required because of support in SystemCompiler generic easyblock to specify 'system' as version,
        # which results in deriving the actual compiler version
        # comparing a non-version like 'system' with an actual version like '2016' fails with TypeError in Python 3.x
        if re.match(r'^[0-9]+.*', self.version):

            if LooseVersion(self.version) < LooseVersion('2020'):
                raise EasyBuildError(
                    f"Version {self.version} of {self.name} is unsupported. Mininum supported version is 2020.0."
                )

            self.comp_libs_subdir = os.path.join(f'compilers_and_libraries_{self.version}', 'linux')

            if self.cfg['components'] is None:
                # we need to use 'ALL' by default,
                # using 'DEFAULTS' results in key things not being installed (e.g. bin/icc)
                self.cfg['components'] = [COMP_ALL]
                self.log.debug(
                    f"Missing components specification, required for version {self.version}. "
                    f"Using {self.cfg['components']} instead."
                )

        # define list of subdirectories in search paths of module load environment
        # some of these paths only apply to certain versions, but that doesn't really matter
        # existence of paths is checked by module generator before 'prepend-paths' statements are included

        # new directory layout since Intel Parallel Studio XE 2016
        # https://software.intel.com/en-us/articles/new-directory-layout-for-intel-parallel-studio-xe-2016
        # in recent Intel compiler distributions, the actual binaries are
        # in deeper directories, and symlinked in top-level directories
        # however, not all binaries are symlinked (e.g. mcpcom is not)
        # we only need to include the deeper directories (same as compilervars.sh)
        def comp_libs_subdir_paths(*subdir_paths):
            """Utility method to prepend self.comp_libs_subdir to list of paths"""
            try:
                return [os.path.join(self.comp_libs_subdir, path) for path in subdir_paths]
            except TypeError:
                raise EasyBuildError(f"Cannot prepend {self.comp_libs_subdir} to {subdir_paths}: wrong data type")

        self.module_load_environment.PATH = comp_libs_subdir_paths(
            'bin/intel64',
            'ipp/bin/intel64',
            'mpi/intel64/bin',
            'tbb/bin/emt64',
            'tbb/bin/intel64',
        )
        # in the end we set 'LIBRARY_PATH' equal to 'LD_LIBRARY_PATH'
        self.module_load_environment.LD_LIBRARY_PATH = comp_libs_subdir_paths(
            'lib',
            'compiler/lib/intel64',
            'debugger/ipt/intel64/lib',
            'ipp/lib/intel64',
            'mkl/lib/intel64',
            'mpi/intel64',
            f"tbb/lib/intel64/{get_tbb_gccprefix(os.path.join(self.installdir, 'tbb/lib/intel64'))}",
        )
        # 'include' is deliberately omitted, including it causes problems, e.g. with complex.h and std::complex
        # cfr. https://software.intel.com/en-us/forums/intel-c-compiler/topic/338378
        self.module_load_environment.set_alias_vars(MODULE_LOAD_ENV_HEADERS, comp_libs_subdir_paths(
            'daal/include',
            'ipp/include',
            'mkl/include',
            'tbb/include',
        ))
        self.module_load_environment.CLASSPATH = comp_libs_subdir_paths('daal/lib/daal.jar')
        self.module_load_environment.DAALROOT = comp_libs_subdir_paths('daal')
        self.module_load_environment.IPPROOT = comp_libs_subdir_paths('ipp')
        self.module_load_environment.MANPATH = comp_libs_subdir_paths(
            'debugger/gdb/intel64/share/man',
            'man/common',
            'man/en_US',
            'share/man',
        )
        self.module_load_environment.TBBROOT = comp_libs_subdir_paths('tbb')

        # Debugger requires INTEL_PYTHONHOME, which only allows for a single value
        self.debuggerpath = f"debugger_{self.version.split('.')[0]}"
        self.module_load_environment.LD_LIBRARY_PATH.extend([
            os.path.join(self.debuggerpath, 'libipt/intel64/lib'),
            'daal/lib/intel64_lin',  # out of self.comp_libs_subdir to not break libipt library loading for gdb
        ])
        self.module_load_environment.PATH.append(
            os.path.join(self.debuggerpath, 'gdb', 'intel64', 'bin')
        )

        # 'lib/intel64' is deliberately listed last, so it gets precedence over subdirs
        self.module_load_environment.LD_LIBRARY_PATH.extend(comp_libs_subdir_paths('lib/intel64'))

        self.module_load_environment.LIBRARY_PATH = self.module_load_environment.LD_LIBRARY_PATH

    def sanity_check_step(self):
        """Custom sanity check paths for icc."""

        binprefix = 'bin'
        binfiles = ['icc', 'icpc']
        binaries = [os.path.join(binprefix, f) for f in binfiles]

        libprefix = 'lib/intel64'
        libraries = [os.path.join(libprefix, f'lib{lib}') for lib in ['iomp5.a', f'iomp5.{get_shared_lib_ext()}']]

        headers = ['include/omp.h']

        custom_paths = {
            'files': binaries + libraries + headers,
            'dirs': [],
        }

        # make very sure that expected 'compilers_and_libraries_<VERSION>/linux' subdir is there for recent versions,
        # since we rely on it being there in module_load_environment
        if self.comp_libs_subdir:
            custom_paths['dirs'].append(self.comp_libs_subdir)

        custom_commands = ["which icc"]

        super(EB_icc, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_step(self, *args, **kwargs):
        """
        Additional paths for module load environment that are conditional
        """
        # only set $IDB_HOME if idb exists
        idb_home_subdir = 'bin/intel64'
        if os.path.isfile(os.path.join(self.installdir, idb_home_subdir, 'idb')):
            self.module_load_environment.IDB_HOME = [idb_home_subdir]

        return super().make_module_step(*args, **kwargs)

    def make_module_extra(self, *args, **kwargs):
        """Additional custom variables for icc: $INTEL_PYTHONHOME."""
        txt = super(EB_icc, self).make_module_extra(*args, **kwargs)

        intel_pythonhome = os.path.join(self.installdir, self.debuggerpath, 'python', 'intel64')
        if os.path.isdir(intel_pythonhome):
            txt += self.module_generator.set_environment('INTEL_PYTHONHOME', intel_pythonhome)

        # on Debian/Ubuntu, /usr/include/x86_64-linux-gnu needs to be included in $CPATH for icc
        res = run_shell_cmd("gcc -print-multiarch", fail_on_error=False, hidden=True)
        multiarch_inc_subdir = res.output.strip()
        if res.exit_code == 0 and multiarch_inc_subdir:
            multiarch_inc_dir = os.path.join('/usr', 'include', multiarch_inc_subdir)
            for envar in self.module_load_environment.alias_vars(MODULE_LOAD_ENV_HEADERS):
                self.log.info(f"Adding multiarch include path '{multiarch_inc_dir}' to ${envar} in generated module")
                # system location must be appended at the end, so use append_paths
                txt += self.module_generator.append_paths(envar, [multiarch_inc_dir], allow_abs=True)

        return txt
