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
EasyBuild support for installing the Intel MPI library, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Damian Alvarez (Forschungszentrum Juelich GmbH)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os
import tempfile
from easybuild.tools import LooseVersion

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, extract_file
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS, get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.tools.toolchain.mpi import get_mpi_cmd_template


class EB_impi(IntelBase):
    """
    Support for installing Intel MPI library
    - minimum version suported: 2018.x
    """
    @staticmethod
    def extra_options():
        extra_vars = {
            'libfabric_configopts': ['', 'Configure options for the provided libfabric', CUSTOM],
            'libfabric_rebuild': [True, 'Try to rebuild internal libfabric instead of using provided binary', CUSTOM],
            'ofi_internal': [True, 'Use internal shipped libfabric instead of external libfabric', CUSTOM],
            'set_mpi_wrappers_compiler': [False, 'Override default compiler used by MPI wrapper commands', CUSTOM],
            'set_mpi_wrapper_aliases_gcc': [False, 'Set compiler for mpigcc/mpigxx via aliases', CUSTOM],
            'set_mpi_wrapper_aliases_intel': [False, 'Set compiler for mpiicc/mpiicpc/mpiifort via aliases', CUSTOM],
            'set_mpi_wrappers_all': [False, 'Set (default) compiler for all MPI wrapper commands', CUSTOM],
        }
        return IntelBase.extra_options(extra_vars)

    def prepare_step(self, *args, **kwargs):
        kwargs['requires_runtime_license'] = False
        super(EB_impi, self).prepare_step(*args, **kwargs)

    def install_step(self):
        """
        Actual installation
        - create silent cfg file
        - execute command
        """
        impiver = LooseVersion(self.version)

        if impiver < LooseVersion('2018'):
            raise EasyBuildError(
                f"Version {self.version} of {self.name} is unsupported. Mininum supported version is 2018.0."
            )

        if impiver >= LooseVersion('2021'):
            super(EB_impi, self).install_step()
        else:
            # impi starting from version 4.0.1.x uses standard installation procedure.
            silent_cfg_names_map = {}
            super(EB_impi, self).install_step(silent_cfg_names_map=silent_cfg_names_map)
            # since v5.0.1 installers create impi/<version> subdir, so stuff needs to be moved afterwards
            super(EB_impi, self).move_after_install()

        # recompile libfabric (if requested)
        # some Intel MPI versions (like 2019 update 6) no longer ship libfabric sources
        libfabric_path = os.path.join(self.installdir, 'libfabric')
        if impiver >= LooseVersion('2019') and self.cfg['libfabric_rebuild']:
            if self.cfg['ofi_internal']:
                libfabric_src_tgz_fn = 'src.tgz'
                if os.path.exists(os.path.join(libfabric_path, libfabric_src_tgz_fn)):
                    change_dir(libfabric_path)
                    srcdir = extract_file(libfabric_src_tgz_fn, os.getcwd(), change_into_dir=False)
                    change_dir(srcdir)
                    libfabric_installpath = os.path.join(self.installdir, 'intel64', 'libfabric')

                    make = 'make'
                    if self.cfg.parallel > 1:
                        make += f' -j {self.cfg.parallel}'

                    cmds = [
                        f"./configure --prefix={libfabric_installpath} {self.cfg['libfabric_configopts']}",
                        make,
                        "make install",
                    ]
                    for cmd in cmds:
                        run_shell_cmd(cmd)
                else:
                    self.log.info("Rebuild of libfabric is requested, but %s does not exist, so skipping...",
                                  libfabric_src_tgz_fn)
            else:
                raise EasyBuildError("Rebuild of libfabric is requested, but ofi_internal is set to False.")

    def post_processing_step(self):
        """Custom post install step for IMPI, fix broken env scripts after moving installed files."""
        super(EB_impi, self).post_processing_step()

        impiver = LooseVersion(self.version)

        if impiver >= LooseVersion('2021'):
            self.log.info("No post-install action for impi v%s", self.version)
        else:
            script_paths = [os.path.join('intel64', 'bin')]
            # fix broken env scripts after the move
            regex_subs = [(r"^setenv I_MPI_ROOT.*", r"setenv I_MPI_ROOT %s" % self.installdir)]
            for script in [os.path.join(script_path, 'mpivars.csh') for script_path in script_paths]:
                apply_regex_substitutions(os.path.join(self.installdir, script), regex_subs)
            regex_subs = [(r"^(\s*)I_MPI_ROOT=[^;\n]*", r"\1I_MPI_ROOT=%s" % self.installdir)]
            for script in [os.path.join(script_path, 'mpivars.sh') for script_path in script_paths]:
                apply_regex_substitutions(os.path.join(self.installdir, script), regex_subs)

            # fix 'prefix=' in compiler wrapper scripts after moving installation (see install_step)
            wrappers = ['mpif77', 'mpif90', 'mpigcc', 'mpigxx', 'mpiicc', 'mpiicpc', 'mpiifort']
            regex_subs = [(r"^prefix=.*", r"prefix=%s" % self.installdir)]
            for script_dir in script_paths:
                for wrapper in wrappers:
                    wrapper_path = os.path.join(self.installdir, script_dir, wrapper)
                    if os.path.exists(wrapper_path):
                        apply_regex_substitutions(wrapper_path, regex_subs)

    def sanity_check_step(self):
        """Custom sanity check paths for IMPI."""

        impi_ver = LooseVersion(self.version)

        suff = '64'

        mpi_mods = ['mpi.mod', 'mpi_base.mod', 'mpi_constants.mod', 'mpi_sizeofs.mod']

        if impi_ver >= LooseVersion('2021'):
            mpi_subdir = self.get_versioned_subdir('mpi')
            bin_dir = os.path.join(mpi_subdir, 'bin')
            include_dir = os.path.join(mpi_subdir, 'include')
            lib_dir = os.path.join(mpi_subdir, 'lib')
            if impi_ver < LooseVersion('2021.11'):
                lib_dir = os.path.join(lib_dir, 'release')
        elif impi_ver >= LooseVersion('2019'):
            bin_dir = os.path.join('intel64', 'bin')
            include_dir = os.path.join('intel64', 'include')
            lib_dir = os.path.join('intel64', 'lib', 'release')
        else:
            bin_dir = 'bin%s' % suff
            include_dir = 'include%s' % suff
            lib_dir = 'lib%s' % suff
            mpi_mods.extend(['i_malloc.h'])

        mpi_mods_dir = include_dir
        if impi_ver >= LooseVersion('2021.11'):
            mpi_mods_dir = os.path.join(mpi_mods_dir, 'mpi')

        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [os.path.join(bin_dir, 'mpi%s' % x) for x in ['icc', 'icpc', 'ifort']] +
            [os.path.join(include_dir, 'mpi%s.h' % x) for x in ['cxx', 'f', '', 'o', 'of']] +
            [os.path.join(mpi_mods_dir, x) for x in mpi_mods] +
            [os.path.join(lib_dir, 'libmpi.%s' % shlib_ext)] +
            [os.path.join(lib_dir, 'libmpi.a')],
            'dirs': [],
        }

        custom_commands = []

        if build_option('mpi_tests'):
            # Add minimal test program to sanity checks
            if build_option('sanity_check_only'):
                # When only running the sanity check we need to manually make sure that
                # variables for compilers and parallelism have been set
                self.set_parallel()
                self.prepare_step(start_dir=False)

                impi_testexe = os.path.join(tempfile.mkdtemp(), 'mpi_test')
            else:
                impi_testexe = os.path.join(self.builddir, 'mpi_test')

            if impi_ver >= LooseVersion('2021'):
                impi_testsrc = os.path.join(self.installdir, self.get_versioned_subdir('mpi'))
                if impi_ver >= LooseVersion('2021.11'):
                    impi_testsrc = os.path.join(impi_testsrc, 'opt', 'mpi')
                impi_testsrc = os.path.join(impi_testsrc, 'test', 'test.c')
            else:
                impi_testsrc = os.path.join(self.installdir, 'test', 'test.c')

            self.log.info("Adding minimal MPI test program to sanity checks: %s", impi_testsrc)

            # Build test program with appropriate compiler from current toolchain
            build_cmd = "mpicc -cc=%s %s -o %s" % (os.getenv('CC'), impi_testsrc, impi_testexe)

            # Execute test program with appropriate MPI executable for target toolchain
            params = {'nr_ranks': self.cfg.parallel, 'cmd': impi_testexe}
            mpi_cmd_tmpl, params = get_mpi_cmd_template(toolchain.INTELMPI, params, mpi_version=self.version)

            custom_commands.extend([
                build_cmd,  # build test program
                mpi_cmd_tmpl % params,  # run test program
            ])

        super(EB_impi, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_step(self, *args, **kwargs):
        """
        Set paths for module load environment based on the actual installation files
        """
        manpath = 'man'
        fi_provider_path = None
        mic_library_path = None

        impi_ver = LooseVersion(self.version)
        if impi_ver >= LooseVersion('2021'):
            mpi_subdir = self.get_versioned_subdir('mpi')
            path_dirs = [
                os.path.join(mpi_subdir, 'bin'),
                os.path.join(mpi_subdir, 'libfabric', 'bin'),
            ]
            lib_dirs = [
                os.path.join(mpi_subdir, 'lib'),
                os.path.join(mpi_subdir, 'libfabric', 'lib'),
            ]
            if impi_ver < LooseVersion('2021.11'):
                lib_dirs.insert(1, os.path.join(mpi_subdir, 'lib', 'release'))
            include_dirs = [os.path.join(mpi_subdir, 'include')]

            if impi_ver >= LooseVersion('2021.11'):
                manpath = os.path.join(mpi_subdir, 'share', 'man')
            else:
                manpath = os.path.join(mpi_subdir, 'man')

            if self.cfg['ofi_internal']:
                lib_dirs.append(os.path.join(mpi_subdir, 'libfabric', 'lib'))
                path_dirs.append(os.path.join(mpi_subdir, 'libfabric', 'bin'))
                fi_provider_path = [os.path.join(mpi_subdir, 'libfabric', 'lib', 'prov')]

        elif impi_ver >= LooseVersion('2019'):
            path_dirs = [os.path.join('intel64', 'bin')]
            # The "release" library is default in v2019. Give it precedence over intel64/lib.
            # (remember paths are *prepended*, so the last path in the list has highest priority)
            lib_dirs = [
                os.path.join('intel64', 'lib'),
                os.path.join('intel64', 'lib', 'release'),
            ]
            include_dirs = [os.path.join('intel64', 'include')]

            if self.cfg['ofi_internal']:
                lib_dirs.append(os.path.join('intel64', 'libfabric', 'lib'))
                path_dirs.append(os.path.join('intel64', 'libfabric', 'bin'))
                fi_provider_path = [os.path.join('intel64', 'libfabric', 'lib', 'prov')]

        else:
            path_dirs = [os.path.join('bin', 'intel64'), 'bin64']
            lib_dirs = [os.path.join('lib', 'em64t'), 'lib64']
            include_dirs = ['include64']
            mic_library_path = [os.path.join('mic', 'lib')]

        self.module_load_environment.PATH = path_dirs
        self.module_load_environment.LD_LIBRARY_PATH = lib_dirs
        self.module_load_environment.LIBRARY_PATH = lib_dirs
        self.module_load_environment.MANPATH = [manpath]
        if fi_provider_path is not None:
            self.module_load_environment.FI_PROVIDER_PATH = fi_provider_path
        if mic_library_path is not None:
            self.module_load_environment.MIC_LD_LIBRARY_PATH = mic_library_path

        # include paths to headers (e.g. CPATH)
        self.module_load_environment.set_alias_vars(MODULE_LOAD_ENV_HEADERS, include_dirs)

        return super().make_module_step(*args, **kwargs)

    def make_module_extra(self, *args, **kwargs):
        """Overwritten from Application to add extra txt"""

        if LooseVersion(self.version) >= LooseVersion('2021'):
            mpiroot = os.path.join(self.installdir, self.get_versioned_subdir('mpi'))
        else:
            mpiroot = self.installdir

        txt = super(EB_impi, self).make_module_extra(*args, **kwargs)
        txt += self.module_generator.set_environment('I_MPI_ROOT', mpiroot)
        if self.cfg['set_mpi_wrappers_compiler'] or self.cfg['set_mpi_wrappers_all']:
            for var in ['CC', 'CXX', 'F77', 'F90', 'FC']:
                if var == 'FC':
                    # $FC isn't defined by EasyBuild framework, so use $F90 instead
                    src_var = 'F90'
                else:
                    src_var = var

                target_var = 'I_MPI_%s' % var

                val = os.getenv(src_var)
                if val:
                    txt += self.module_generator.set_environment(target_var, val)
                else:
                    raise EasyBuildError("Environment variable $%s not set, can't define $%s", src_var, target_var)

        if self.cfg['set_mpi_wrapper_aliases_gcc'] or self.cfg['set_mpi_wrappers_all']:
            # force mpigcc/mpigxx to use GCC compilers, as would be expected based on their name
            txt += self.module_generator.set_alias('mpigcc', 'mpigcc -cc=gcc')
            txt += self.module_generator.set_alias('mpigxx', 'mpigxx -cxx=g++')

        if self.cfg['set_mpi_wrapper_aliases_intel'] or self.cfg['set_mpi_wrappers_all']:
            # do the same for mpiicc/mpiipc/mpiifort to be consistent, even if they may not exist
            if (get_software_root('intel-compilers') and
                    LooseVersion(get_software_version('intel-compilers')) >= LooseVersion('2024')):
                txt += self.module_generator.set_alias('mpiicc', 'mpiicc -cc=icx')
                txt += self.module_generator.set_alias('mpiicpc', 'mpiicpc -cxx=icpx')
            else:
                txt += self.module_generator.set_alias('mpiicc', 'mpiicc -cc=icc')
                txt += self.module_generator.set_alias('mpiicpc', 'mpiicpc -cxx=icpc')
            # -fc also works, but -f90 takes precedence
            txt += self.module_generator.set_alias('mpiifort', 'mpiifort -f90=ifort')

            if LooseVersion(self.version) >= LooseVersion('2021.11'):
                txt += self.module_generator.set_alias('mpiicx', 'mpiicx -cc=icx')
                txt += self.module_generator.set_alias('mpiicpx', 'mpiicpx -cxx=icpx')
                txt += self.module_generator.set_alias('mpiifx', 'mpiifx -f90=ifx')

        # set environment variable UCX_TLS to 'all', this works in all hardware configurations
        # needed with UCX regardless of the transports available (even without a Mellanox HCA)
        # more information in easybuilders/easybuild-easyblocks#2253
        if get_software_root('UCX'):
            # do not overwrite settings in the easyconfig
            if 'UCX_TLS' not in self.cfg['modextravars']:
                txt += self.module_generator.set_environment('UCX_TLS', 'all')

        return txt
