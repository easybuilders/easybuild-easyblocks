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
EasyBuild support for building and installing GROMACS, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Ward Poelmans (Ghent University)
@author: Benjamin Roberts (The University of Auckland)
@author: Luca Marsella (CSCS)
@author: Guilherme Peretti-Pezzi (CSCS)
@author: Oliver Stueker (Compute Canada/ACENET)
@author: Davide Vanzo (Vanderbilt University)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import glob
import os
import re
import shutil

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import copy_dir, find_backup_name_candidate, remove_dir, which
from easybuild.tools.modules import get_software_libdir, get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import X86_64, get_cpu_architecture, get_cpu_features, get_shared_lib_ext
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC
from easybuild.tools.utilities import nub
from easybuild.tools.version import VERBOSE_VERSION as EASYBUILD_VERSION


class EB_GROMACS(CMakeMake):
    """Support for building/installing GROMACS."""

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'double_precision': [None, "Build with double precision enabled (-DGMX_DOUBLE=ON), " +
                                 "default is to build double precision unless CUDA is enabled", CUSTOM],
            'single_precision': [True, "Build with single precision enabled (-DGMX_DOUBLE=OFF), " +
                                 "default is to build single precision", CUSTOM],
            'mpisuffix': ['_mpi', "Suffix to append to MPI-enabled executables (only for GROMACS < 4.6)", CUSTOM],
            'mpiexec': ['mpirun', "MPI executable to use when running tests", CUSTOM],
            'mpiexec_numproc_flag': ['-np', "Flag to introduce the number of MPI tasks when running tests", CUSTOM],
            'mpi_numprocs': [0, "Number of MPI tasks to use when running tests", CUSTOM],
            'ignore_plumed_version_check': [False, "Ignore the version compatibility check for PLUMED", CUSTOM],
            'plumed': [None, "Try to apply PLUMED patches. None (default) is auto-detect. " +
                       "True or False forces behaviour.", CUSTOM],
        })
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize GROMACS-specific variables."""
        super(EB_GROMACS, self).__init__(*args, **kwargs)

        self._lib_subdirs = []  # list of directories with libraries

        self.pre_env = ''
        self.cfg['build_shared_libs'] = self.cfg.get('build_shared_libs', False)

        if LooseVersion(self.version) >= LooseVersion('2019'):
            # Building the gmxapi interface requires shared libraries
            self.cfg['build_shared_libs'] = True

        if self.cfg['build_shared_libs']:
            self.libext = get_shared_lib_ext()
        else:
            self.libext = 'a'

    def get_gromacs_arch(self):
        """Determine value of GMX_SIMD CMake flag based on optarch string.

        Refs:
        [0] http://manual.gromacs.org/documentation/2016.3/install-guide/index.html#typical-installation
        [1] http://manual.gromacs.org/documentation/2016.3/install-guide/index.html#simd-support
        [2] http://www.gromacs.org/Documentation/Acceleration_and_parallelization
        """
        # default: fall back on autodetection
        res = None

        optarch = build_option('optarch') or ''
        # take into account that optarch value is a dictionary if it is specified by compiler family
        if isinstance(optarch, dict):
            comp_fam = self.toolchain.comp_family()
            optarch = optarch.get(comp_fam, '')
        optarch = optarch.upper()

        # The list of GMX_SIMD options can be found
        # http://manual.gromacs.org/documentation/2018/install-guide/index.html#simd-support
        if 'MIC-AVX512' in optarch and LooseVersion(self.version) >= LooseVersion('2016'):
            res = 'AVX_512_KNL'
        elif 'AVX512' in optarch and LooseVersion(self.version) >= LooseVersion('2016'):
            res = 'AVX_512'
        elif 'AVX2' in optarch and LooseVersion(self.version) >= LooseVersion('5.0'):
            res = 'AVX2_256'
        elif 'AVX' in optarch:
            res = 'AVX_256'
        elif 'SSE3' in optarch or 'SSE2' in optarch or 'MARCH=NOCONA' in optarch:
            # Gromacs doesn't have any GMX_SIMD=SSE3 but only SSE2 and SSE4.1 [1].
            # According to [2] the performance difference between SSE2 and SSE4.1 is minor on x86
            # and SSE4.1 is not supported by AMD Magny-Cours[1].
            res = 'SSE2'
        elif optarch == OPTARCH_GENERIC:
            cpu_arch = get_cpu_architecture()
            if cpu_arch == X86_64:
                res = 'SSE2'
            else:
                res = 'None'
        elif optarch:
            warn_msg = "--optarch configuration setting set to %s but not taken into account; " % optarch
            warn_msg += "compiling GROMACS for the current host architecture (i.e. the default behavior)"
            self.log.warning(warn_msg)
            print_warning(warn_msg)

        if res:
            self.log.info("Target architecture based on optarch configuration option ('%s'): %s", optarch, res)
        else:
            self.log.info("No target architecture specified based on optarch configuration option ('%s')", optarch)

        return res

    @property
    def is_double_precision_cuda_build(self):
        """Check if the current build step involves double precision and CUDA"""
        cuda = get_software_root('CUDA')
        return cuda and self.double_prec_pattern in self.cfg['configopts']

    def prepare_step(self, *args, **kwargs):
        """Custom prepare step for GROMACS."""

        # With the intel toolchain the -ftz build flag is automatically added, causing
        # denormal results being flushed to zero. This will cause errors for very small
        # arguments without FMA support since some intermediate results might be denormal.
        # [https://redmine.gromacs.org/issues/2335]
        # Set -fp-model precise on non-FMA CPUs to produce correct results.
        if self.toolchain.comp_family() == toolchain.INTELCOMP:
            cpu_features = get_cpu_features()
            if 'fma' not in cpu_features:
                self.log.info("FMA instruction not supported by this CPU: %s", cpu_features)
                self.log.info("Setting precise=True intel toolchain option to remove -ftz build flag")
                self.toolchain.options['precise'] = True

        # This must be called after enforcing the precise option otherwise the
        # change will be ignored.
        super(EB_GROMACS, self).prepare_step(*args, **kwargs)

    def configure_step(self):
        """Custom configuration procedure for GROMACS: set configure options for configure or cmake."""

        gromacs_version = LooseVersion(self.version)

        if gromacs_version >= '4.6':
            cuda = get_software_root('CUDA')
            if cuda:
                # CUDA with double precision is currently not supported in GROMACS yet
                # If easyconfig explicitly have double_precision=True error out,
                # otherwise warn about it and skip the double precision build
                if self.cfg.get('double_precision'):
                    raise EasyBuildError("Double precision is not available for GPU build. " +
                                         "Please explicitly set \"double_precision = False\" " +
                                         "or remove it in the easyconfig file.")
                if self.double_prec_pattern in self.cfg['configopts']:
                    if self.cfg.get('double_precision') is None:
                        # Only print warning once when trying double precision
                        # build the first time
                        self.cfg['double_precision'] = False
                        self.log.info("Double precision is not available for " +
                                      "GPU build. Skipping the double precision build.")

                    self.log.info("skipping configure step")
                    return

                if gromacs_version >= '2021':
                    self.cfg.update('configopts', "-DGMX_GPU=CUDA")
                else:
                    self.cfg.update('configopts', "-DGMX_GPU=ON")
                self.cfg.update('configopts', "-DCUDA_TOOLKIT_ROOT_DIR=%s" % cuda)

                # Set CUDA capabilities based on template value.
                if '-DGMX_CUDA_TARGET_SM' not in self.cfg['configopts']:
                    cuda_cc_semicolon_sep = self.cfg.get_cuda_cc_template_value(
                        "cuda_cc_semicolon_sep").replace('.', '')
                    self.cfg.update('configopts', '-DGMX_CUDA_TARGET_SM="%s"' % cuda_cc_semicolon_sep)
            else:
                # explicitly disable GPU support if CUDA is not available,
                # to avoid that GROMACS finds and uses a system-wide CUDA compiler
                self.cfg.update('configopts', "-DGMX_GPU=OFF")

        # PLUMED detection
        # enable PLUMED support if PLUMED is listed as a dependency
        # and PLUMED support is either explicitly enabled (plumed = True) or unspecified ('plumed' not defined)
        plumed_root = get_software_root('PLUMED')
        if self.cfg['plumed'] and not plumed_root:
            msg = "PLUMED support has been requested but PLUMED is not listed as a dependency."
            raise EasyBuildError(msg)
        elif plumed_root and self.cfg['plumed'] is False:
            self.log.info('PLUMED was found, but compilation without PLUMED has been requested.')
            plumed_root = None

        if plumed_root:
            self.log.info('PLUMED support has been enabled.')

            # Need to check if PLUMED has an engine for this version
            engine = 'gromacs-%s' % self.version

            res = run_shell_cmd("plumed-patch -l")
            if not re.search(engine, res.output):
                plumed_ver = get_software_version('PLUMED')
                msg = "There is no support in PLUMED version %s for GROMACS %s: %s" % (plumed_ver, self.version,
                                                                                       res.output)
                if self.cfg['ignore_plumed_version_check']:
                    self.log.warning(msg)
                else:
                    raise EasyBuildError(msg)

            # PLUMED patching must be done at different stages depending on
            # version of GROMACS. Just prepare first part of cmd here
            plumed_cmd = "plumed-patch -p -e %s" % engine

        # Ensure that the GROMACS log files report how the code was patched
        # during the build, so that any problems are easier to diagnose.
        # The GMX_VERSION_STRING_OF_FORK feature is available since 2020.
        if (gromacs_version >= '2020' and
                '-DGMX_VERSION_STRING_OF_FORK=' not in self.cfg['configopts']):
            gromacs_version_string_suffix = 'EasyBuild-%s' % EASYBUILD_VERSION
            if plumed_root:
                gromacs_version_string_suffix += '-PLUMED-%s' % get_software_version('PLUMED')
            self.cfg.update('configopts', '-DGMX_VERSION_STRING_OF_FORK=%s' % gromacs_version_string_suffix)

        if gromacs_version < '4.6':
            self.log.info("Using configure script for configuring GROMACS build.")

            if self.cfg['build_shared_libs']:
                self.cfg.update('configopts', "--enable-shared --disable-static")
            else:
                self.cfg.update('configopts', "--enable-static")

            # Use external BLAS and LAPACK
            self.cfg.update('configopts', "--with-external-blas --with-external-lapack")
            env.setvar('LIBS', "%s %s" % (os.environ['LIBLAPACK'], os.environ['LIBS']))

            # Don't use the X window system
            self.cfg.update('configopts', "--without-x")

            # OpenMP is not supported for versions older than 4.5.
            if gromacs_version >= '4.5':
                # enable OpenMP support if desired
                if self.toolchain.options.get('openmp', None):
                    self.cfg.update('configopts', "--enable-threads")
                else:
                    self.cfg.update('configopts', "--disable-threads")
            elif self.toolchain.options.get('openmp', None):
                raise EasyBuildError("GROMACS version %s does not support OpenMP" % self.version)

            # GSL support
            if get_software_root('GSL'):
                self.cfg.update('configopts', "--with-gsl")
            else:
                self.cfg.update('configopts', "--without-gsl")

            # actually run configure via ancestor (not direct parent)
            self.cfg['configure_cmd'] = "./configure"
            ConfigureMake.configure_step(self)

            # Now patch GROMACS for PLUMED between configure and build
            if plumed_root:
                run_shell_cmd(plumed_cmd)

        else:
            if '-DGMX_MPI=ON' in self.cfg['configopts']:
                mpi_numprocs = self.cfg.get('mpi_numprocs', 0)
                if mpi_numprocs == 0:
                    self.log.info("No number of test MPI tasks specified -- using default: %s",
                                  self.cfg.parallel)
                    mpi_numprocs = self.cfg.parallel

                elif mpi_numprocs > self.cfg.parallel:
                    self.log.warning("Number of test MPI tasks (%s) is greater than value for 'parallel': %s",
                                     mpi_numprocs, self.cfg.parallel)

                mpiexec = self.cfg.get('mpiexec')
                if mpiexec:
                    mpiexec_path = which(mpiexec)
                    if mpiexec_path:
                        self.cfg.update('configopts', "-DMPIEXEC=%s" % mpiexec_path)
                        self.cfg.update('configopts', "-DMPIEXEC_NUMPROC_FLAG=%s" %
                                        self.cfg.get('mpiexec_numproc_flag'))
                        self.cfg.update('configopts', "-DNUMPROC=%s" % mpi_numprocs)
                    elif self.cfg['runtest']:
                        raise EasyBuildError("'%s' not found in $PATH", mpiexec)
                else:
                    raise EasyBuildError("No value found for 'mpiexec'")
                self.log.info("Using %s as MPI executable when testing, with numprocs flag '%s' and %s tasks",
                              mpiexec_path, self.cfg.get('mpiexec_numproc_flag'),
                              mpi_numprocs)

            if gromacs_version >= '2019':
                # Building the gmxapi interface requires shared libraries,
                # this is handled in the class initialisation so --module-only works
                self.cfg.update('configopts', "-DGMXAPI=ON")

                if gromacs_version >= '2020':
                    # build Python bindings if Python is loaded as a dependency
                    python_root = get_software_root('Python')
                    if python_root:
                        self.cfg.update('configopts', "-DGMX_PYTHON_PACKAGE=ON")
                        bin_python = os.path.join(python_root, 'bin', 'python')
                        # For find_package(PythonInterp)
                        self.cfg.update('configopts', "-DPYTHON_EXECUTABLE=%s" % bin_python)
                        if gromacs_version >= '2021':
                            # For find_package(Python3) - Ignore virtual envs
                            self.cfg.update('configopts', "-DPython3_FIND_VIRTUALENV=STANDARD")

            # Now patch GROMACS for PLUMED before cmake
            if plumed_root:
                if gromacs_version >= '5.1':
                    # Use shared or static patch depending on
                    # setting of self.cfg['build_shared_libs']
                    # and adapt cmake flags accordingly as per instructions
                    # from "plumed patch -i"
                    if self.cfg['build_shared_libs']:
                        mode = 'shared'
                    else:
                        mode = 'static'
                    plumed_cmd = plumed_cmd + ' -m %s' % mode

                run_shell_cmd(plumed_cmd)

            # prefer static libraries, if available
            if self.cfg['build_shared_libs']:
                self.cfg.update('configopts', "-DGMX_PREFER_STATIC_LIBS=OFF")
            else:
                self.cfg.update('configopts', "-DGMX_PREFER_STATIC_LIBS=ON")

            # always specify to use external BLAS/LAPACK
            self.cfg.update('configopts', "-DGMX_EXTERNAL_BLAS=ON -DGMX_EXTERNAL_LAPACK=ON")

            if gromacs_version < '2023':
                # disable GUI tools, removed in v2023
                self.cfg.update('configopts', "-DGMX_X11=OFF")

            # convince to build for an older architecture than present on the build node by setting GMX_SIMD CMake flag
            # it does not make sense for Cray, because OPTARCH is defined by the Cray Toolchain
            if self.toolchain.toolchain_family() != toolchain.CRAYPE:
                gmx_simd = self.get_gromacs_arch()
                if gmx_simd:
                    if gromacs_version < '5.0':
                        self.cfg.update('configopts', "-DGMX_CPU_ACCELERATION=%s" % gmx_simd)
                    else:
                        self.cfg.update('configopts', "-DGMX_SIMD=%s" % gmx_simd)

            # set regression test path
            prefix = 'regressiontests'
            if any([src['name'].startswith(prefix) for src in self.src]):
                self.cfg.update('configopts', "-DREGRESSIONTEST_PATH='%%(builddir)s/%s-%%(version)s' " % prefix)

            # enable OpenMP support if desired
            if self.toolchain.options.get('openmp', None):
                self.cfg.update('configopts', "-DGMX_OPENMP=ON")
            else:
                self.cfg.update('configopts', "-DGMX_OPENMP=OFF")

            imkl_root = get_software_root('imkl')
            if imkl_root:
                # using MKL for FFT, so it will also be used for BLAS/LAPACK
                imkl_include = os.path.join(os.getenv('MKLROOT'), 'mkl', 'include')
                self.cfg.update('configopts', '-DGMX_FFT_LIBRARY=mkl -DMKL_INCLUDE_DIR="%s" ' % imkl_include)
                libs = os.getenv('LAPACK_STATIC_LIBS').split(',')
                mkl_libs = [os.path.join(os.getenv('LAPACK_LIB_DIR'), lib) for lib in libs if lib != 'libgfortran.a']
                mkl_libs = ['-Wl,--start-group'] + mkl_libs + ['-Wl,--end-group -lpthread -lm -ldl']
                self.cfg.update('configopts', '-DMKL_LIBRARIES="%s" ' % ';'.join(mkl_libs))
            else:
                for libname in ['BLAS', 'LAPACK']:
                    libdir = os.getenv('%s_LIB_DIR' % libname)
                    if self.toolchain.toolchain_family() == toolchain.CRAYPE:
                        libsci_mpi_mp_lib = glob.glob(os.path.join(libdir, 'libsci_*_mpi_mp.a'))
                        if libsci_mpi_mp_lib:
                            self.cfg.update('configopts', '-DGMX_%s_USER=%s' % (libname, libsci_mpi_mp_lib[0]))
                        else:
                            raise EasyBuildError("Failed to find libsci library to link with for %s", libname)
                    else:
                        # -DGMX_BLAS_USER & -DGMX_LAPACK_USER require full path to library
                        # prefer shared libraries when using FlexiBLAS-based toolchain
                        if self.toolchain.blas_family() == toolchain.FLEXIBLAS:
                            libs = os.getenv('%s_SHARED_LIBS' % libname).split(',')
                        else:
                            libs = os.getenv('%s_STATIC_LIBS' % libname).split(',')

                        libpaths = [os.path.join(libdir, lib) for lib in libs if not lib.startswith('libgfortran')]
                        self.cfg.update('configopts', '-DGMX_%s_USER="%s"' % (libname, ';'.join(libpaths)))
                        # if libgfortran.a is listed, make sure it gets linked in too to avoiding linking issues
                        if 'libgfortran.a' in libs:
                            env.setvar('LDFLAGS', "%s -lgfortran -lm" % os.environ.get('LDFLAGS', ''))

            # no more GSL support in GROMACS 5.x, see http://redmine.gromacs.org/issues/1472
            if gromacs_version < '5.0':
                # enable GSL when it's provided
                if get_software_root('GSL'):
                    self.cfg.update('configopts', "-DGMX_GSL=ON")
                else:
                    self.cfg.update('configopts', "-DGMX_GSL=OFF")

            # include flags for linking to zlib/XZ in $LDFLAGS if they're listed as a dep;
            # this is important for the tests, to correctly link against libxml2
            for dep, link_flag in [('XZ', '-llzma'), ('zlib', '-lz')]:
                root = get_software_root(dep)
                if root:
                    libdir = get_software_libdir(dep)
                    ldflags = os.environ.get('LDFLAGS', '')
                    env.setvar('LDFLAGS', "%s -L%s %s" % (ldflags, os.path.join(root, libdir), link_flag))

            # complete configuration with configure_method of parent
            out = super(EB_GROMACS, self).configure_step()

            # for recent GROMACS versions, make very sure that a decent BLAS, LAPACK and FFT is found and used
            if gromacs_version >= '4.6.5':
                patterns = [
                    r"Using external FFT library - \S*",
                    r"Looking for dgemm_ - found",
                    r"Looking for cheev_ - found",
                ]
                for pattern in patterns:
                    regex = re.compile(pattern, re.M)
                    if not regex.search(out):
                        raise EasyBuildError("Pattern '%s' not found in GROMACS configuration output.", pattern)

            # Make sure compilation of CPU detection code did not fail
            patterns = [
                r".*detection program did not compile.*",
            ]
            for pattern in patterns:
                regex = re.compile(pattern, re.M)
                if regex.search(out):
                    raise EasyBuildError("Pattern '%s' found in GROMACS configuration output.", pattern)

    def build_step(self):
        """
        Custom build step for GROMACS; Skip if CUDA is enabled and the current
        iteration is for double precision
        """

        if self.is_double_precision_cuda_build:
            self.log.info("skipping build step")
        else:
            super(EB_GROMACS, self).build_step()

    def test_step(self):
        """Run the basic tests (but not necessarily the full regression tests) using make check"""

        if self.is_double_precision_cuda_build:
            self.log.info("skipping test step")
        else:
            # allow to escape testing by setting runtest to False
            if self.cfg['runtest'] is None or self.cfg['runtest']:

                libdir = os.path.join(self.installdir, 'lib')
                libdir_backup = None

                if build_option('rpath'):
                    # temporarily copy 'lib' to installation directory when RPATH linking is enabled;
                    # required to fix errors like:
                    #     "ImportError: libgmxapi.so.0: cannot open shared object file: No such file or directory"
                    # occurs with 'make test' because _gmxapi.*.so only includes %(installdir)/lib in RPATH section,
                    # while the libraries are only there after install step...

                    # keep in mind that we may be performing an iterated installation:
                    # if there already is an existing 'lib' dir in the installation,
                    # we temporarily move it out of the way (and then restore it after running the tests)
                    if os.path.exists(libdir):
                        libdir_backup = find_backup_name_candidate(libdir)
                        self.log.info("%s already exists, moving it to %s while running tests...",
                                      libdir, libdir_backup)
                        shutil.move(libdir, libdir_backup)

                    copy_dir('lib', libdir)

                orig_runtest = self.cfg['runtest']
                # make very sure OMP_NUM_THREADS is set to 1, to avoid hanging GROMACS regression test
                env.setvar('OMP_NUM_THREADS', '1')

                if self.cfg['runtest'] is None or isinstance(self.cfg['runtest'], bool):
                    self.cfg['runtest'] = 'check'

                # run 'make check' or whatever the easyconfig specifies
                # in parallel since it involves more compilation
                self.cfg.update('runtest', f"-j {self.cfg.parallel}")
                super(EB_GROMACS, self).test_step()

                if build_option('rpath'):
                    # clean up temporary copy of 'lib' in installation directory,
                    # this was only there to avoid ImportError when running the tests before populating
                    # the installation directory
                    remove_dir(libdir)

                    if libdir_backup:
                        self.log.info("Restoring %s to %s after running tests", libdir_backup, libdir)
                        shutil.move(libdir_backup, libdir)

                self.cfg['runtest'] = orig_runtest

    def install_step(self):
        """
        Custom install step for GROMACS; figure out where libraries were installed to.
        """
        # Skipping if CUDA is enabled and the current iteration is double precision
        if self.is_double_precision_cuda_build:
            self.log.info("skipping install step")
        else:
            # run 'make install' in parallel since it involves more compilation
            self.cfg.update('installopts', f"-j {self.cfg.parallel}")
            super(EB_GROMACS, self).install_step()

    def extensions_step(self, fetch=False):
        """ Custom extensions step, only handle extensions after the last iteration round"""
        if self.iter_idx < self.variants_to_build - 1:
            self.log.info("skipping extension step %s", self.iter_idx)
        else:
            # Reset installopts etc for the benefit of the gmxapi extension
            self.cfg['install_cmd'] = self.orig_install_cmd
            self.cfg['build_cmd'] = self.orig_build_cmd
            self.cfg['installopts'] = self.orig_installopts
            # Set runtest to None so that the gmxapi extension doesn't try to
            # run "check" as a command
            orig_runtest = self.cfg['runtest']
            self.cfg['runtest'] = None
            super(EB_GROMACS, self).extensions_step(fetch)
            self.cfg['runtest'] = orig_runtest

    @property
    def lib_subdirs(self):
        """Return list of relative paths to subdirs holding library files"""
        if len(self._lib_subdirs) == 0:
            try:
                self._lib_subdirs = self.get_lib_subdirs()
            except EasyBuildError as error:
                if build_option('force') and build_option('module_only'):
                    self.log.info(f"No sub-directory with GROMACS libraries found in installation: {error}")
                    self.log.info("You are forcing module creation for a non-existent installation!")
                else:
                    raise error

        return self._lib_subdirs

    def get_lib_subdirs(self):
        """
        Return list of relative paths to sub-directories that contain GROMACS libraries

        The GROMACS libraries get installed in different locations (deeper subdirectory),
        depending on the platform;
        this is determined by the GNUInstallDirs CMake module;
        rather than trying to replicate the logic, we just figure out where the library was placed
        """

        if LooseVersion(self.version) < LooseVersion('5.0'):
            libname = f'libgmx*.{self.libext}'
        else:
            libname = f'libgromacs*.{self.libext}'

        lib_subdirs = []
        real_installdir = os.path.realpath(self.installdir)
        for lib_path in glob.glob(os.path.join(real_installdir, '**', libname), recursive=True):
            lib_relpath = os.path.realpath(lib_path)  # avoid symlinks
            lib_relpath = lib_relpath[len(real_installdir) + 1:]  # relative path from installdir
            subdir = lib_relpath.split(os.sep)[0:-1]
            lib_subdirs.append(os.path.join(*subdir))

        if len(lib_subdirs) == 0:
            raise EasyBuildError(f"Failed to determine sub-directory with {libname} in {self.installdir}")

        # remove duplicates, 'libname' pattern can match symlinks to actual library file
        lib_subdirs = nub(lib_subdirs)
        self.log.info(f"Found sub-directories that contain {libname}: {', '.join(lib_subdirs)}")

        return lib_subdirs

    def make_module_step(self, *args, **kwargs):
        """Custom library subdirectories for GROMACS."""
        self.module_load_environment.LD_LIBRARY_PATH = self.lib_subdirs
        self.module_load_environment.LIBRARY_PATH = self.lib_subdirs
        self.module_load_environment.PKG_CONFIG_PATH = [os.path.join(ld, 'pkgconfig') for ld in self.lib_subdirs]

        return super().make_module_step(*args, **kwargs)

    def sanity_check_step(self):
        """Custom sanity check for GROMACS."""

        dirs = [os.path.join('include', 'gromacs')]

        # in GROMACS v5.1, only 'gmx' binary is there
        # (only) in GROMACS v5.0, other binaries are symlinks to 'gmx'
        # bins/libs that never have an _mpi suffix
        bins = []
        libnames = []
        # bins/libs that may have an _mpi suffix
        mpi_bins = []
        mpi_libnames = []
        if LooseVersion(self.version) < LooseVersion('5.1'):
            mpi_bins.extend(['mdrun'])

        if LooseVersion(self.version) >= LooseVersion('5.0'):
            mpi_bins.append('gmx')
            mpi_libnames.append('gromacs')
        else:
            bins.extend(['editconf', 'g_lie', 'genbox', 'genconf'])
            libnames.extend(['gmxana'])
            if LooseVersion(self.version) >= LooseVersion('4.6'):
                if self.cfg['build_shared_libs']:
                    mpi_libnames.extend(['gmx', 'md'])
                else:
                    libnames.extend(['gmx', 'md'])
            else:
                mpi_libnames.extend(['gmx', 'md'])

            if LooseVersion(self.version) >= LooseVersion('4.5'):
                if LooseVersion(self.version) >= LooseVersion('4.6'):
                    if self.cfg['build_shared_libs']:
                        mpi_libnames.append('gmxpreprocess')
                    else:
                        libnames.append('gmxpreprocess')
                else:
                    mpi_libnames.append('gmxpreprocess')

        # also check for MPI-specific binaries/libraries
        if self.toolchain.options.get('usempi', None):
            if LooseVersion(self.version) < LooseVersion('4.6'):
                mpisuff = self.cfg.get('mpisuffix', '_mpi')
            else:
                mpisuff = '_mpi'

            mpi_bins.extend([binary + mpisuff for binary in mpi_bins])
            mpi_libnames.extend([libname + mpisuff for libname in mpi_libnames])

        suffixes = ['']

        # make sure that configopts is a list:
        configopts_list = self.cfg['configopts']
        if isinstance(configopts_list, str):
            configopts_list = [configopts_list]

        lib_files = []
        bin_files = []

        dsuff = None
        if not get_software_root('CUDA'):
            for configopts in configopts_list:
                # add the _d suffix to the suffix, in case of double precision
                if self.double_prec_pattern in configopts:
                    dsuff = '_d'

        if dsuff:
            suffixes.extend([dsuff])

        lib_files.extend([f'lib{x}{suff}.{self.libext}' for x in libnames + mpi_libnames for suff in suffixes])
        bin_files.extend([b + suff for b in bins + mpi_bins for suff in suffixes])

        # pkgconfig dir not available for earlier versions, exact version to use here is unclear
        if LooseVersion(self.version) >= LooseVersion('4.6'):
            dirs.extend([os.path.join(ld, 'pkgconfig') for ld in self.lib_subdirs])

        custom_paths = {
            'files': [os.path.join('bin', b) for b in bin_files] +
            [os.path.join(libdir, lib) for libdir in self.lib_subdirs for lib in lib_files],
            'dirs': dirs,
        }
        super(EB_GROMACS, self).sanity_check_step(custom_paths=custom_paths)

    def run_all_steps(self, *args, **kwargs):
        """
        Put configure options in place for different variants, (no)mpi, single/double precision.
        """
        # Save installopts so we can reset it later. The gmxapi pip install
        # can't handle the -j argument.
        self.orig_installopts = self.cfg['installopts']

        # keep track of config/build/installopts specified in easyconfig
        # file, so we can include them in each iteration later
        common_config_opts = self.cfg['configopts']
        common_build_opts = self.cfg['buildopts']
        common_install_opts = self.cfg['installopts']

        self.orig_install_cmd = self.cfg['install_cmd']
        self.orig_build_cmd = self.cfg['build_cmd']

        self.cfg['configopts'] = []
        self.cfg['buildopts'] = []
        self.cfg['installopts'] = []

        if LooseVersion(self.version) < LooseVersion('4.6'):
            prec_opts = {
                'single': '--disable-double',
                'double': '--enable-double',
            }
            mpi_type_opts = {
                'nompi': '--disable-mpi',
                'mpi': '--enable-mpi'
            }
        else:
            prec_opts = {
                'single': '-DGMX_DOUBLE=OFF',
                'double': '-DGMX_DOUBLE=ON',
            }
            mpi_type_opts = {
                'nompi': '-DGMX_MPI=OFF -DGMX_THREAD_MPI=ON',
                'mpi': '-DGMX_MPI=ON -DGMX_THREAD_MPI=OFF'
            }

        # Double precision pattern so search for in configopts
        self.double_prec_pattern = prec_opts['double']

        # For older versions we only build/install the mdrun part for
        # the MPI variant. So we need to be able to specify the
        # install target depending on variant.
        self.cfg['install_cmd'] = 'make'
        if LooseVersion(self.version) < LooseVersion('5'):
            # Use the fact that for older versions we just need to
            # build and install mdrun for the MPI part
            build_opts = {
                'nompi': '',
                'mpi': 'mdrun'
            }
            install_opts = {
                'nompi': 'install',
                'mpi': 'install-mdrun'
            }
        else:
            build_opts = {
                'nompi': '',
                'mpi': ''
            }
            install_opts = {
                'nompi': 'install',
                'mpi': 'install'
            }

        precisions = []
        if self.cfg.get('single_precision'):
            precisions.append('single')
        if self.cfg.get('double_precision') is None or self.cfg.get('double_precision'):
            precisions.append('double')

        if precisions == []:
            raise EasyBuildError("No precision selected. At least one of single/double_precision must be unset or True")

        mpitypes = ['nompi']
        if self.toolchain.options.get('usempi', None):
            mpitypes.append('mpi')

        # We need to count the number of variations to build.
        versions_built = []
        # Handle the different variants
        for precision in precisions:
            for mpitype in mpitypes:
                versions_built.append('%s precision %s' % (precision, mpitype))
                var_confopts = []
                var_buildopts = []
                var_installopts = []

                var_confopts.append(mpi_type_opts[mpitype])
                var_confopts.append(prec_opts[precision])
                if LooseVersion(self.version) < LooseVersion('4.6'):
                    suffix = ''
                    if mpitype == 'mpi':
                        suffix = "--program-suffix={0}".format(self.cfg.get('mpisuffix', '_mpi'))
                        if precision == 'double':
                            suffix += '_d'
                    var_confopts.append(suffix)

                var_buildopts.append(build_opts[mpitype])
                var_installopts.append(install_opts[mpitype])

                self.cfg.update('configopts', ' '.join(var_confopts + [common_config_opts]))
                self.cfg.update('buildopts', ' '.join(var_buildopts + [common_build_opts]))
                self.cfg.update('installopts', ' '.join(var_installopts + [common_install_opts]))
        self.variants_to_build = len(self.cfg['configopts'])

        self.log.debug("List of configure options to iterate over: %s", self.cfg['configopts'])
        self.log.info("Building these variants of GROMACS: %s", ', '.join(versions_built))
        return super(EB_GROMACS, self).run_all_steps(*args, **kwargs)

        self.cfg['install_cmd'] = self.orig_install_cmd
        self.cfg['build_cmd'] = self.orig_build_cmd

        self.log.info("A full regression test suite is available from the GROMACS web site: %s", self.cfg['homepage'])
