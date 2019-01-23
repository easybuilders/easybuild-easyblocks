##
# Copyright 2009-2019 Ghent University
# Copyright 2019 Micael Oliveira
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
EasyBuild support for building and installing ELPA, implemented as an easyblock

@author: Micael Oliveira (MPSD-Hamburg)
"""
import os

from vsc.utils.missing import nub

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.systemtools import get_cpu_features, get_shared_lib_ext
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC
ELPA_CPU_FEATURE_FLAGS = ['avx', 'avx2', 'avx512', 'vsx', 'sse4_2']


class EB_ELPA(ConfigureMake):
    """Support for building/installing ELPA."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for ELPA."""
        extra_vars = {
            'auto_detect_cpu_features': [True, "Auto-detect available CPU features, and configure accordingly", CUSTOM],
            'with_mpi': [True, "Enable building of ELPA MPI library", CUSTOM],
            'with_openmp': [True, "Enable building of ELPA OpenMP library", CUSTOM],
            'with_shared': [True, "Enable building of shared ELPA libraries", CUSTOM],
            'with_single': [True, "Enable building of single precision ELPA functions", CUSTOM],
            'with_generic_kernel': [True, "Enable building of ELPA generic kernels", CUSTOM],
        }

        for flag in ELPA_CPU_FEATURE_FLAGS:
            if flag == 'sse4_2':
                conf_opt = ['sse', 'sse-assembly']
            else:
                conf_opt = [flag]

            for opt in conf_opt:
                help_msg = "Configure with --enable-%s (if None, auto-detect support for %s)" % (opt, flag.upper())
                extra_vars['use_%s' % flag] = [None, help_msg, CUSTOM]

        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for ELPA."""
        super(EB_ELPA, self).__init__(*args, **kwargs)

        # do not enable MPI if the toolchain does not support it
        if not self.toolchain.mpi_family():
            self.log.info("Disabling MPI support because the toolchain used does not support it.")
            self.cfg['with_mpi'] = False

        for flag in ELPA_CPU_FEATURE_FLAGS:
            # fail-safe: make sure we're not overwriting an existing attribute (could lead to weird bugs if we do)
            if hasattr(self, flag):
                raise EasyBuildError("EasyBlock attribute '%s' already exists")
            setattr(self, flag, self.cfg['use_%s' % flag])

        # auto-detect CPU features that can be used and are not enabled/disabled explicitly,
        # but only if --optarch=GENERIC is not being used
        if self.cfg['auto_detect_cpu_features']:

            # if --optarch=GENERIC is used, we will not use no CPU feature
            if build_option('optarch') == OPTARCH_GENERIC:
                cpu_features = []
            else:
                cpu_features = ELPA_CPU_FEATURE_FLAGS
            self.log.info("CPU features considered for auto-detection: %s", cpu_features)

            # get list of available CPU features, so we can check which ones to retain
            avail_cpu_features = get_cpu_features()

            # on macOS, AVX is indicated with 'avx1.0' rather than 'avx'
            if 'avx1.0' in avail_cpu_features:
                avail_cpu_features.append('avx')

            self.log.info("List of available CPU features: %s", avail_cpu_features)

            for flag in cpu_features:
                # only enable use of a particular CPU feature if it's still undecided (i.e. None)
                if getattr(self, flag) is None and flag in avail_cpu_features:
                    self.log.info("Enabling use of %s (should be supported based on CPU features)", flag.upper())
                    setattr(self, flag, True)

    def run_all_steps(self, *args, **kwargs):
        """
        Put configure options in place for different builds (serial, openmp, mpi, openmp+mpi).
        """

        # the following configopts are common to all builds
        if self.toolchain.options['pic']:
            self.cfg.update('configopts', '--with-pic')

        if self.cfg['with_shared']:
            self.cfg.update('configopts', '--enable-shared')

        if self.cfg['with_generic_kernel']:
            self.cfg.update('configopts', '--enable-generic')

        if self.cfg['with_single']:
            self.cfg.update('configopts', '--enable-single-precision')

        for flag in ELPA_CPU_FEATURE_FLAGS:
            # many ELPA kernels are enabled by default, even when the
            # CPU does not support them, so we disable them all, except
            # when the appropriate CPU flag is found
            # sse kernels require sse4_2
            if flag == 'sse4_2':
                if getattr(self, flag):
                    self.cfg.update('configopts','--enable-sse')
                    self.cfg.update('configopts', '--enable-sse-assembly')
                else:
                    self.cfg.update('configopts', '--disable-sse')
                    self.cfg.update('configopts', '--disable-sse-assembly')
            else:
                if getattr(self, flag):
                    self.cfg.update('configopts', '--enable-%s' % flag)
                else:
                    self.cfg.update('configopts', '--disable-%s' % flag)

        # make all builds verbose
        self.cfg.update('buildopts', 'V=1')

        # keep track of common configopts and of configopts specified in easyconfig file, so we can include them in each iteration later
        common_config_opts = self.cfg['configopts']
        common_build_opts = self.cfg['buildopts']

        self.cfg['configopts'] = []
        self.cfg['buildopts'] = []

        with_mpi_opts = [False]
        if self.cfg['with_mpi']:
            with_mpi_opts.append(True)

        with_omp_opts = [False]
        if self.cfg['with_openmp']:
            with_omp_opts.append(True)

        for with_mpi in with_mpi_opts:
            if with_mpi:
                mpi_configopt = '--with-mpi=yes'
                linalgopt = 'LIBS="$LIBSCALAPACK"'
            else:
                mpi_configopt = '--with-mpi=no'
                linalgopt = 'LIBS="$LIBLAPACK"'

            for with_omp in with_omp_opts:
                if with_omp:
                    omp_configopt = '--enable-openmp'
                else:
                    omp_configopt = '--disable-openmp'

                # append additional configure and build options
                self.cfg.update('configopts', [mpi_configopt + ' ' + omp_configopt + ' ' + linalgopt + ' ' + common_config_opts])
                self.cfg.update('buildopts', [linalgopt + ' ' + common_build_opts])

        self.log.debug("List of configure options to iterate over: %s", self.cfg['configopts'])
        self.log.debug("List of build options to iterate over: %s", self.cfg['buildopts'])

        return super(EB_ELPA, self).run_all_steps(*args, **kwargs)

    def sanity_check_step(self):
        """Custom sanity check for ELPA."""

        custom_paths = {
            'dirs': ['lib/pkgconfig', 'bin'],
        }

        shlib_ext = get_shared_lib_ext()

        extra_files = []

        with_mpi_opts = [False]
        if self.cfg['with_mpi']:
            with_mpi_opts.append(True)

        with_omp_opts = [False]
        if self.cfg['with_openmp']:
            with_omp_opts.append(True)

        for with_mpi in with_mpi_opts:
            if with_mpi:
                mpi_suff = ''
            else:
                mpi_suff = '_onenode'

            for with_omp in with_omp_opts:
                if with_omp:
                    omp_suff = '_openmp'
                else:
                    omp_suff = ''

                extra_files.append('include/elpa%s%s-%s/elpa/elpa.h' % (mpi_suff, omp_suff, self.version))
                extra_files.append('include/elpa%s%s-%s/modules/elpa.mod' % (mpi_suff, omp_suff, self.version))

                extra_files.append('lib/libelpa%s%s.a' % (mpi_suff, omp_suff))
                if self.cfg['with_shared']:
                    extra_files.append('lib/libelpa%s%s.%s' % (mpi_suff, omp_suff, shlib_ext))

        custom_paths['files'] = nub(extra_files)

        super(EB_ELPA, self).sanity_check_step(custom_paths=custom_paths)
