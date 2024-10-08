##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for PETSc, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os
import re

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import BUILD, CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import symlink, apply_regex_substitutions
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.tools.py2vs3 import string_type

NO_MPI_CXX_EXT_FLAGS = '-DOMPI_SKIP_MPICXX -DMPICH_SKIP_MPICXX'


class EB_PETSc(ConfigureMake):
    """Support for building and installing PETSc"""

    def __init__(self, *args, **kwargs):
        """Initialize PETSc specific variables."""
        super(EB_PETSc, self).__init__(*args, **kwargs)

        self.petsc_arch = self.cfg['petsc_arch']
        self.petsc_subdir = ""
        self.prefix_inc = ''
        self.prefix_lib = ''
        self.prefix_bin = ''

        self.with_python = False

        if self.cfg['sourceinstall']:
            self.build_in_installdir = True

        if LooseVersion(self.version) >= LooseVersion("3.9"):
            self.prefix_bin = os.path.join(self.prefix_inc, 'lib', 'petsc')

    @staticmethod
    def extra_options():
        """Add extra config options specific to PETSc."""
        extra_vars = {
            'sourceinstall': [False, "Indicates whether a source installation should be performed", CUSTOM],
            'petsc_arch': ['', "Custom PETSC_ARCH for sourceinstall", CUSTOM],
            'shared_libs': [False, "Build shared libraries", CUSTOM],
            'with_papi': [False, "Enable PAPI support", CUSTOM],
            'papi_inc': ['/usr/include', "Path for PAPI include files", CUSTOM],
            'papi_lib': ['/usr/lib64/libpapi.so', "Path for PAPI library", CUSTOM],
            'runtest': ['test', "Make target to test build", BUILD],
            'test_parallel': [
                None,
                "Number of parallel PETSc tests launched. If unset, 'parallel' will be used",
                CUSTOM
            ],
            'download_deps_static': [[], "Dependencies that should be downloaded and installed static", CUSTOM],
            'download_deps_shared': [[], "Dependencies that should be downloaded and installed shared", CUSTOM],
            'download_deps': [[], "Dependencies that should be downloaded and installed", CUSTOM]
        }
        return ConfigureMake.extra_options(extra_vars)

    def prepare_step(self, *args, **kwargs):
        """Prepare build environment."""

        super(EB_PETSc, self).prepare_step(*args, **kwargs)

        # build with Python support if Python is loaded as a non-build (runtime) dependency
        build_deps = self.cfg.dependencies(build_only=True)
        if get_software_root('Python') and not any(x['name'] == 'Python' for x in build_deps):
            self.with_python = True
            self.log.info("Python included as runtime dependency, so enabling Python support")

    def configure_step(self):
        """
        Configure PETSc by setting configure options and running configure script.

        Configure procedure is much more concise for older versions (< v3).
        """
        if LooseVersion(self.version) >= LooseVersion("3"):
            # make the install dir first if we are doing a download install, then keep it for the rest of the way
            deps = self.cfg["download_deps"] + self.cfg["download_deps_static"] + self.cfg["download_deps_shared"]
            if deps:
                self.log.info("Creating the installation directory before the configure.")
                self.make_installdir()
                self.cfg["keeppreviousinstall"] = True
                for dep in set(deps):
                    self.cfg.update('configopts', '--download-%s=1' % dep)
                for dep in self.cfg["download_deps_static"]:
                    self.cfg.update('configopts', '--download-%s-shared=0' % dep)
                for dep in self.cfg["download_deps_shared"]:
                    self.cfg.update('configopts', '--download-%s-shared=1' % dep)

            # compilers
            self.cfg.update('configopts', '--with-cc="%s"' % os.getenv('CC'))
            self.cfg.update('configopts', '--with-cxx="%s" --with-c++-support' % os.getenv('CXX'))
            self.cfg.update('configopts', '--with-fc="%s"' % os.getenv('F90'))

            # compiler flags
            # Don't build with MPI c++ bindings as this leads to a hard dependency
            # on libmpi and libmpi_cxx even for C code and non-MPI code
            cxxflags = os.getenv('CXXFLAGS') + ' ' + NO_MPI_CXX_EXT_FLAGS
            if LooseVersion(self.version) >= LooseVersion("3.5"):
                self.cfg.update('configopts', '--CFLAGS="%s"' % os.getenv('CFLAGS'))
                self.cfg.update('configopts', '--CXXFLAGS="%s"' % cxxflags)
                self.cfg.update('configopts', '--FFLAGS="%s"' % os.getenv('F90FLAGS'))
            else:
                self.cfg.update('configopts', '--with-cflags="%s"' % os.getenv('CFLAGS'))
                self.cfg.update('configopts', '--with-cxxflags="%s"' % cxxflags)
                self.cfg.update('configopts', '--with-fcflags="%s"' % os.getenv('F90FLAGS'))

            if not self.toolchain.comp_family() == toolchain.GCC:  # @UndefinedVariable
                self.cfg.update('configopts', '--with-gnu-compilers=0')

            # MPI
            if self.toolchain.options.get('usempi', None):
                self.cfg.update('configopts', '--with-mpi=1')

            # build options
            self.cfg.update('configopts', '--with-build-step-np=%s' % self.cfg['parallel'])
            self.cfg.update('configopts', '--with-shared-libraries=%d' % self.cfg['shared_libs'])
            self.cfg.update('configopts', '--with-debugging=%d' % self.toolchain.options['debug'])
            self.cfg.update('configopts', '--with-pic=%d' % self.toolchain.options['pic'])
            self.cfg.update('configopts', '--with-x=0 --with-windows-graphics=0')

            # PAPI support
            if self.cfg['with_papi']:
                papi_inc = self.cfg['papi_inc']
                papi_inc_file = os.path.join(papi_inc, "papi.h")
                papi_lib = self.cfg['papi_lib']
                if os.path.isfile(papi_inc_file) and os.path.isfile(papi_lib):
                    self.cfg.update('configopts', '--with-papi=1')
                    self.cfg.update('configopts', '--with-papi-include=%s' % papi_inc)
                    self.cfg.update('configopts', '--with-papi-lib=%s' % papi_lib)
                else:
                    raise EasyBuildError("PAPI header (%s) and/or lib (%s) not found, can not enable PAPI support?",
                                         papi_inc_file, papi_lib)

            # Python extensions_step
            if self.with_python:

                # enable numpy support, but only if numpy is available
                (_, ec) = run_cmd("python -s -c 'import numpy'", log_all=True, simple=False)
                if ec == 0:
                    self.cfg.update('configopts', '--with-numpy=1')

                # enable mpi4py support, but only if mpi4py is available
                (_, ec) = run_cmd("python -s -c 'import mpi4py'", log_all=True, simple=False)
                if ec == 0:
                    with_mpi4py_opt = '--with-mpi4py'
                    if self.cfg['shared_libs'] and with_mpi4py_opt not in self.cfg['configopts']:
                        self.cfg.update('configopts', '%s=1' % with_mpi4py_opt)

            # FFTW, ScaLAPACK (and BLACS for older PETSc versions)
            deps = ["FFTW", "ScaLAPACK"]
            if LooseVersion(self.version) < LooseVersion("3.5"):
                deps.append("BLACS")
            for dep in deps:
                libdir = os.getenv('%s_LIB_DIR' % dep.upper())
                libs = os.getenv('%s_STATIC_LIBS' % dep.upper())
                if libdir and libs:
                    with_arg = "--with-%s" % dep.lower()
                    self.cfg.update('configopts', '%s=1' % with_arg)
                    self.cfg.update('configopts', '%s-lib=[%s/%s]' % (with_arg, libdir, libs))

                    inc = os.getenv('%s_INC_DIR' % dep.upper())
                    if inc:
                        self.cfg.update('configopts', '%s-include=%s' % (with_arg, inc))
                else:
                    self.log.info("Missing inc/lib info, so not enabling %s support." % dep)

            # BLAS, LAPACK libraries
            bl_libdir = os.getenv('BLAS_LAPACK_LIB_DIR')
            bl_libs = os.getenv('BLAS_LAPACK_STATIC_LIBS')
            if bl_libdir and bl_libs:
                self.cfg.update('configopts', '--with-blas-lapack-lib=[%s/%s]' % (bl_libdir, bl_libs))
            else:
                raise EasyBuildError("One or more environment variables for BLAS/LAPACK not defined?")

            # additional dependencies
            # filter out deps handled seperately
            sep_deps = ['BLACS', 'BLAS', 'CMake', 'FFTW', 'LAPACK', 'numpy',
                        'mpi4py', 'papi', 'ScaLAPACK', 'SciPy-bundle', 'SuiteSparse']
            # SCOTCH has to be treated separately since they add weird postfixes
            # to library names from SCOTCH 7.0.1 or PETSc version 3.17.
            if (LooseVersion(self.version) >= LooseVersion("3.17")):
                sep_deps.append('SCOTCH')
            depfilter = [d['name'] for d in self.cfg.builddependencies()] + sep_deps

            deps = [dep['name'] for dep in self.cfg.dependencies() if not dep['name'] in depfilter]
            for dep in deps:
                if isinstance(dep, string_type):
                    dep = (dep, dep)
                deproot = get_software_root(dep[0])
                if deproot:
                    if (LooseVersion(self.version) >= LooseVersion("3.5")) and (dep[1] == "SCOTCH"):
                        withdep = "--with-pt%s" % dep[1].lower()  # --with-ptscotch is the configopt PETSc >= 3.5
                    else:
                        withdep = "--with-%s" % dep[1].lower()
                    self.cfg.update('configopts', '%s=1 %s-dir=%s' % (withdep, withdep, deproot))

            # SCOTCH has to be treated separately since they add weird postfixes
            # to library names from SCOTCH 7.0.1 or PETSc version 3.17.
            scotch = get_software_root('SCOTCH')
            scotch_ver = get_software_version('SCOTCH')
            if (scotch and LooseVersion(scotch_ver) >= LooseVersion("7.0")):
                withdep = "--with-ptscotch"
                scotch_inc = [os.path.join(scotch, "include")]
                inc_spec = "-include=[%s]" % ','.join(scotch_inc)

                # For some reason there is a v3 suffix added to libptscotchparmetis
                # which is the reason for this new code;
                # note: order matters here, don't sort these alphabetically!
                req_scotch_libs = ['libptesmumps.a', 'libptscotchparmetisv3.a', 'libptscotch.a',
                                   'libptscotcherr.a', 'libesmumps.a', 'libscotch.a', 'libscotcherr.a']
                scotch_libs = [os.path.join(scotch, "lib", x) for x in req_scotch_libs]
                lib_spec = "-lib=[%s]" % ','.join(scotch_libs)
                self.cfg.update('configopts', ' '.join([withdep + spec for spec in ['=1', inc_spec, lib_spec]]))

            # SuiteSparse options changed in PETSc 3.5,
            suitesparse = get_software_root('SuiteSparse')
            if suitesparse:
                if LooseVersion(self.version) >= LooseVersion("3.5"):
                    withdep = "--with-suitesparse"
                    # specified order of libs matters!
                    ss_libs = ["UMFPACK", "KLU", "CHOLMOD", "BTF", "CCOLAMD", "COLAMD", "CAMD", "AMD"]
                    # More libraries added after version 3.17
                    if LooseVersion(self.version) >= LooseVersion("3.17"):
                        ss_libs = ["UMFPACK", "KLU", "SPQR", "CHOLMOD", "BTF", "CCOLAMD",
                                   "COLAMD", "CXSparse", "LDL", "RBio", "SLIP_LU", "CAMD", "AMD"]

                    # SLIP_LU was replaced by SPEX in SuiteSparse >= 6.0
                    if LooseVersion(get_software_version('SuiteSparse')) >= LooseVersion("6.0"):
                        ss_libs = [x if x != "SLIP_LU" else "SPEX" for x in ss_libs]

                    suitesparse_inc = os.path.join(suitesparse, "include")
                    suitesparse_incs = [suitesparse_inc]
                    # SuiteSparse can install its headers into a subdirectory of the include directory instead.
                    suitesparse_inc_subdir = os.path.join(suitesparse_inc, 'suitesparse')
                    if os.path.exists(suitesparse_inc_subdir):
                        suitesparse_incs.append(suitesparse_inc_subdir)
                    inc_spec = "-include=[%s]" % ','.join(suitesparse_incs)

                    suitesparse_libs = [os.path.join(suitesparse, "lib", "lib%s.so" % x.replace("_", "").lower())
                                        for x in ss_libs]
                    lib_spec = "-lib=[%s]" % ','.join(suitesparse_libs)
                else:
                    # CHOLMOD and UMFPACK are part of SuiteSparse (PETSc < 3.5)
                    withdep = "--with-umfpack"
                    inc_spec = "-include=%s" % os.path.join(suitesparse, "include")
                    # specified order of libs matters!
                    umfpack_libs = [os.path.join(suitesparse, "lib", "lib%s.a" % x.lower())
                                    for x in ["UMFPACK", "CHOLMOD", "COLAMD", "AMD"]]
                    lib_spec = "-lib=[%s]" % ','.join(umfpack_libs)

                self.cfg.update('configopts', ' '.join([withdep + spec for spec in ['=1', inc_spec, lib_spec]]))

            # set PETSC_DIR for configure (env) and build_step
            petsc_dir = self.cfg['start_dir'].rstrip(os.path.sep)
            env.setvar('PETSC_DIR', petsc_dir)
            self.cfg.update('buildopts', 'PETSC_DIR=%s' % petsc_dir)

            if self.cfg['sourceinstall']:
                if self.petsc_arch:
                    env.setvar('PETSC_ARCH', self.cfg['petsc_arch'])

                # run configure without --prefix (required)
                cmd = "%s ./configure %s" % (self.cfg['preconfigopts'], self.cfg['configopts'])
                (out, _) = run_cmd(cmd, log_all=True, simple=False)
            else:
                out = super(EB_PETSc, self).configure_step()

            # check for errors in configure
            error_regexp = re.compile("ERROR")
            if error_regexp.search(out):
                raise EasyBuildError("Error(s) detected in configure output!")

            if self.cfg['sourceinstall']:
                # figure out PETSC_ARCH setting
                petsc_arch_regex = re.compile(r"^\s*PETSC_ARCH:\s*(\S+)$", re.M)
                res = petsc_arch_regex.search(out)
                if res:
                    self.petsc_arch = res.group(1)
                    self.cfg.update('buildopts', 'PETSC_ARCH=%s' % self.petsc_arch)
                else:
                    raise EasyBuildError("Failed to determine PETSC_ARCH setting.")

                self.petsc_subdir = self.name.lower()
                self.prefix_lib = os.path.join(self.petsc_subdir, self.petsc_arch)
                self.prefix_inc = os.path.join(self.petsc_subdir, self.petsc_arch)
                self.prefix_bin = os.path.join(self.petsc_subdir, self.petsc_arch)
            else:
                self.petsc_subdir = '%s-%s' % (self.name.lower(), self.version)

        else:  # old versions (< 3.x)

            self.cfg.update('configopts', '--prefix=%s' % self.installdir)
            self.cfg.update('configopts', '--with-shared=1')

            # additional dependencies
            for dep in ["SCOTCH"]:
                deproot = get_software_root(dep)
                if deproot:
                    withdep = "--with-%s" % dep.lower()
                    self.cfg.update('configopts', '%s=1 %s-dir=%s' % (withdep, withdep, deproot))

            cmd = "./config/configure.py %s" % self.get_cfg('configopts')
            run_cmd(cmd, log_all=True, simple=True)

        # Make sure to set test_parallel before self.cfg['parallel'] is set to None
        if self.cfg['test_parallel'] is None and self.cfg['parallel']:
            self.cfg['test_parallel'] = self.cfg['parallel']

        # PETSc > 3.5, make does not accept -j
        # to control parallel build, we need to specify MAKE_NP=... as argument to 'make' command
        if LooseVersion(self.version) >= LooseVersion("3.5"):
            self.cfg.update('buildopts', "MAKE_NP=%s" % self.cfg['parallel'])
            self.cfg['parallel'] = None

    # default make should be fine

    def test_step(self):
        """
        Test the compilation
        """

        # Each PETSc test may use multiple threads, so running "self.cfg['parallel']" of them may lead to
        # some oversubscription every now and again. Not a big deal, but if needed a reduced parallelism
        # can be specified with test_parallel - and it takes priority
        paracmd = ''
        self.log.info("In test_step: %s" % self.cfg['test_parallel'])
        if self.cfg['test_parallel'] is not None:
            paracmd = "-j %s" % self.cfg['test_parallel']

        if self.cfg['runtest']:
            cmd = "%s make %s %s %s" % (self.cfg['pretestopts'], paracmd, self.cfg['runtest'], self.cfg['testopts'])
            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            return out

    def install_step(self):
        """
        Install using make install (for non-source installations),
        or by symlinking files (old versions, < 3).
        """
        if LooseVersion(self.version) >= LooseVersion("3"):
            if not self.cfg['sourceinstall']:
                super(EB_PETSc, self).install_step()
                petsc_root = self.installdir
            else:
                petsc_root = os.path.join(self.installdir, self.petsc_subdir)
            # Remove MPI-CXX flags added during configure to prevent them from being passed to consumers of PETsc
            petsc_variables_path = os.path.join(petsc_root, 'lib', 'petsc', 'conf', 'petscvariables')
            if os.path.isfile(petsc_variables_path):
                fix = (r'^(CXX_FLAGS|CXX_LINKER_FLAGS|CONFIGURE_OPTIONS)( = .*)%s(.*)$' % NO_MPI_CXX_EXT_FLAGS,
                       r'\1\2\3')
                apply_regex_substitutions(petsc_variables_path, [fix])

        else:  # old versions (< 3.x)

            for fn in ['petscconf.h', 'petscconfiginfo.h', 'petscfix.h', 'petscmachineinfo.h']:
                includedir = os.path.join(self.installdir, 'include')
                bmakedir = os.path.join(self.installdir, 'bmake', 'linux-gnu-c-opt')
                symlink(os.path.join(bmakedir, fn), os.path.join(includedir, fn))

    def make_module_req_guess(self):
        """Specify PETSc custom values for PATH, CPATH and LD_LIBRARY_PATH."""

        guesses = super(EB_PETSc, self).make_module_req_guess()

        guesses.update({
            'CPATH': [os.path.join(self.prefix_lib, 'include'), os.path.join(self.prefix_inc, 'include')],
            'LD_LIBRARY_PATH': [os.path.join(self.prefix_lib, 'lib')],
            'PATH': [os.path.join(self.prefix_bin, 'bin')],
            # see https://www.mcs.anl.gov/petsc/documentation/faq.html#sparse-matrix-ascii-format
            'PYTHONPATH': [os.path.join('lib', 'petsc', 'bin')],
        })

        return guesses

    def make_module_extra(self):
        """Set PETSc specific environment variables (PETSC_DIR, PETSC_ARCH)."""
        txt = super(EB_PETSc, self).make_module_extra()

        if self.cfg['sourceinstall']:
            txt += self.module_generator.set_environment('PETSC_DIR', os.path.join(self.installdir, self.petsc_subdir))
            txt += self.module_generator.set_environment('PETSC_ARCH', self.petsc_arch)
        else:
            txt += self.module_generator.set_environment('PETSC_DIR', self.installdir)

        return txt

    def sanity_check_step(self):
        """Custom sanity check for PETSc"""

        if self.cfg['shared_libs']:
            libext = get_shared_lib_ext()
        else:
            libext = 'a'

        custom_paths = {
            'files': [os.path.join(self.prefix_lib, 'lib', 'libpetsc.%s' % libext)],
            'dirs': [os.path.join(self.prefix_bin, 'bin'), os.path.join(self.prefix_inc, 'include'),
                     os.path.join(self.prefix_lib, 'include')]
        }
        if LooseVersion(self.version) < LooseVersion('3.6'):
            custom_paths['dirs'].append(os.path.join(self.prefix_lib, 'conf'))
        else:
            custom_paths['dirs'].append(os.path.join(self.prefix_lib, 'lib', 'petsc', 'conf'))

        custom_commands = []
        if self.with_python:
            custom_commands.append("python -m PetscBinaryIO --help")

        super(EB_PETSc, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
