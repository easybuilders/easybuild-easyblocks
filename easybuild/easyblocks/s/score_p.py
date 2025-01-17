##
# Copyright 2013-2025 Ghent University
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
EasyBuild support for software using the Score-P configuration style (e.g., Cube, OTF2, Scalasca, and Score-P),
implemented as an EasyBlock.

@author: Kenneth Hoste (Ghent University)
@author: Bernd Mohr (Juelich Supercomputing Centre)
@author: Markus Geimer (Juelich Supercomputing Centre)
@author: Alexander Grund (TU Dresden)
@author: Christian Feld (Juelich Supercomputing Centre)
@author: Jan Andre Reuter (Juelich Supercomputing Centre)
"""
import os

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.environment import unset_env_vars
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.modules import get_software_root, get_software_libdir


class EB_Score_minus_P(ConfigureMake):
    """
    Support for building and installing software using the Score-P configuration style (e.g., Cube, OTF2, Scalasca,
    and Score-P).
    """
    def configure_step(self, *args, **kwargs):
        """Configure the build, set configure options for compiler, MPI and dependencies."""

        if LooseVersion('8.0') <= LooseVersion(self.version) < LooseVersion('8.5'):
            # Fix an issue where the configure script would fail if certain dependencies are installed in a path
            # that includes "yes" or "no", see https://gitlab.com/score-p/scorep/-/issues/1008.
            yes_no_regex = [
                (r'\*yes\*\|\*no\*', 'yes,*|no,*|*,yes|*,no'),
                (r'_lib}\${with_', '_lib},${with_'),
            ]
            configure_scripts = [
                os.path.join(self.start_dir, 'build-backend', 'configure'),
                os.path.join(self.start_dir, 'build-mpi', 'configure'),
                os.path.join(self.start_dir, 'build-shmem', 'configure'),
            ]
            for configure_script in configure_scripts:
                apply_regex_substitutions(configure_script, yes_no_regex)

        # Remove some settings from the environment, as they interfere with
        # Score-P's configure magic...
        unset_env_vars(['CPPFLAGS', 'LDFLAGS', 'LIBS'])

        # On non-cross-compile platforms, specify compiler and MPI suite explicitly. This is much quicker and safer
        # than autodetection. In Score-P build-system terms, the following platforms are considered cross-compile
        # architectures:
        #
        #   - Cray XT/XE/XK/XC series
        #   - Fujitsu FX10, FX100 & K computer
        #   - IBM Blue Gene series
        #
        # Of those, only Cray is supported right now.
        tc_fam = self.toolchain.toolchain_family()
        if tc_fam != toolchain.CRAYPE:
            # --with-nocross-compiler-suite=(gcc|ibm|intel|oneapi|nvhpc|pgi|clang| \
            #                                aocc|amdclang|cray)
            comp_opts = {
                # assume that system toolchain uses a system-provided GCC
                toolchain.SYSTEM: 'gcc',
                toolchain.GCC: 'gcc',
                toolchain.IBMCOMP: 'ibm',
                toolchain.INTELCOMP: 'intel',
                toolchain.NVHPC: 'nvhpc',
                toolchain.PGI: 'pgi',
            }
            nvhpc_since = {
                'Score-P': '8.0',
                'Scalasca': '2.6.1',
                'OTF2': '3.0.2',
                'CubeWriter': '4.8',
                'CubeLib': '4.8',
                'CubeGUI': '4.8',
            }
            if LooseVersion(self.version) < LooseVersion(nvhpc_since.get(self.name, '0')):
                comp_opts[toolchain.NVHPC] = 'pgi'
            # Switch to oneAPI for toolchains using oneAPI variants as default.
            # This may result in installations without Fortran compiler instrumentation support,
            # if this is chosen before 2024.0.0, as prior versions did not support the required flags.
            if self.toolchain.options.get('oneapi', None) is True:
                comp_opts[toolchain.INTELCOMP] = 'oneapi'

            comp_fam = self.toolchain.comp_family()
            if comp_fam in comp_opts:
                self.cfg.update('configopts', "--with-nocross-compiler-suite=%s" % comp_opts[comp_fam])
            else:
                raise EasyBuildError("Compiler family %s not supported yet (only: %s)",
                                     comp_fam, ', '.join(comp_opts.keys()))

            # --with-mpi=(bullxmpi|cray|hp|ibmpoe|intel|intel2|intel3|intelpoe|lam|
            #             mpibull2|mpich|mpich2|mpich3|mpich4|openmpi|openmpi3| \
            #             platform|scali|sgimpt|sgimptwrapper|spectrum|sun)
            #
            # Notes:
            #   - intel:    Intel MPI v1.x (ancient & unsupported)
            #   - intel2:   Intel MPI v2.x and higher
            #   - intelpoe: IBM POE MPI for Intel platforms
            #   - mpich:    MPICH v1.x (ancient & unsupported)
            #   - mpich2:   MPICH2 v1.x
            #   - mpich3:   MPICH v3.x & MVAPICH2
            #               This setting actually only affects options passed to the MPI (Fortran) compiler wrappers.
            #               And since MPICH v3.x-compatible options were already supported in MVAPICH2 v1.7, it is
            #               safe to use 'mpich3' for all supported versions although MVAPICH2 is based on MPICH v3.x
            #               only since v1.9b.
            #
            # With minimal toolchains, packages using this EasyBlock may be built with a non-MPI toolchain (e.g., OTF2).
            # In this case, skip passing the '--with-mpi' option.
            mpi_opts = {
                toolchain.INTELMPI: 'intel2',
                toolchain.OPENMPI: 'openmpi',
                # In EB terms, MPICH means MPICH 3.x
                toolchain.MPICH: 'mpich3',
                toolchain.MPICH2: 'mpich2',
                toolchain.MVAPICH2: 'mpich3',
            }
            mpi_fam = self.toolchain.mpi_family()
            if mpi_fam is not None:
                if mpi_fam in mpi_opts:
                    self.cfg.update('configopts', "--with-mpi=%s" % mpi_opts[mpi_fam])
                else:
                    raise EasyBuildError("MPI family %s not supported yet (only: %s)",
                                         mpi_fam, ', '.join(mpi_opts.keys()))

        # Auto-detection for dependencies mostly works fine, but hard specify paths anyway to have full control
        #
        # Notes:
        #   - binutils: Pass include/lib directories separately, as different directory layouts may break Score-P's
        #               configure, see https://github.com/geimer/easybuild-easyblocks/pull/4#issuecomment-219284755
        deps = {
            'binutils': ['--with-libbfd-include=%s/include',
                         '--with-libbfd-lib=%%s/%s' % get_software_libdir('binutils', fs=['libbfd.a'])],
            'libunwind': ['--with-libunwind=%s'],
            'CubeLib': ['--with-cubelib=%s/bin'],
            'CubeWriter': ['--with-cubew=%s/bin'],
            'CUDA': ['--enable-cuda', '--with-libcudart=%s'],
            'GOTCHA': ['--with-libgotcha=%s'],
            'OTF2': ['--with-otf2=%s/bin'],
            'OPARI2': ['--with-opari2=%s/bin'],
            'PAPI': ['--with-papi-header=%s/include', '--with-papi-lib=%%s/%s' % get_software_libdir('PAPI')],
            'PDT': ['--with-pdt=%s/bin'],
            # Used for CubeGUI. As EasyBuild splits Qt versions into separate EasyConfig names, we need to specify all
            # supported Qt versions. EasyConfigs should only use one of them.
            'Qt': ['--with-qt=%s/bin'],
            'Qt5': ['--with-qt=%s/bin'],
            'Qt6': ['--with-qt=%s/bin'],
            'SIONlib': ['--with-sionlib=%s/bin'],
        }

        # Go through all dependencies of passed EasyConfig to determine which flags to pass
        # explicitly to configure.
        ec_explicit_deps = [dep for dep in self.cfg.all_dependencies if dep['name'] in deps.keys()]
        for dep in ec_explicit_deps:
            dep_root = get_software_root(dep['name'])
            configure_opts = deps[dep['name']]
            for configure_opt in configure_opts:
                try:
                    configure_opt = configure_opt % dep_root
                except TypeError:
                    # Ignore substitution error when there is nothing to substitute
                    pass
                self.cfg.update('configopts', configure_opt)

        super(EB_Score_minus_P, self).configure_step(*args, **kwargs)
