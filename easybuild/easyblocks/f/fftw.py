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
EasyBuild support for building and installing FFTW, implemented as an easyblock

@author: Kenneth Hoste (HPC-UGent)
"""
from distutils.version import LooseVersion

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.toolchains.compiler.gcc import TC_CONSTANT_GCC
from easybuild.toolchains.compiler.fujitsu import TC_CONSTANT_FUJITSU
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_version
from easybuild.tools.systemtools import AARCH32, AARCH64, POWER, X86_64
from easybuild.tools.systemtools import get_cpu_architecture, get_cpu_features, get_shared_lib_ext
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC
from easybuild.tools.utilities import nub


# AVX*, FMA4 (AMD Bulldozer+ only), SSE2 (x86_64 only)
FFTW_CPU_FEATURE_FLAGS_SINGLE_DOUBLE = ['avx', 'avx2', 'avx512', 'fma4', 'sse2', 'vsx']
# Altivec (POWER), SSE (x86), NEON (ARM), FMA (x86_64)
# asimd is CPU feature for extended NEON on AARCH64
FFTW_CPU_FEATURE_FLAGS = FFTW_CPU_FEATURE_FLAGS_SINGLE_DOUBLE + ['altivec', 'asimd', 'neon', 'sse', 'sve']
FFTW_PRECISION_FLAGS = ['single', 'double', 'long-double', 'quad-precision']


class EB_FFTW(ConfigureMake):
    """Support for building/installing FFTW."""

    @staticmethod
    def _prec_param(prec):
        """Determine parameter name for specified precision"""
        return 'with_%s_prec' % prec.replace('-', '_').replace('_precision', '')

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for FFTW."""
        extra_vars = {
            'auto_detect_cpu_features': [True, "Auto-detect available CPU features, and configure accordingly", CUSTOM],
            'use_fma': [None, "Configure with --enable-avx-128-fma (DEPRECATED, use 'use_fma4' instead)", CUSTOM],
            'with_mpi': [True, "Enable building of FFTW MPI library", CUSTOM],
            'with_openmp': [True, "Enable building of FFTW OpenMP library", CUSTOM],
            'with_shared': [True, "Enable building of shared FFTW libraries", CUSTOM],
            'with_threads': [True, "Enable building of FFTW threads library", CUSTOM],
        }

        for flag in FFTW_CPU_FEATURE_FLAGS:
            if flag == 'fma4':
                conf_opt = 'avx-128-fma'
            else:
                conf_opt = flag

            help_msg = "Configure with --enable-%s (if None, auto-detect support for %s)" % (conf_opt, flag.upper())
            extra_vars['use_%s' % flag] = [None, help_msg, CUSTOM]

        for prec in FFTW_PRECISION_FLAGS:
            help_msg = "Enable building of %s precision library" % prec.replace('-precision', '')
            extra_vars[EB_FFTW._prec_param(prec)] = [True, help_msg, CUSTOM]

        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for FFTW."""
        super(EB_FFTW, self).__init__(*args, **kwargs)

        # do not enable MPI if the toolchain does not support it
        if not self.toolchain.mpi_family():
            self.log.info("Disabling MPI support because the toolchain used does not support it.")
            self.cfg['with_mpi'] = False

        for flag in FFTW_CPU_FEATURE_FLAGS:
            # fail-safe: make sure we're not overwriting an existing attribute (could lead to weird bugs if we do)
            if hasattr(self, flag):
                raise EasyBuildError("EasyBlock attribute '%s' already exists")
            setattr(self, flag, self.cfg['use_%s' % flag])

            # backwards compatibility: use use_fma setting if use_fma4 is not set
            if flag == 'fma4' and self.cfg['use_fma4'] is None and self.cfg['use_fma'] is not None:
                self.log.deprecated("Use 'use_fma4' instead of 'use_fma' easyconfig parameter", '4.0')
                self.fma4 = self.cfg['use_fma']

        # auto-detect CPU features that can be used and are not enabled/disabled explicitly,
        # but only if --optarch=GENERIC is not being used
        cpu_arch = get_cpu_architecture()
        if self.cfg['auto_detect_cpu_features']:

            # if --optarch=GENERIC is used, limit which CPU features we consider for auto-detection
            if build_option('optarch') == OPTARCH_GENERIC:
                if cpu_arch == X86_64:
                    # SSE(2) is supported on all x86_64 architectures
                    cpu_features = ['sse', 'sse2']
                elif cpu_arch == AARCH64:
                    # NEON is supported on all AARCH64 architectures (indicated with 'asimd')
                    cpu_features = ['asimd']
                else:
                    cpu_features = []
            else:
                cpu_features = FFTW_CPU_FEATURE_FLAGS
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

        # Auto-disable quad-precision on ARM and POWER, as it is unsupported
        if self.cfg['with_quad_prec'] and cpu_arch in [AARCH32, AARCH64, POWER]:
            self.cfg['with_quad_prec'] = False
            self.log.debug("Quad-precision automatically disabled; not supported on %s.", cpu_arch)

    def run_all_steps(self, *args, **kwargs):
        """
        Put configure options in place for different precisions (single, double, long double, quad).
        """
        # keep track of configopts specified in easyconfig file, so we can include them in each iteration later
        common_config_opts = self.cfg['configopts']

        self.cfg['configopts'] = []

        for prec in FFTW_PRECISION_FLAGS:
            if self.cfg[EB_FFTW._prec_param(prec)]:

                prec_configopts = []

                # double precison is the default, no configure flag needed (there is no '--enable-double')
                if prec != 'double':
                    prec_configopts.append('--enable-%s' % prec)

                # MPI is not supported for quad precision
                if prec != 'quad-precision' and self.cfg['with_mpi']:
                    prec_configopts.append('--enable-mpi')

                if self.toolchain.options['pic']:
                    prec_configopts.append('--with-pic')

                for libtype in ['openmp', 'shared', 'threads']:
                    if self.cfg['with_%s' % libtype]:
                        prec_configopts.append('--enable-%s' % libtype)

                # SSE2, AVX* only supported for single/double precision
                if prec in ['single', 'double']:
                    for flag in FFTW_CPU_FEATURE_FLAGS_SINGLE_DOUBLE:
                        if getattr(self, flag):
                            if flag == 'fma4':
                                prec_configopts.append('--enable-avx-128-fma')
                            else:
                                prec_configopts.append('--enable-%s' % flag)

                # Altivec (POWER) and SSE only for single precision
                for flag in ['altivec', 'sse']:
                    if prec == 'single' and getattr(self, flag):
                        prec_configopts.append('--enable-%s' % flag)

                if self.sve:
                    # SVE (ARM) only for single precision and double precision (on AARCH64 if sve feature is present)
                    if prec == 'single' or prec == 'double':
                        prec_configopts.append('--enable-fma --enable-sve --enable-armv8-cntvct-el0')
                elif self.asimd or self.neon:
                    # NEON (ARM) only for single precision and double precision (on AARCH64)
                    if prec == 'single' or (prec == 'double' and self.asimd):
                        prec_configopts.append('--enable-neon')

                # For POWER with GCC 5/6/7 and FFTW/3.3.6 we need to disable some settings for tests to pass
                # (we do it last so as not to affect previous logic)
                cpu_arch = get_cpu_architecture()
                comp_fam = self.toolchain.comp_family()
                fftw_ver = LooseVersion(self.version)
                if cpu_arch == POWER and comp_fam == TC_CONSTANT_GCC:
                    # See https://github.com/FFTW/fftw3/issues/59 which applies to GCC 5 and above
                    # Upper bound of 3.4 (as of yet unreleased) in hope there will eventually be a fix.
                    if prec == 'single' and fftw_ver < LooseVersion('3.4'):
                        self.log.info("Disabling altivec for single precision on POWER with GCC for FFTW/%s"
                                      % self.version)
                        prec_configopts.append('--disable-altivec')
                    # Issue with VSX has been solved in FFTW/3.3.7
                    if prec == 'double' and fftw_ver <= LooseVersion('3.3.6'):
                        self.log.info("Disabling vsx for double precision on POWER with GCC for FFTW/%s" % self.version)
                        prec_configopts.append('--disable-vsx')

                # Fujitsu specific flags (from build instructions at https://github.com/fujitsu/fftw3)
                if self.toolchain.comp_family() == TC_CONSTANT_FUJITSU:
                    prec_configopts.append('CFLAGS="-Ofast"')
                    prec_configopts.append('FFLAGS="-Kfast"')
                    prec_configopts.append('ac_cv_prog_f77_v="-###"')
                    if self.cfg['with_openmp']:
                        prec_configopts.append('OPENMP_CFLAGS="-Kopenmp"')

                # append additional configure options (may be empty string, but that's OK)
                self.cfg.update('configopts', [' '.join(prec_configopts) + ' ' + common_config_opts])

        self.log.debug("List of configure options to iterate over: %s", self.cfg['configopts'])

        return super(EB_FFTW, self).run_all_steps(*args, **kwargs)

    def test_step(self):
        """Custom implementation of test step for FFTW."""

        if self.toolchain.mpi_family() is not None and not build_option('mpi_tests'):
            self.log.info("Skipping testing of FFTW since MPI testing is disabled")
            return

        if self.toolchain.mpi_family() == toolchain.OPENMPI and not self.toolchain.comp_family() == TC_CONSTANT_FUJITSU:

            # allow oversubscription of number of processes over number of available cores with OpenMPI 3.0 & newer,
            # to avoid that some tests fail if only a handful of cores are available
            ompi_ver = get_software_version('OpenMPI')
            if LooseVersion(ompi_ver) >= LooseVersion('3.0'):
                if 'OMPI_MCA_rmaps_base_oversubscribe' not in self.cfg['pretestopts']:
                    self.cfg.update('pretestopts', "export OMPI_MCA_rmaps_base_oversubscribe=true && ")

        super(EB_FFTW, self).test_step()

    def sanity_check_step(self, mpionly=False):
        """Custom sanity check for FFTW. mpionly=True only for FFTW.MPI"""

        custom_paths = {
            'files': ['include/fftw3.f', 'include/fftw3.h'],
            'dirs': [],
        }
        if not mpionly:
            custom_paths['files'].insert(0, 'bin/fftw-wisdom-to-conf')
            custom_paths['dirs'].insert(0, 'lib/pkgconfig')

        shlib_ext = get_shared_lib_ext()

        extra_files = []
        for (prec, letter) in [('double', ''), ('long_double', 'l'), ('quad', 'q'), ('single', 'f')]:
            if self.cfg['with_%s_prec' % prec]:

                # precision-specific binaries
                if not mpionly:
                    extra_files.append('bin/fftw%s-wisdom' % letter)

                # precision-specific .f03 header files
                inc_f03 = 'include/fftw3%s.f03' % letter
                if prec == 'single':
                    # no separate .f03 header file for single/double precision
                    inc_f03 = 'include/fftw3.f03'
                extra_files.append(inc_f03)

                # libraries, one for each precision and variant (if enabled)
                if mpionly:
                    variantlist = ['mpi']
                else:
                    variantlist = ['', 'mpi', 'openmp', 'threads']
                for variant in variantlist:
                    if variant == 'openmp':
                        suff = '_omp'
                    elif variant == '':
                        suff = ''
                    else:
                        suff = '_' + variant

                    # MPI is not compatible with quad precision
                    if variant == '' or self.cfg['with_%s' % variant] and not (prec == 'quad' and variant == 'mpi'):
                        extra_files.append('lib/libfftw3%s%s.a' % (letter, suff))
                        if self.cfg['with_shared']:
                            extra_files.append('lib/libfftw3%s%s.%s' % (letter, suff, shlib_ext))

        # some additional files to check for when MPI is enabled
        if self.cfg['with_mpi']:
            extra_files.extend(['include/fftw3-mpi.f03', 'include/fftw3-mpi.h'])
            if self.cfg['with_long_double_prec']:
                extra_files.append('include/fftw3l-mpi.f03')

        custom_paths['files'].extend(nub(extra_files))

        super(EB_FFTW, self).sanity_check_step(custom_paths=custom_paths)
