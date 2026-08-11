##
# Copyright 2013-2026 Ghent University
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
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.environment import unset_env_vars
from easybuild.tools.filetools import apply_regex_substitutions, which
from easybuild.tools.modules import get_software_root, get_software_libdir
from easybuild.tools.run import run_shell_cmd


class EB_Score_minus_P(ConfigureMake):
    """
    Support for building and installing software using the Score-P configuration style (e.g., Cube, OTF2, Scalasca,
    and Score-P).
    """

    @staticmethod
    def extra_options(extra_vars=None):
        extra_vars = ConfigureMake.extra_options(extra_vars)
        extra_vars.update({
            'enable_compiler_plugin': [True, "Enable building with compiler plugin", CUSTOM],
            'enable_debug': [False, "Enables additional debug output via environment variable, at the cost of overhead",
                             CUSTOM],
            'enable_detailed_tests': [False, "Enable thorough tests. May require more resources "
                                      "and running tests with multiple ranks", CUSTOM],
            'enable_fortran': [True, "Enable building Fortran support", CUSTOM],
            'enable_mpi_f08': [True, "Enable building MPI Fortran 2008 bindings", CUSTOM],
            'enable_post_install_tests': [False, "Enable post-installation tests", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Constructor for Score-P easyblock."""
        super().__init__(*args, **kwargs)

        if (self.cfg['enable_detailed_tests'] or self.cfg['enable_post_install_tests']) and not self.cfg['runtest']:
            self.cfg['runtest'] = True
            print_warning("Enabling 'runtest' due to requested 'enable_detailed_tests' or 'enable_post_install_tests'!")

    def _patch_deficiencies(self):
        """
        Patch known deficiencies in software packages, which are not easily patchable across multiple versions
        with a patch file, e.g. patches to the configure scripts.
        """
        if self.name == "Score-P":
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

    def _determine_toolchain(self):
        """
        Determine toolchain to be used to build application. Tools use a common --with-nocross-compiler-suite=
        for this. Map the EasyBuild toolchains to the arguments understood by the configure scripts.
        Providing the compilers via environment variables is not recommended, as tools provide platform files with
        additional, potentially important, flags to be used during configure.
        """

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
                toolchain.LLVM: 'clang',
                toolchain.ROCM: 'amdclang',
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

    def _determine_mpi(self):
        """
        Determine MPI toolchain to be used to build application. Tools use a common --with-mpi=
        for this. Map the EasyBuild toolchains to the arguments understood by the configure scripts.
        Providing the compilers via environment variables is not recommended, as tools provide platform files with
        additional, potentially important, flags to be used during configure.
        """

        # --with-mpi=(bullxmpi|cray|hp|ibmpoe|intel|intel2|intel3|intelpoe|lam|
        #             mpibull2|mpich|mpich2|mpich3|mpich4|openmpi|openmpi3| \
        #             platform|scali|sgimpt|sgimptwrapper|spectrum|sun)
        #
        # Notes:
        #     intel3    -  Intel MPI 5.x and newer
        #     oneapi    -  Intel MPI 2021.10.x and newer (LLVM-based compilers) (since v10.0)
        #     mpich4    -  MPICH 4.x and newer
        #     openmpi3  -  Open MPI 3.x and newer
        # With minimal toolchains, packages using this EasyBlock may be built with a non-MPI toolchain (e.g., OTF2).
        # In this case, skip passing the '--with-mpi' option.
        mpi_opts = {
            toolchain.INTELMPI: 'intel3',
            toolchain.OPENMPI: 'openmpi3',
            toolchain.MPICH: 'mpich4',
        }
        mpi_fam = self.toolchain.mpi_family()
        if mpi_fam is not None:
            if mpi_fam in mpi_opts:
                self.cfg.update('configopts', "--with-mpi=%s" % mpi_opts[mpi_fam])
            else:
                raise EasyBuildError("MPI family %s not supported yet (only: %s)",
                                     mpi_fam, ', '.join(mpi_opts.keys()))
        else:
            self.cfg.update('configopts', "--without-mpi")

    def _determine_shmem(self):
        """
        Determine SHMEM toolchain to be used to build application. Tools use a common --with-shmem=
        for this. Map the EasyBuild toolchains to the arguments understood by the configure scripts.
        Providing the compilers via environment variables is not recommended, as tools provide platform files with
        additional, potentially important, flags to be used during configure.
        """

        # EasyBuild does not provide an easy way to determine different SHMEM toolchains.
        # OpenMPI is built with SHMEM support by default though. As such, enable SHMEM when OpenMPI is loaded,
        # and oshcc is present.
        #
        # --with-shmem=(cray|openshmem|openmpi|openmpi3|sgimpt|sgimptwrapper|spectrum)
        #

        ompi_root = get_software_root("OpenMPI")
        if ompi_root:
            oshcc_path = which("oshcc")
            # Avoid picking up a oshcc outside of the module
            if oshcc_path and ompi_root in oshcc_path:
                self.cfg.update('configopts', "--with-shmem=openmpi3")
                return

        self.cfg.update('configopts', '--without-shmem')

    def _determine_dependencies_cubelib(self):
        """
        Provides a dict for CubeLib dependencies which, in a nested dict,
        provide configure options if dependency is present, or lacking.
        """
        return {
            'zlib': {
                True: ['--with-frontend-zlib=%s'],
                False: ['--without-frontend-zlib'],
            },
        }

    def _determine_dependencies_cubegui(self):
        """
        Provides a dict for CubeGUI dependencies which, in a nested dict,
        provide configure options if dependency is present, or lacking.
        """
        return {
            'Qt': {
                 True: ['--with-qt=%s/bin'],
                 False: ['--without-qt'],
            },
            'Qt5': {
                 True: ['--with-qt=%s/bin'],
                 False: ['--without-qt'],
            },
            'Qt6': {
                 True: ['--with-qt=%s/bin'],
                 False: ['--without-qt'],
            },
        }

    def _determine_dependencies_cubew(self):
        """
        Provides a dict for CubeWriter dependencies which, in a nested dict,
        provide configure options if dependency is present, or lacking.
        """
        return {
            'zlib': {
                True: ['--with-backend-zlib=%s'],
                False: ['--without-backend-zlib'],
            }
        }

    def _determine_dependencies_otf2(self):
        """
        Provides a dict for OTF2 dependencies which, in a nested dict,
        provide configure options if dependency is present, or lacking.
        """
        return {
            'SIONlib': {
                True: ['--with-sionlib=%s/bin'],
                False: ['--without-sionlib'],
            },
        }

    def _determine_dependencies_scorep(self):
        """
        Provides a dict for Score-P dependencies which, in a nested dict,
        provide configure options if dependency is present, or lacking.
        """
        deps = {
            'binutils': {
                True: ['--with-libbfd-include=%s/include',
                       '--with-libbfd-lib=%%s/%s' % get_software_libdir('binutils', fs=['libbfd.a'])],
                False: ['--without-libbfd'],
            },
            'libunwind': {
                True: ['--with-libunwind=%s'],
                False: ['--without-libunwind'],
            },
            'CubeLib': {
                True: ['--with-cubelib=%s/bin'],
                False: ['--without-cubelib']
            },
            'CubeWriter': {
                True: ['--with-cubew=%s/bin'],
                False: ['--without-cubew'],
            },
            'CUDA': {
                True: ['--enable-cuda', '--with-libcudart=%s'],
                False: ['--disable-cuda'],
            },
            'OTF2': {
                True: ['--with-otf2=%s/bin'],
                False: ['--without-otf2'],
            },
            'OPARI2': {
                True: ['--with-opari2=%s/bin'],
                False: ['--without-opari2'],
            },
            'PAPI': {
                True: ['--with-papi-header=%s/include',
                       '--with-papi-lib=%%s/%s' % get_software_libdir('PAPI')],
                False: ['--without-papi']
            },
            'HIP': {
                True: ['--with-libamdhip64=%s'],
                False: ['--without-libamdhip64'],
            },
            'rocm-smi': {
                True: ['--with-librocm_smi64=%s'],
                False: ['--without-librocm_smi64'],
            },
            'rocTracer': {
                True: ['--with-libroctracer64=%s'],
                False: ['--without-libroctracer64'],
            },
        }
        if self.version < LooseVersion('9.0'):
            deps.update({
                'PDT': {
                    True: ['--with-pdt=%s/bin'],
                    False: ['--without-pdt'],
                }
            })
        if self.version >= LooseVersion('9.0'):
            deps.update({
                'GOTCHA': {
                    True: ['--with-libgotcha=%s'],
                    False: ['--without-libgotcha'],
                }
            })
        if self.version >= LooseVersion('10.0'):
            deps.update({
                'PAPI': {
                    True: ['--with-libpapi-include=%s/include',
                           '--with-libpapi-lib=%%s/%s' % get_software_libdir('PAPI')],
                    False: ['--without-libpapi'],
                },
                'ROCProfiler-SDK': {
                    True: ['--enable-rocm-adapter --disable-hip-adapter',
                           '--with-librocprofiler-sdk=%s'],
                    False: ['--disable-rocm-adapter'],
                },
            })

        return deps

    def _determine_dependencies_scalasca(self):
        """
        Provides a dict for Scalasca dependencies which, in a nested dict,
        provide configure options if dependency is present, or lacking.
        """
        return {
            'CubeWriter': {
                True: ['--with-cubew=%s/bin'],
                False: ['--without-cubew']
            },
            'OTF2': {
                True: ['--with-otf2=%s/bin'],
                False: ['--without-otf2'],
            }
        }

    def _determine_dependencies(self):
        """
        Sets, based on determined dependencies of the software, configure flags to
        be passed as 'configopts' during the build process.
        Filtered dependencies will be skipped, and need to be provided by a hook, or
        need to rely on auto-detection instead.
        """
        # Auto-detection for dependencies mostly works fine, but hard specify paths anyway to have full control
        if self.name == "CubeLib":
            deps = self._determine_dependencies_cubelib()
        elif self.name == "CubeGUI":
            deps = self._determine_dependencies_cubegui()
        elif self.name == "CubeWriter":
            deps = self._determine_dependencies_cubew()
        elif self.name == "OTF2":
            deps = self._determine_dependencies_otf2()
        elif self.name == "Score-P":
            deps = self._determine_dependencies_scorep()
        elif self.name == "Scalasca":
            deps = self._determine_dependencies_scalasca()
        else:
            raise EasyBuildError(f"Unexpected software name {self.name} for this EasyBlock")

        filtered_deps = build_option('filter_deps') or []
        # Go through all dependencies to determine which flags to pass explicitly to configure.
        for dep_name, dep_opts in deps.items():
            # In case a dependency is filtered, let either the hook or auto-detection handle
            # finding the library.
            if dep_name in filtered_deps:
                continue
            # Decide by software root if we want to enable a feature
            dep_root = get_software_root(dep_name)
            if dep_root:
                for configure_opt in dep_opts[True]:
                    # Substitute string by dependency root, if necessary.
                    if '%s' in configure_opt:
                        self.cfg.update('configopts', configure_opt % dep_root)
                    else:
                        self.cfg.update('configopts', configure_opt)
            else:
                self.cfg.update('configopts', dep_opts[False])

    def _enable_features(self):
        """
        Enable additional software features, based on passed config flags in the EasyConfig,
        or build options on the command line.
        For Score-P, one particular exception is Libwrap, which will also pass --with-llvm.
        This eases the dependency handling, since LLVM can be provided in multiple ways.
        """

        # Enables debug output via an environment variable, for the cost of additional overhead
        if self.cfg['enable_debug']:
            self.cfg.update('configopts', "--enable-debug")
        # More tests
        if self.cfg['enable_detailed_tests']:
            self.cfg.update('configopts', "--enable-backend-test-runs")

        if self.name == "Score-P":
            if LooseVersion(self.version) >= LooseVersion('10.0'):
                # Never try to download missing dependencies during configure / build
                self.cfg.update('configopts', '--disable-download-externals')

                # Disables Fortran instrumentation
                fortran_switch = "enable" if self.cfg['enable_fortran'] else "disable"
                self.cfg.update('configopts', f'--{fortran_switch}-fortran')

                # Disables Fortran MPI 2008 instrumentation, e.g. helpful if MPI does not provide
                # sufficient functionality.
                # Can only be enabled when we're using a MPI toolchain
                mpi_fam = self.toolchain.mpi_family()
                mpif08_switch = "enable" if self.cfg['enable_mpi_f08'] and mpi_fam is not None else "disable"
                self.cfg.update('configopts', f'--{mpif08_switch}-mpif08')

            # Enable / disable compiler instrumentation plugins. Should generally preferred to be
            # enabled, but could be disabled in the case of issues between the plugin and the
            # compiler version.
            comp_fam = self.toolchain.comp_family()
            compiler_plugin_switch = "enable" if self.cfg['enable_compiler_plugin'] else "disable"
            if (comp_fam == toolchain.LLVM or comp_fam == toolchain.ROCM) \
                    and LooseVersion(self.version) >= LooseVersion('9.0'):
                self.cfg.update('configopts', f"--{compiler_plugin_switch}-llvm-plugin")
            elif comp_fam == toolchain.GCC:
                self.cfg.update('configopts', f"--{compiler_plugin_switch}-gcc-plugin")

            # Libwrap generator may be built with either ROCm-LLVM or LLVM. Hence, we
            # cannot provide that option as part of the _determine_dependencies dict.
            # Handle separately here.
            llvm_root = get_software_root('LLVM')
            rocm_llvm_root = get_software_root('ROCm-LLVM')
            if llvm_root:
                self.cfg.update('configopts', f'--with-llvm={llvm_root}/bin')
            elif rocm_llvm_root:
                self.cfg.update('configopts', f'--with-llvm={rocm_llvm_root}/bin')

    def configure_step(self, *args, **kwargs):
        """Configure the build, set configure options for compiler, MPI and dependencies."""

        # Remove some settings from the environment, as they interfere with
        # Score-P's configure magic...
        unset_env_vars(['CPPFLAGS', 'LDFLAGS', 'LIBS'])

        self._patch_deficiencies()
        self._determine_toolchain()
        if self.name in ["Score-P", "Scalasca"]:
            self._determine_mpi()
        if self.name in ["Score-P"]:
            self._determine_shmem()
        self._determine_dependencies()
        self._enable_features()

        super().configure_step(*args, **kwargs)

    def test_step(self, *args, **kwargs):
        if self.cfg['runtest']:
            # Remove some settings from the environment, as they interfere with
            # Score-P's expected environment...
            unset_env_vars(['CPPFLAGS', 'LDFLAGS', 'LIBS'])
            self.cfg['runtest'] = 'check'

        super().test_step(*args, **kwargs)

    def post_processing_step(self, *args, **kwargs):
        super().post_processing_step(*args, **kwargs)

        if self.cfg['enable_post_install_tests']:
            # Remove some settings from the environment, as they interfere with
            # Score-P's expected environment...
            unset_env_vars(['CPPFLAGS', 'LDFLAGS', 'LIBS'])

            # make installcheck needs to run from the build directory,
            # as some files were generated during the configure process.
            cmd = 'make installcheck'
            run_shell_cmd(cmd, work_dir=self.start_dir)
