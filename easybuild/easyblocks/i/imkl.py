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
EasyBuild support for installing the Intel Math Kernel Library (MKL), implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Ward Poelmans (Ghent University)
@author: Lumir Jasiok (IT4Innovations)
@author: Bart Oldeman (McGill University, Calcul Quebec, Compute Canada)
"""
import glob
import itertools
import os
import shutil
import tempfile
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, mkdir, move_file, remove_dir, write_file
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS, get_software_root
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_imkl(IntelBase):
    """
    Class that can be used to install mkl
    - minimum version suported: 2020.x
    -- will fail for all older versions (due to newer silent installer)
    """

    @staticmethod
    def extra_options():
        """Add easyconfig parameters custom to imkl (e.g. interfaces)."""
        extra_vars = {
            'interfaces': [True, "Indicates whether interfaces should be built", CUSTOM],
            'flexiblas': [None, "Indicates whether FlexiBLAS-compatible libraries should be built, "
                          "default from version 2021", CUSTOM],
        }
        return IntelBase.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Constructor for imkl easyblock."""
        super(EB_imkl, self).__init__(*args, **kwargs)
        if LooseVersion(self.version) < LooseVersion('2020'):
            raise EasyBuildError(
                f"Version {self.version} of {self.name} is unsupported. Mininum supported version is 2020.0."
            )

        # make sure $MKLROOT isn't set, it's known to cause problems with the installation
        self.cfg.update('unwanted_env_vars', ['MKLROOT'])
        self.cdftlibs = []
        self.mpi_spec = None

        if self.cfg['flexiblas'] is None:
            self.cfg['flexiblas'] = LooseVersion(self.version) >= LooseVersion('2021')

        if LooseVersion(self.version) >= LooseVersion('2024'):
            self.examples_subdir = os.path.join('share', 'doc', 'mkl', 'examples')
            self.compiler_libdir = 'lib'
        else:
            self.examples_subdir = 'examples'
            self.compiler_libdir = os.path.join('linux', 'compiler', 'lib', 'intel64_lin')

    @property
    def mkl_basedir(self):
        if LooseVersion(self.version) >= LooseVersion('2021'):
            return self.get_versioned_subdir('mkl')
        else:
            return 'mkl'

    @mkl_basedir.setter
    def mkl_basedir(self, path):
        self.set_versioned_subdir('mkl', path)

    def prepare_step(self, *args, **kwargs):
        """Prepare build environment."""

        kwargs['requires_runtime_license'] = False
        super(EB_imkl, self).prepare_step(*args, **kwargs)

        # build the mkl interfaces, if desired
        if self.cfg['interfaces']:
            self.cdftlibs = ['fftw2x_cdft', 'fftw3x_cdft']
            # check whether MPI_FAMILY constant is defined, so mpi_family() can be used
            if hasattr(self.toolchain, 'MPI_FAMILY') and self.toolchain.MPI_FAMILY is not None:
                mpi_spec_by_fam = {
                    toolchain.MPICH: 'mpich2',  # MPICH is MPICH v3.x, which is MPICH2 compatible
                    toolchain.MPICH2: 'mpich2',
                    toolchain.MVAPICH2: 'mpich2',
                    toolchain.OPENMPI: 'openmpi',
                }
                mpi_fam = self.toolchain.mpi_family()
                self.mpi_spec = mpi_spec_by_fam.get(mpi_fam)
                debugstr = "MPI toolchain component"
            else:
                # can't use toolchain.mpi_family, because of system toolchain
                if get_software_root('MPICH2') or get_software_root('MVAPICH2'):
                    self.mpi_spec = 'mpich2'
                elif get_software_root('OpenMPI'):
                    self.mpi_spec = 'openmpi'
                elif not get_software_root('impi'):
                    # no compatible MPI found: do not build cdft
                    self.cdftlibs = []
                debugstr = "loaded MPI module"
            if self.mpi_spec:
                self.log.debug("Determined MPI specification based on %s: %s", debugstr, self.mpi_spec)
            else:
                self.log.debug("No MPI or no compatible MPI found: do not build CDFT")

    def install_step(self):
        """
        Actual installation
        - create silent cfg file
        - execute command
        """
        silent_cfg_extras = None
        if self.install_components is None:
            silent_cfg_extras = {
                'COMPONENTS': 'ALL',
            }
        super(EB_imkl, self).install_step(silent_cfg_extras=silent_cfg_extras)

    def build_mkl_fftw_interfaces(self, libdir):
        """Build the Intel MKL FFTW interfaces."""
        mkdir(libdir)

        intsubdir = self.mkl_basedir
        if LooseVersion(self.version) >= LooseVersion('2024'):
            intsubdir = os.path.join(intsubdir, 'share', 'mkl')
        intsubdir = os.path.join(intsubdir, 'interfaces')
        inttarget = 'libintel64'

        cmd = "make -f makefile %s" % inttarget

        # blas95 and lapack95 need more work, ignore for now
        # blas95 and lapack also need include/.mod to be processed
        fftw2libs = ['fftw2xc', 'fftw2xf']
        fftw3libs = ['fftw3xc', 'fftw3xf']

        interfacedir = os.path.join(self.installdir, intsubdir)
        change_dir(interfacedir)
        self.log.info("Changed to interfaces directory %s", interfacedir)

        compopt = None
        # determine whether we're using a non-Intel GCC-based or PGI/NVHPC-based toolchain
        # can't use toolchain.comp_family, because of system toolchain used when installing imkl
        if get_software_root('icc') or get_software_root('intel-compilers'):
            compopt = 'compiler=intel'
        elif get_software_root('PGI'):
            compopt = 'compiler=pgi'
        elif get_software_root('NVHPC'):
            compopt = 'compiler=nvhpc'
        # GCC should be the last as the above compilers also have an underlying GCC
        elif get_software_root('GCC'):
            compopt = 'compiler=gnu'
        else:
            raise EasyBuildError("Not using Intel/GCC/PGI/NVHPC compilers, "
                                 "don't know how to build wrapper libs")

        # patch makefiles for cdft wrappers when PGI or NVHPC is used as compiler
        if get_software_root('NVHPC'):
            regex_subs = [
                # nvhpc should be considered as a valid compiler
                ("intel gnu", "intel gnu nvhpc"),
                # transform 'gnu' case to 'nvhpc' case
                (r"ifeq \(\$\(compiler\),gnu\)", "ifeq ($(compiler),nvhpc)"),
                ('=gcc', '=nvc'),
            ]
        if get_software_root('PGI'):
            regex_subs = [
                # pgi should be considered as a valid compiler
                ("intel gnu", "intel gnu pgi"),
                # transform 'gnu' case to 'pgi' case
                (r"ifeq \(\$\(compiler\),gnu\)", "ifeq ($(compiler),pgi)"),
                ('=gcc', '=pgcc'),
            ]
        if get_software_root('PGI') or get_software_root('NVHPC'):
            regex_subs += [
                # correct flag to use C99 standard
                ('-std=c99', '-c99'),
                # -Wall and -Werror are not valid options for pgcc, no close equivalent
                ('-Wall', ''),
                ('-Werror', ''),
            ]
            for lib in self.cdftlibs:
                apply_regex_substitutions(os.path.join(interfacedir, lib, 'makefile'), regex_subs)

        if get_software_root('NVHPC'):
            regex_nvc_subs = [
                ('pgcc', 'nvc'),
                ('pgf95', 'nvfortran'),
                ('pgi', 'nvhpc'),
            ]
            for liball in glob.glob(os.path.join(interfacedir, '*', 'makefile')):
                apply_regex_substitutions(liball, regex_nvc_subs)

        for lib in fftw2libs + fftw3libs + self.cdftlibs:
            buildopts = [compopt]
            if lib in fftw3libs:
                buildopts.append('install_to=$INSTALL_DIR')
            elif lib in self.cdftlibs:
                if self.mpi_spec is not None:
                    buildopts.append('mpi=%s' % self.mpi_spec)

            precflags = ['']
            if lib.startswith('fftw2x'):
                # build both single and double precision variants
                precflags = ['PRECISION=MKL_DOUBLE', 'PRECISION=MKL_SINGLE']

            intflags = ['']
            if lib in self.cdftlibs:
                # build both 32-bit and 64-bit interfaces
                intflags = ['interface=lp64', 'interface=ilp64']

            allopts = [list(opts) for opts in itertools.product(intflags, precflags)]

            for flags, extraopts in itertools.product(['', '-fPIC'], allopts):
                tup = (lib, flags, buildopts, extraopts)
                self.log.debug("Building lib %s with: flags %s, buildopts %s, extraopts %s" % tup)

                tmpbuild = tempfile.mkdtemp(dir=self.builddir)
                self.log.debug("Created temporary directory %s" % tmpbuild)

                # Avoid unused command line arguments (-Wl,rpath...) causing errors when using RPATH
                # See https://github.com/easybuilders/easybuild-easyconfigs/pull/18439#issuecomment-1662671054
                if build_option('rpath') and os.getenv('CC') in ('icx', 'clang'):
                    cflags = flags + ' -Wno-unused-command-line-argument'
                else:
                    cflags = flags

                # always set INSTALL_DIR, SPEC_OPT, COPTS and CFLAGS
                # fftw2x(c|f): use $INSTALL_DIR, $CFLAGS and $COPTS
                # fftw3x(c|f): use $CFLAGS
                # fftw*cdft: use $INSTALL_DIR and $SPEC_OPT
                env.setvar('INSTALL_DIR', tmpbuild)
                env.setvar('SPEC_OPT', flags)
                env.setvar('COPTS', flags)
                env.setvar('CFLAGS', cflags)

                intdir = os.path.join(interfacedir, lib)
                change_dir(intdir)
                self.log.info("Changed to interface %s directory %s", lib, intdir)

                fullcmd = "%s %s" % (cmd, ' '.join(buildopts + extraopts))
                res = run_shell_cmd(fullcmd)
                if res.exit_code:
                    raise EasyBuildError("Building %s (flags: %s, fullcmd: %s) failed", lib, flags, fullcmd)

                for fn in os.listdir(tmpbuild):
                    src = os.path.join(tmpbuild, fn)
                    if flags == '-fPIC':
                        # add _pic to filename
                        ff = fn.split('.')
                        fn = '.'.join(ff[:-1]) + '_pic.' + ff[-1]
                    dest = os.path.join(libdir, fn)
                    if os.path.isfile(src):
                        move_file(src, dest)
                        self.log.info("Moved %s to %s", src, dest)

                remove_dir(tmpbuild)

    def build_mkl_flexiblas(self, flexiblasdir):
        """
        Build libflexiblas_imkl_gnu_thread.so, libflexiblas_imkl_intel_thread.so,
        and libflexiblas_imkl_sequential.so. They can be used as FlexiBLAS backends
        via FLEXIBLAS_LIBRARY_PATH.
        """
        builder_subdir = os.path.join('tools', 'builder')
        if LooseVersion(self.version) >= LooseVersion('2024'):
            builder_subdir = os.path.join('share', 'mkl', builder_subdir)
        change_dir(os.path.join(self.installdir, self.mkl_basedir, builder_subdir))
        mkdir(flexiblasdir, parents=True)

        # concatenate lists of all BLAS, CBLAS and LAPACK functions
        with tempfile.NamedTemporaryFile(dir=self.builddir, mode="wt", delete=False) as dst:
            listfilename = dst.name
            self.log.debug("Created temporary file %s" % listfilename)
            for lst in 'blas', 'cblas', 'lapack':
                with open(lst + "_example_list") as src:
                    shutil.copyfileobj(src, dst)

        compilerdir = os.path.join(self.installdir, self.get_versioned_subdir('compiler'), self.compiler_libdir)
        # IFACE_COMP_PART=gf gives the gfortran calling convention that FlexiBLAS expects
        cmds = ["make libintel64 IFACE_COMP_PART=gf export=%s name=%s" % (
            listfilename, os.path.join(flexiblasdir, 'libflexiblas_imkl_')) +
                s for s in ['sequential threading=sequential',
                            'gnu_thread parallel=gnu',
                            'intel_thread parallel=intel SYSTEM_LIBS="-lm -ldl -L%s"' % compilerdir]]

        for cmd in cmds:
            res = run_shell_cmd(cmd)
            if res.exit_code:
                raise EasyBuildError("Building FlexiBLAS-compatible library (cmd: %s) failed", cmd)

    def post_processing_step(self):
        """
        Install group libraries and interfaces (if desired).
        """
        super(EB_imkl, self).post_processing_step()

        # extract examples
        examples_subdir = os.path.join(self.installdir, self.mkl_basedir, self.examples_subdir)
        if os.path.exists(examples_subdir):
            cwd = change_dir(examples_subdir)
            for examples_tarball in glob.glob('examples_*.tgz'):
                run_shell_cmd("tar xvzf %s -C ." % examples_tarball)
            change_dir(cwd)

        # reload the dependencies
        self.load_dependency_modules()

        shlib_ext = get_shared_lib_ext()

        extra = {
            'libmkl.%s' % shlib_ext: 'GROUP (-lmkl_intel_lp64 -lmkl_intel_thread -lmkl_core)',
            'libmkl_em64t.a': 'GROUP (libmkl_intel_lp64.a libmkl_intel_thread.a libmkl_core.a)',
            'libmkl_solver.a': 'GROUP (libmkl_solver_lp64.a)',
            'libmkl_scalapack.a': 'GROUP (libmkl_scalapack_lp64.a)',
            'libmkl_lapack.a': 'GROUP (libmkl_intel_lp64.a libmkl_intel_thread.a libmkl_core.a)',
            'libmkl_cdft.a': 'GROUP (libmkl_cdft_core.a)'
        }

        libsubdir = os.path.join(self.mkl_basedir, 'lib', 'intel64')
        libdir = os.path.join(self.installdir, libsubdir)
        for fil, txt in extra.items():
            dest = os.path.join(libdir, fil)
            if not os.path.exists(dest):
                write_file(dest, txt)

        if self.cfg['interfaces']:
            self.build_mkl_fftw_interfaces(os.path.join(self.installdir, libdir))

        if self.cfg['flexiblas']:
            self.build_mkl_flexiblas(os.path.join(self.installdir, libdir, 'flexiblas'))

    def get_mkl_fftw_interface_libs(self):
        """Returns list of library names produced by build_mkl_fftw_interfaces()"""

        if get_software_root('icc') or get_software_root('intel-compilers'):
            compsuff = '_intel'
        # check for PGI and NVHPC first, since there's a GCC underneath PGI and NVHPC too...
        elif get_software_root('PGI'):
            compsuff = '_pgi'
        elif get_software_root('NVHPC'):
            compsuff = '_nvhpc'
        elif get_software_root('GCC'):
            compsuff = '_gnu'
        else:
            raise EasyBuildError("Not using Intel/GCC/PGI/NVHPC, "
                                 "don't know compiler suffix for FFTW libraries.")

        precs = ['_double', '_single']
        fftw_vers = [f'2x{x}{prec}' for x in ['c', 'f'] for prec in precs] + ['3xc', '3xf']

        pics = ['', '_pic']
        libs = [f'libfftw{fftwver}{compsuff}{pic}.a' for fftwver in fftw_vers for pic in pics]

        if self.cdftlibs:
            fftw_cdft_vers = ['2x_cdft_DOUBLE', '2x_cdft_SINGLE', '3x_cdft']
            bits = ['_lp64', '_ilp64']
            libs += [f'libfftw{x[0]}{x[1]}{x[2]}.a' for x in itertools.product(fftw_cdft_vers, bits, pics)]

        return libs

    def sanity_check_step(self):
        """Custom sanity check paths for Intel MKL."""
        shlib_ext = get_shared_lib_ext()

        mklfiles = None
        mkldirs = None
        libs = ['libmkl_core.%s' % shlib_ext, 'libmkl_gnu_thread.%s' % shlib_ext,
                'libmkl_intel_thread.%s' % shlib_ext, 'libmkl_sequential.%s' % shlib_ext]
        extralibs = ['libmkl_blacs_intelmpi_%(suff)s.' + shlib_ext, 'libmkl_scalapack_%(suff)s.' + shlib_ext]

        if self.cfg['interfaces']:
            libs += self.get_mkl_fftw_interface_libs()

        if self.cfg['flexiblas']:
            libs += [os.path.join('flexiblas', 'libflexiblas_imkl_%s.so' % thread)
                     for thread in ['gnu_thread', 'intel_thread', 'sequential']]

        mkldirs = [
            os.path.join(self.mkl_basedir, 'bin'),
            os.path.join(self.mkl_basedir, 'lib', 'intel64'),
            os.path.join(self.mkl_basedir, 'include'),
        ]
        libs += [lib % {'suff': suff} for lib in extralibs for suff in ['lp64', 'ilp64']]

        mklfiles = [os.path.join(self.mkl_basedir, 'include', 'mkl.h')]
        mklfiles.extend([os.path.join(self.mkl_basedir, 'lib', 'intel64', lib) for lib in libs])

        if LooseVersion(self.version) >= LooseVersion('2021'):
            mklfiles.append(os.path.join(self.mkl_basedir, 'lib', 'intel64', 'libmkl_core.%s' % shlib_ext))
        else:
            mklfiles.append(os.path.join(self.mkl_basedir, 'lib', 'intel64', 'libmkl.%s' % shlib_ext))
            mkldirs += [os.path.join('lib', 'intel64_lin')]

        custom_paths = {
            'files': mklfiles,
            'dirs': mkldirs,
        }

        super(EB_imkl, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_step(self, *args, **kwargs):
        """
        Set paths for module load environment based on the actual installation files
        """
        if LooseVersion(self.version) >= LooseVersion('2021'):
            compiler_subdir = os.path.join(self.get_versioned_subdir('compiler'), self.compiler_libdir)
            pkg_config_path = [
                os.path.join(self.mkl_basedir, 'tools', 'pkgconfig'),
                os.path.join(self.mkl_basedir, 'lib', 'pkgconfig'),
            ]
        else:
            compiler_subdir = os.path.join('lib', 'intel64')
            pkg_config_path = [os.path.join(self.mkl_basedir, 'bin', 'pkgconfig')]

        self.module_load_environment.PATH = []
        self.module_load_environment.LD_LIBRARY_PATH = [
            compiler_subdir,
            os.path.join(self.mkl_basedir, 'lib', 'intel64'),
        ]
        self.module_load_environment.LIBRARY_PATH = self.module_load_environment.LD_LIBRARY_PATH
        self.module_load_environment.CMAKE_PREFIX_PATH = [self.mkl_basedir]
        self.module_load_environment.PKG_CONFIG_PATH = pkg_config_path

        # include paths to headers (e.g. CPATH)
        include_dirs = [
            os.path.join(self.mkl_basedir, 'include'),
            os.path.join(self.mkl_basedir, 'include', 'fftw'),
        ]
        self.module_load_environment.set_alias_vars(MODULE_LOAD_ENV_HEADERS, include_dirs)

        if LooseVersion(self.version) < LooseVersion('2021'):
            self.module_load_environment.MANPATH = ['man', os.path.join('man', 'en_US')]
            self.module_load_environment.MIC_LD_LIBRARY_PATH = [
                os.path.join('lib', 'intel64_lin_mic'),
                os.path.join(self.mkl_basedir, 'lib', 'mic'),
            ]

        if self.cfg['flexiblas']:
            self.module_load_environment.FLEXIBLAS_LIBRARY_PATH = os.path.join(
                self.mkl_basedir, 'lib', 'intel64', 'flexiblas'
            )

        return super().make_module_step(*args, **kwargs)

    def make_module_extra(self):
        """Overwritten from Application to add extra txt"""

        if 'MKL_EXAMPLES' not in self.cfg['modextravars']:
            self.cfg.update('modextravars', {
                'MKL_EXAMPLES': os.path.join(self.installdir, self.mkl_basedir, self.examples_subdir),
            })

        txt = super(EB_imkl, self).make_module_extra()

        mklroot = os.path.join(self.installdir, self.mkl_basedir)
        txt += self.module_generator.set_environment('MKLROOT', mklroot)

        return txt
