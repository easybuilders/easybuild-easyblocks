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
EasyBuild support for Quantum ESPRESSO, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Ake Sandgren (HPC2N, Umea University)
@author: Davide Grassano (CECAM, EPFL)
"""
import fileinput
import os
import re
import shutil
import sys

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_dir, copy_file
from easybuild.tools.modules import get_software_root, get_software_version

from easybuild.easyblocks.generic.configuremake import ConfigureMake


class EB_QuantumESPRESSO(ConfigureMake):
    """Support for building and installing Quantum ESPRESSO."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for Quantum ESPRESSO."""
        extra_vars = {
            'hybrid': [False, "Enable hybrid build (with OpenMP)", CUSTOM],
            'with_scalapack': [True, "Enable ScaLAPACK support", CUSTOM],
            'with_ace': [False, "Enable Adaptively Compressed Exchange support", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Add extra config options specific to Quantum ESPRESSO."""
        super(EB_QuantumESPRESSO, self).__init__(*args, **kwargs)

        self.install_subdir = "qe-%s" % self.version

    def patch_step(self):
        """Patch files from build dir (not start dir)."""
        super(EB_QuantumESPRESSO, self).patch_step(beginpath=self.builddir)

    def _add_compiler_flags(self, comp_fam):
        """Add compiler flags to the build."""
        allowed_toolchains = [toolchain.INTELCOMP, toolchain.GCC]
        if comp_fam not in allowed_toolchains:
            raise EasyBuildError("EasyBuild does not yet have support for QuantumESPRESSO with toolchain %s" % comp_fam)

        if LooseVersion(self.version) >= LooseVersion("6.1"):
            if comp_fam == toolchain.INTELCOMP:
                self.dflags += ["-D__INTEL_COMPILER"]
            elif comp_fam == toolchain.GCC:
                self.dflags += ["-D__GFORTRAN__"]
        elif LooseVersion(self.version) >= LooseVersion("5.2.1"):
            if comp_fam == toolchain.INTELCOMP:
                self.dflags += ["-D__INTEL"]
            elif comp_fam == toolchain.GCC:
                self.dflags += ["-D__GFORTRAN"]
        elif LooseVersion(self.version) >= LooseVersion("5.0"):
            if comp_fam == toolchain.INTELCOMP:
                self.dflags += ["-D__INTEL"]
            elif comp_fam == toolchain.GCC:
                self.dflags += ["-D__GFORTRAN", "-D__STD_F95"]

    def _add_openmp(self):
        """Add OpenMP support to the build."""
        if self.toolchain.options.get('openmp', False) or self.cfg['hybrid']:
            self.cfg.update('configopts', '--enable-openmp')
            if LooseVersion(self.version) >= LooseVersion("6.2.1"):
                self.dflags += ["-D_OPENMP"]
            elif LooseVersion(self.version) >= LooseVersion("5.0"):
                self.dflags += ["-D__OPENMP"]

    def _add_mpi(self):
        """Add MPI support to the build."""
        if not self.toolchain.options.get('usempi', False):
            self.cfg.update('configopts', '--disable-parallel')
        else:
            self.cfg.update('configopts', '--enable-parallel')
            if LooseVersion(self.version) >= LooseVersion("6.0"):
                self.dflags += ["-D__MPI"]
            elif LooseVersion(self.version) >= LooseVersion("5.0"):
                self.dflags += ["-D__MPI", "-D__PARA"]

    def _add_scalapack(self, comp_fam):
        """Add ScaLAPACK support to the build."""
        if not self.cfg['with_scalapack']:
            self.cfg.update('configopts', '--without-scalapack')
        else:
            if comp_fam == toolchain.INTELCOMP:
                if get_software_root("impi") and get_software_root("imkl"):
                    if LooseVersion(self.version) >= LooseVersion("6.2"):
                        self.cfg.update('configopts', '--with-scalapack=intel')
                    elif LooseVersion(self.version) >= LooseVersion("5.1.1"):
                        self.cfg.update('configopts', '--with-scalapack=intel')
                        self.repls += [
                            ('SCALAPACK_LIBS', os.getenv('LIBSCALAPACK'), False)
                        ]
                    elif LooseVersion(self.version) >= LooseVersion("5.0"):
                        self.cfg.update('configopts', '--with-scalapack=yes')
                    self.dflags += ["-D__SCALAPACK"]
            elif comp_fam == toolchain.GCC:
                if get_software_root("OpenMPI") and get_software_root("ScaLAPACK"):
                    self.cfg.update('configopts', '--with-scalapack=yes')
                    self.dflags += ["-D__SCALAPACK"]
            else:
                self.cfg.update('configopts', '--without-scalapack')

    def _add_libxc(self):
        """Add libxc support to the build."""
        libxc = get_software_root("libxc")
        if not libxc:
            return

        libxc_v = get_software_version("libxc")
        if LooseVersion(libxc_v) < LooseVersion("3.0.1"):
            raise EasyBuildError("Must use libxc >= 3.0.1")
        if LooseVersion(self.version) >= LooseVersion("7.0"):
            if LooseVersion(libxc_v) < LooseVersion("6.0.0"):
                raise EasyBuildError("libxc support for QuantumESPRESSO 7.0 only available for libxc >= 6.0.0")
            self.cfg.update('configopts', '--with-libxc=yes')
            self.cfg.update('configopts', '--with-libxc-prefix=%s' % libxc)
        elif LooseVersion(self.version) >= LooseVersion("6.4"):
            if LooseVersion(libxc_v) >= LooseVersion("5.0"):
                raise EasyBuildError("libxc support for QuantumESPRESSO 6.x only available for libxc <= 4.3.4")
            self.cfg.update('configopts', '--with-libxc=yes')
            self.cfg.update('configopts', '--with-libxc-prefix=%s' % libxc)
        else:
            self.extra_libs.append(" -lxcf90 -lxc")

        self.dflags += ["-D__LIBXC"]

    def _add_hdf5(self):
        """Add HDF5 support to the build."""
        hdf5 = get_software_root("HDF5")
        if not hdf5:
            return
        self.cfg.update('configopts', '--with-hdf5=%s' % hdf5)
        self.dflags += ["-D__HDF5"]
        hdf5_lib_repl = '-L%s/lib -lhdf5hl_fortran -lhdf5_hl -lhdf5_fortran -lhdf5 -lsz -lz -ldl -lm' % hdf5
        self.repls += [('HDF5_LIB', hdf5_lib_repl, False)]

        if LooseVersion(self.version) >= LooseVersion("6.2.1"):
            pass
        else:
            # Should be experimental in 6.0 but gives segfaults when used
            raise EasyBuildError("HDF5 support is only available in QuantumESPRESSO 6.2.1 and later")

    def _add_elpa(self):
        """Add ELPA support to the build."""
        elpa = get_software_root("ELPA")
        if not elpa:
            return

        elpa_v = get_software_version("ELPA")

        if LooseVersion(elpa_v) < LooseVersion("2015"):
            raise EasyBuildError("ELPA versions lower than 2015 are not supported")

        if LooseVersion(self.version) >= LooseVersion("6.8"):
            if LooseVersion(elpa_v) >= LooseVersion("2018.11"):
                self.dflags += ["-D__ELPA"]
            elif LooseVersion(elpa_v) >= LooseVersion("2016.11"):
                self.dflags += ["-D__ELPA_2016"]
            elif LooseVersion(elpa_v) >= LooseVersion("2015"):
                self.dflags += ["-D__ELPA_2015"]
        elif LooseVersion(self.version) >= LooseVersion("6.6"):
            if LooseVersion(elpa_v) >= LooseVersion("2020"):
                raise EasyBuildError("ELPA support for QuantumESPRESSO 6.6 only available up to v2019.xx")
            elif LooseVersion(elpa_v) >= LooseVersion("2018"):
                self.dflags += ["-D__ELPA"]
            elif LooseVersion(elpa_v) >= LooseVersion("2015"):
                elpa_year_v = elpa_v.split('.')[0]
                self.dflags += ["-D__ELPA_%s" % elpa_year_v]
        elif LooseVersion(self.version) >= LooseVersion("6.0"):
            if LooseVersion(elpa_v) >= LooseVersion("2017"):
                raise EasyBuildError("ELPA support for QuantumESPRESSO 6.x only available up to v2016.xx")
            elif LooseVersion(elpa_v) >= LooseVersion("2016"):
                self.dflags += ["-D__ELPA_2016"]
            elif LooseVersion(elpa_v) >= LooseVersion("2015"):
                self.dflags += ["-D__ELPA_2015"]
        elif LooseVersion(self.version) >= LooseVersion("5.4"):
            self.dflags += ["-D__ELPA"]
            self.cfg.update('configopts', '--with-elpa=%s' % elpa)
            return
        elif LooseVersion(self.version) >= LooseVersion("5.1.1"):
            self.cfg.update('configopts', '--with-elpa=%s' % elpa)
            return
        else:
            raise EasyBuildError("ELPA support is only available in QuantumESPRESSO 5.1.1 and later")

        if self.toolchain.options.get('openmp', False):
            elpa_include = 'elpa_openmp-%s' % elpa_v
            elpa_lib = 'libelpa_openmp.a'
        else:
            elpa_include = 'elpa-%s' % elpa_v
            elpa_lib = 'libelpa.a'
        elpa_include = os.path.join(elpa, 'include', elpa_include, 'modules')
        elpa_lib = os.path.join(elpa, 'lib', elpa_lib)
        self.repls += [
            ('IFLAGS', '-I%s' % elpa_include, True)
            ]
        self.cfg.update('configopts', '--with-elpa-include=%s' % elpa_include)
        self.cfg.update('configopts', '--with-elpa-lib=%s' % elpa_lib)
        if LooseVersion(self.version) < LooseVersion("7.0"):
            self.repls += [
                ('SCALAPACK_LIBS', '%s %s' % (elpa_lib, os.getenv("LIBSCALAPACK")), False)
                ]

    def _add_fftw(self, comp_fam):
        """Add FFTW support to the build."""
        if self.toolchain.options.get('openmp', False):
            libfft = os.getenv('LIBFFT_MT')
        else:
            libfft = os.getenv('LIBFFT')

        if LooseVersion(self.version) >= LooseVersion("5.2.1"):
            if comp_fam == toolchain.INTELCOMP and get_software_root("imkl"):
                self.dflags += ["-D__DFTI"]
            elif libfft:
                self.dflags += ["-D__FFTW"] if "fftw3" not in libfft else ["-D__FFTW3"]
                env.setvar('FFTW_LIBS', libfft)
        elif LooseVersion(self.version) >= LooseVersion("5.0"):
            if libfft:
                self.dflags += ["-D__FFTW"] if "fftw3" not in libfft else ["-D__FFTW3"]
                env.setvar('FFTW_LIBS', libfft)

    def _add_ace(self):
        """Add ACE support to the build."""
        if not self.cfg['with_ace']:
            return

        if LooseVersion(self.version) >= LooseVersion("6.2"):
            self.log.warning("ACE support is not available in QuantumESPRESSO >= 6.2")
        elif LooseVersion(self.version) >= LooseVersion("6.0"):
            self.dflags += ["-D__EXX_ACE"]
        else:
            self.log.warning("ACE support is not available in QuantumESPRESSO < 6.0")

    def _add_beef(self):
        """Add BEEF support to the build."""
        if LooseVersion(self.version) == LooseVersion("6.6"):
            libbeef = get_software_root("libbeef")
            if libbeef:
                self.dflags += ["-Duse_beef"]
                libbeef_lib = os.path.join(libbeef, 'lib')
                self.cfg.update('configopts', '--with-libbeef-prefix=%s' % libbeef_lib)
                self.repls += [
                    ('BEEF_LIBS_SWITCH', 'external', False),
                    ('BEEF_LIBS', str(os.path.join(libbeef_lib, "libbeef.a")), False)
                ]

    def _adjust_compiler_flags(self, comp_fam):
        """Adjust compiler flags based on the compiler family and code version."""
        if comp_fam == toolchain.INTELCOMP:
            if LooseVersion("6.0") <= LooseVersion(self.version) <= LooseVersion("6.4"):
                i_mpi_cc = os.getenv('I_MPI_CC', '')
                if i_mpi_cc == 'icx':
                    env.setvar('I_MPI_CC', 'icc')  # Needed as clib/qmmm_aux.c using <math.h> implicitly
        elif comp_fam == toolchain.GCC:
            pass

    def configure_step(self):
        """Custom configuration procedure for Quantum ESPRESSO."""

        # compose list of DFLAGS (flag, value, keep_stuff)
        # for guidelines, see include/defs.h.README in sources
        self.dflags = []
        self.repls = []
        self.extra_libs = []

        comp_fam = self.toolchain.comp_family()

        self._add_compiler_flags(comp_fam)
        self._add_openmp()
        self._add_mpi()
        self._add_scalapack(comp_fam)
        self._add_libxc()
        self._add_hdf5()
        self._add_elpa()
        self._add_fftw(comp_fam)
        self._add_ace()
        self._add_beef()

        if comp_fam == toolchain.INTELCOMP:
            # Intel compiler must have -assume byterecl (see install/configure)
            self.repls.append(('F90FLAGS', '-fpp -assume byterecl', True))
            self.repls.append(('FFLAGS', '-assume byterecl', True))
        elif comp_fam == toolchain.GCC:
            f90_flags = ['-cpp']
            if LooseVersion(get_software_version('GCC')) >= LooseVersion('10'):
                f90_flags.append('-fallow-argument-mismatch')
            self.repls.append(('F90FLAGS', ' '.join(f90_flags), True))

        self._adjust_compiler_flags(comp_fam)

        super(EB_QuantumESPRESSO, self).configure_step()

        # always include -w to supress warnings
        self.dflags.append('-w')

        self.repls.append(('DFLAGS', ' '.join(self.dflags), False))

        # complete C/Fortran compiler and LD flags
        if self.toolchain.options.get('openmp', False) or self.cfg['hybrid']:
            self.repls.append(('LDFLAGS', self.toolchain.get_flag('openmp'), True))
            self.repls.append(('(?:C|F90|F)FLAGS', self.toolchain.get_flag('openmp'), True))

        # obtain library settings
        libs = []
        if comp_fam == toolchain.GCC:
            num_libs = ['BLAS', 'LAPACK', 'FFT']
            if self.cfg['with_scalapack']:
                num_libs.extend(['SCALAPACK'])
            elpa = get_software_root('ELPA')
            elpa_lib = os.path.join(elpa or '', 'lib', 'libelpa.a' if self.toolchain.options.get('openmp', False) else 'libelpa_openmp.a')
            for lib in num_libs:
                if self.toolchain.options.get('openmp', False):
                    val = os.getenv('LIB%s_MT' % lib)
                else:
                    val = os.getenv('LIB%s' % lib)
                if lib == 'SCALAPACK' and elpa:
                    val = ' '.join([elpa_lib, val])
                self.repls.append(('%s_LIBS' % lib, val, False))
                libs.append(val)
            libs = ' '.join(libs)

        self.repls.append(('BLAS_LIBS_SWITCH', 'external', False))
        self.repls.append(('LAPACK_LIBS_SWITCH', 'external', False))
        self.repls.append(('LD_LIBS', ' '.join(self.extra_libs + [os.getenv('LIBS')]), False))

        # Do not use external FoX.
        # FoX starts to be used in 6.2 and they use a patched version that
        # is newer than FoX 4.1.2 which is the latest release.
        # Ake Sandgren, 20180712
        if get_software_root('FoX'):
            raise EasyBuildError("Found FoX external module, QuantumESPRESSO" +
                                 "must use the version they include with the source.")

        self.log.debug("List of replacements to perform: %s" % str(self.repls))

        if LooseVersion(self.version) >= LooseVersion("6"):
            make_ext = '.inc'
        else:
            make_ext = '.sys'

        # patch make.sys file
        fn = os.path.join(self.cfg['start_dir'], 'make' + make_ext)
        try:
            for line in fileinput.input(fn, inplace=1, backup='.orig.eb'):
                for (k, v, keep) in self.repls:
                    # need to use [ \t]* instead of \s*, because vars may be undefined as empty,
                    # and we don't want to include newlines
                    if keep:
                        line = re.sub(fr"^({k}\s*=[ \t]*)(.*)$", fr"\1\2 {v}", line)
                    else:
                        line = re.sub(fr"^({k}\s*=[ \t]*).*$", fr"\1{v}", line)

                # fix preprocessing directives for .f90 files in make.sys if required
                if LooseVersion(self.version) < LooseVersion("6.0"):
                    if comp_fam == toolchain.GCC:
                        line = re.sub(r"^\t\$\(MPIF90\) \$\(F90FLAGS\) -c \$<",
                                      "\t$(CPP) -C $(CPPFLAGS) $< -o $*.F90\n" +
                                      "\t$(MPIF90) $(F90FLAGS) -c $*.F90 -o $*.o",
                                      line)

                if LooseVersion(self.version) == LooseVersion("6.6"):
                    # fix order of BEEF_LIBS in QE_LIBS
                    line = re.sub(r"^(QELIBS\s*=[ \t]*)(.*) \$\(BEEF_LIBS\) (.*)$",
                                  r"QELIBS = $(BEEF_LIBS) \2 \3", line)

                    # use FCCPP instead of CPP for Fortran headers
                    line = re.sub(r"\t\$\(CPP\) \$\(CPPFLAGS\) \$< -o \$\*\.fh",
                                  "\t$(FCCPP) $(CPPFLAGS) $< -o $*.fh", line)

                sys.stdout.write(line)
        except IOError as err:
            raise EasyBuildError("Failed to patch %s: %s", fn, err)

        with open(fn, "r") as f:
            self.log.debug("Contents of patched %s: %s" % (fn, f.read()))

        # patch default make.sys for wannier
        if LooseVersion(self.version) >= LooseVersion("5"):
            fn = os.path.join(self.cfg['start_dir'], 'install', 'make_wannier90' + make_ext)
        else:
            fn = os.path.join(self.cfg['start_dir'], 'plugins', 'install', 'make_wannier90.sys')
        try:
            for line in fileinput.input(fn, inplace=1, backup='.orig.eb'):
                line = re.sub(r"^(LIBS\s*=\s*).*", fr"\1{libs}", line)

                sys.stdout.write(line)

        except IOError as err:
            raise EasyBuildError("Failed to patch %s: %s", fn, err)

        with open(fn, "r") as f:
            self.log.debug("Contents of patched %s: %s" % (fn, f.read()))

        # patch Makefile of want plugin
        wantprefix = 'want-'
        wantdirs = [d for d in os.listdir(self.builddir) if d.startswith(wantprefix)]

        if len(wantdirs) > 1:
            raise EasyBuildError("Found more than one directory with %s prefix, help!", wantprefix)

        if len(wantdirs) != 0:
            wantdir = os.path.join(self.builddir, wantdirs[0])
            make_sys_in_path = None
            cand_paths = [os.path.join('conf', 'make.sys.in'), os.path.join('config', 'make.sys.in')]
            for path in cand_paths:
                full_path = os.path.join(wantdir, path)
                if os.path.exists(full_path):
                    make_sys_in_path = full_path
                    break
            if make_sys_in_path is None:
                raise EasyBuildError("Failed to find make.sys.in in want directory %s, paths considered: %s",
                                     wantdir, ', '.join(cand_paths))

            try:
                for line in fileinput.input(make_sys_in_path, inplace=1, backup='.orig.eb'):
                    # fix preprocessing directives for .f90 files in make.sys if required
                    if comp_fam == toolchain.GCC:
                        line = re.sub("@f90rule@",
                                      "$(CPP) -C $(CPPFLAGS) $< -o $*.F90\n" +
                                      "\t$(MPIF90) $(F90FLAGS) -c $*.F90 -o $*.o",
                                      line)

                    sys.stdout.write(line)
            except IOError as err:
                raise EasyBuildError("Failed to patch %s: %s", fn, err)

        # move non-espresso directories to where they're expected and create symlinks
        try:
            dirnames = [d for d in os.listdir(self.builddir) if d not in [self.install_subdir, 'd3q-latest']]
            targetdir = os.path.join(self.builddir, self.install_subdir)
            for dirname in dirnames:
                shutil.move(os.path.join(self.builddir, dirname), os.path.join(targetdir, dirname))
                self.log.info("Moved %s into %s" % (dirname, targetdir))

                dirname_head = dirname.split('-')[0]
                # Handle the case where the directory is preceded by 'qe-'
                if dirname_head == 'qe':
                    dirname_head = dirname.split('-')[1]
                linkname = None
                if dirname_head == 'sax':
                    linkname = 'SaX'
                if dirname_head == 'wannier90':
                    linkname = 'W90'
                elif dirname_head in ['d3q', 'gipaw', 'plumed', 'want', 'yambo']:
                    linkname = dirname_head.upper()
                if linkname:
                    os.symlink(os.path.join(targetdir, dirname), os.path.join(targetdir, linkname))

        except OSError as err:
            raise EasyBuildError("Failed to move non-espresso directories: %s", err)

    def install_step(self):
        """Custom install step for Quantum ESPRESSO."""

        # extract build targets as list
        targets = self.cfg['buildopts'].split()

        # Copy all binaries
        bindir = os.path.join(self.installdir, 'bin')
        copy_dir(os.path.join(self.cfg['start_dir'], 'bin'), bindir)

        # Pick up files not installed in bin
        def copy_binaries(path):
            full_dir = os.path.join(self.cfg['start_dir'], path)
            self.log.info("Looking for binaries in %s" % full_dir)
            for filename in os.listdir(full_dir):
                full_path = os.path.join(full_dir, filename)
                if os.path.isfile(full_path):
                    if filename.endswith('.x'):
                        copy_file(full_path, bindir)

        if 'upf' in targets or 'all' in targets:
            if LooseVersion(self.version) < LooseVersion("6.6"):
                copy_binaries('upftools')
            else:
                copy_binaries('upflib')
                copy_file(os.path.join(self.cfg['start_dir'], 'upflib', 'fixfiles.py'), bindir)

        if 'want' in targets:
            copy_binaries('WANT')

        if 'w90' in targets:
            copy_binaries('W90')

        if 'yambo' in targets:
            copy_binaries('YAMBO')

    def sanity_check_step(self):
        """Custom sanity check for Quantum ESPRESSO."""

        # extract build targets as list
        targets = self.cfg['buildopts'].split()

        bins = []
        if LooseVersion(self.version) < LooseVersion("6.7"):
            # build list of expected binaries based on make targets
            bins.extend(["iotk", "iotk.x", "iotk_print_kinds.x"])

        if 'cp' in targets or 'all' in targets:
            bins.extend(["cp.x", "wfdd.x"])
            if LooseVersion(self.version) < LooseVersion("6.4"):
                bins.append("cppp.x")

        # only for v4.x, not in v5.0 anymore, called gwl in 6.1 at least
        if 'gww' in targets or 'gwl' in targets:
            bins.extend(["gww_fit.x", "gww.x", "head.x", "pw4gww.x"])

        if 'ld1' in targets or 'all' in targets:
            bins.extend(["ld1.x"])

        if 'gipaw' in targets:
            bins.extend(["gipaw.x"])

        if 'neb' in targets or 'pwall' in targets or 'all' in targets:
            if LooseVersion(self.version) > LooseVersion("5"):
                bins.extend(["neb.x", "path_interpolation.x"])

        if 'ph' in targets or 'all' in targets:
            bins.extend(["dynmat.x", "lambda.x", "matdyn.x", "ph.x", "phcg.x", "q2r.x"])
            if LooseVersion(self.version) < LooseVersion("6"):
                bins.extend(["d3.x"])
            if LooseVersion(self.version) > LooseVersion("5"):
                bins.extend(["fqha.x", "q2qstar.x"])

        if 'pp' in targets or 'pwall' in targets or 'all' in targets:
            bins.extend(["average.x", "bands.x", "dos.x", "epsilon.x", "initial_state.x",
                         "plan_avg.x", "plotband.x", "plotproj.x", "plotrho.x", "pmw.x", "pp.x",
                         "projwfc.x", "sumpdos.x", "pw2wannier90.x", "pw2gw.x",
                         "wannier_ham.x", "wannier_plot.x"])
            if LooseVersion(self.version) > LooseVersion("5") and LooseVersion(self.version) < LooseVersion("6.4"):
                bins.extend(["pw2bgw.x", "bgw2pw.x"])
            elif LooseVersion(self.version) <= LooseVersion("5"):
                bins.extend(["pw2casino.x"])
            if LooseVersion(self.version) < LooseVersion("6.4"):
                bins.extend(["pw_export.x"])

        if 'pw' in targets or 'all' in targets:
            bins.extend(["dist.x", "ev.x", "kpoints.x", "pw.x", "pwi2xsf.x"])
            if LooseVersion(self.version) < LooseVersion("6.5"):
                if LooseVersion(self.version) >= LooseVersion("5.1"):
                    bins.extend(["generate_rVV10_kernel_table.x"])
                if LooseVersion(self.version) > LooseVersion("5"):
                    bins.extend(["generate_vdW_kernel_table.x"])
            if LooseVersion(self.version) <= LooseVersion("5"):
                bins.extend(["path_int.x"])
            if LooseVersion(self.version) < LooseVersion("5.3"):
                bins.extend(["band_plot.x", "bands_FS.x", "kvecs_FS.x"])

        if 'pwcond' in targets or 'pwall' in targets or 'all' in targets:
            bins.extend(["pwcond.x"])

        if 'tddfpt' in targets or 'all' in targets:
            if LooseVersion(self.version) > LooseVersion("5"):
                bins.extend(["turbo_lanczos.x", "turbo_spectrum.x"])

        upftools = []
        if 'upf' in targets or 'all' in targets:
            if LooseVersion(self.version) < LooseVersion("6.6"):
                upftools = ["casino2upf.x", "cpmd2upf.x", "fhi2upf.x", "fpmd2upf.x", "ncpp2upf.x",
                            "oldcp2upf.x", "read_upf_tofile.x", "rrkj2upf.x", "uspp2upf.x", "vdb2upf.x"]
                if LooseVersion(self.version) > LooseVersion("5"):
                    upftools.extend(["interpolate.x", "upf2casino.x"])
                if LooseVersion(self.version) >= LooseVersion("6.3"):
                    upftools.extend(["fix_upf.x"])
                if LooseVersion(self.version) < LooseVersion("6.4"):
                    upftools.extend(["virtual.x"])
                else:
                    upftools.extend(["virtual_v2.x"])
            else:
                upftools = ["upfconv.x", "virtual_v2.x", "fixfiles.py"]

        if 'vdw' in targets:  # only for v4.x, not in v5.0 anymore
            bins.extend(["vdw.x"])

        if 'w90' in targets:
            bins.extend(["wannier90.x"])
            if LooseVersion(self.version) >= LooseVersion("5.4"):
                bins.extend(["postw90.x"])
                if LooseVersion(self.version) < LooseVersion("6.1"):
                    bins.extend(["w90chk2chk.x"])

        want_bins = []
        if 'want' in targets:
            want_bins = ["blc2wan.x", "conductor.x", "current.x", "disentangle.x",
                         "dos.x", "gcube2plt.x", "kgrid.x", "midpoint.x", "plot.x", "sumpdos",
                         "wannier.x", "wfk2etsf.x"]
            if LooseVersion(self.version) > LooseVersion("5"):
                want_bins.extend(["cmplx_bands.x", "decay.x", "sax2qexml.x", "sum_sgm.x"])

        if 'xspectra' in targets:
            bins.extend(["xspectra.x"])

        yambo_bins = []
        if 'yambo' in targets:
            yambo_bins = ["a2y", "p2y", "yambo", "ypp"]

        d3q_bins = []
        if 'd3q' in targets:
            d3q_bins = ['d3_asr3.x', 'd3_lw.x', 'd3_q2r.x',
                        'd3_qq2rr.x', 'd3q.x', 'd3_r2q.x', 'd3_recenter.x',
                        'd3_sparse.x', 'd3_sqom.x', 'd3_tk.x']
            if LooseVersion(self.version) < LooseVersion("6.4"):
                d3q_bins.append('d3_import3py.x')

        custom_paths = {
            'files': [os.path.join('bin', x) for x in bins + upftools + want_bins + yambo_bins + d3q_bins],
            'dirs': []
        }

        super(EB_QuantumESPRESSO, self).sanity_check_step(custom_paths=custom_paths)
