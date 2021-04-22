##
# Copyright 2009-2021 Ghent University
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
"""
import fileinput
import os
import re
import shutil
import sys
from distutils.version import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_dir, copy_file
from easybuild.tools.modules import get_software_root, get_software_version


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

        if LooseVersion(self.version) >= LooseVersion("6"):
            self.install_subdir = "qe-%s" % self.version
        else:
            self.install_subdir = "espresso-%s" % self.version

    def patch_step(self):
        """Patch files from build dir (not start dir)."""
        super(EB_QuantumESPRESSO, self).patch_step(beginpath=self.builddir)

    def configure_step(self):
        """Custom configuration procedure for Quantum ESPRESSO."""

        # compose list of DFLAGS (flag, value, keep_stuff)
        # for guidelines, see include/defs.h.README in sources
        dflags = []

        repls = []

        extra_libs = []

        comp_fam_dflags = {
            toolchain.INTELCOMP: '-D__INTEL',
            toolchain.GCC: '-D__GFORTRAN -D__STD_F95',
        }
        comp_fam = self.toolchain.comp_family()
        if comp_fam in comp_fam_dflags:
            dflags.append(comp_fam_dflags[comp_fam])
        else:
            raise EasyBuildError("EasyBuild does not yet have support for QuantumESPRESSO with toolchain %s" % comp_fam)

        if self.toolchain.options.get('openmp', False) or self.cfg['hybrid']:
            self.cfg.update('configopts', '--enable-openmp')
            dflags.append(" -D__OPENMP")

        if self.toolchain.options.get('usempi', None):
            dflags.append('-D__MPI -D__PARA')
        else:
            self.cfg.update('configopts', '--disable-parallel')

        if self.cfg['with_scalapack']:
            dflags.append(" -D__SCALAPACK")
            if self.toolchain.options.get('usempi', None):
                if get_software_root("impi") and get_software_root("imkl"):
                    self.cfg.update('configopts', '--with-scalapack=intel')
        else:
            self.cfg.update('configopts', '--without-scalapack')

        libxc = get_software_root("libxc")
        if libxc:
            libxc_v = get_software_version("libxc")
            if LooseVersion(libxc_v) < LooseVersion("3.0.1"):
                raise EasyBuildError("Must use libxc >= 3.0.1")
            dflags.append(" -D__LIBXC")
            repls.append(('IFLAGS', '-I%s' % os.path.join(libxc, 'include'), True))
            if LooseVersion(self.version) < LooseVersion("6.5"):
                extra_libs.append(" -lxcf90 -lxc")
            else:
                extra_libs.append(" -lxcf90 -lxcf03 -lxc")

        hdf5 = get_software_root("HDF5")
        if hdf5:
            self.cfg.update('configopts', '--with-hdf5=%s' % hdf5)
            dflags.append(" -D__HDF5")
            hdf5_lib_repl = '-L%s/lib -lhdf5hl_fortran -lhdf5_hl -lhdf5_fortran -lhdf5 -lsz -lz -ldl -lm' % hdf5
            repls.append(('HDF5_LIB', hdf5_lib_repl, False))

        elpa = get_software_root("ELPA")
        if elpa:
            if not self.cfg['with_scalapack']:
                raise EasyBuildError("ELPA requires ScaLAPACK but 'with_scalapack' is set to False")

            elpa_v = get_software_version("ELPA")
            if LooseVersion(self.version) >= LooseVersion("6"):

                # NOTE: Quantum Espresso should use -D__ELPA_<year> for corresponding ELPA version
                # However for ELPA VERSION >= 2017.11 Quantum Espresso needs to use ELPA_2018
                # because of outdated bindings. See: https://xconfigure.readthedocs.io/en/latest/elpa/
                if LooseVersion("2018") > LooseVersion(elpa_v) >= LooseVersion("2017.11"):
                    dflags.append('-D__ELPA_2018')
                else:
                    # get year from LooseVersion
                    elpa_year_v = elpa_v.split('.')[0]
                    dflags.append('-D__ELPA_%s' % elpa_year_v)

                elpa_min_ver = "2016.11.001.pre"
            else:
                elpa_min_ver = "2015"
                dflags.append('-D__ELPA_2015 -D__ELPA')

            if LooseVersion(elpa_v) < LooseVersion(elpa_min_ver):
                raise EasyBuildError("QuantumESPRESSO %s needs ELPA to be " +
                                     "version %s or newer", self.version, elpa_min_ver)

            if self.toolchain.options.get('openmp', False):
                elpa_include = 'elpa_openmp-%s' % elpa_v
                elpa_lib = 'libelpa_openmp.a'
            else:
                elpa_include = 'elpa-%s' % elpa_v
                elpa_lib = 'libelpa.a'
            elpa_include = os.path.join(elpa, 'include', elpa_include)
            repls.append(('IFLAGS', '-I%s' % os.path.join(elpa_include, 'modules'), True))
            self.cfg.update('configopts', '--with-elpa-include=%s' % elpa_include)
            elpa_lib = os.path.join(elpa, 'lib', elpa_lib)
            self.cfg.update('configopts', '--with-elpa-lib=%s' % elpa_lib)

        if comp_fam == toolchain.INTELCOMP:
            # set preprocessor command (-E to stop after preprocessing, -C to preserve comments)
            cpp = "%s -E -C" % os.getenv('CC')
            repls.append(('CPP', cpp, False))
            env.setvar('CPP', cpp)

        # also define $FCCPP, but do *not* include -C (comments should not be preserved when preprocessing Fortran)
        env.setvar('FCCPP', "%s -E" % os.getenv('CC'))

        if comp_fam == toolchain.INTELCOMP:
            # Intel compiler must have -assume byterecl (see install/configure)
            repls.append(('F90FLAGS', '-fpp -assume byterecl', True))
            repls.append(('FFLAGS', '-assume byterecl', True))
        elif comp_fam == toolchain.GCC:
            f90_flags = ['-cpp']
            if LooseVersion(get_software_version('GCC')) >= LooseVersion('10'):
                f90_flags.append('-fallow-argument-mismatch')
            repls.append(('F90FLAGS', ' '.join(f90_flags), True))

        super(EB_QuantumESPRESSO, self).configure_step()

        if self.toolchain.options.get('openmp', False):
            libfft = os.getenv('LIBFFT_MT')
        else:
            libfft = os.getenv('LIBFFT')
        if libfft:
            if "fftw3" in libfft:
                dflags.append('-D__FFTW3')
            else:
                dflags.append('-D__FFTW')
            env.setvar('FFTW_LIBS', libfft)

        if get_software_root('ACML'):
            dflags.append('-D__ACML')

        if self.cfg['with_ace']:
            dflags.append(" -D__EXX_ACE")

        # always include -w to supress warnings
        dflags.append('-w')

        if LooseVersion(self.version) >= LooseVersion("6.6"):
            dflags.append(" -Duse_beef")
            libbeef = get_software_root("libbeef")
            if libbeef:
                repls.append(('BEEF_LIBS_SWITCH', 'external', False))
                repls.append(('BEEF_LIBS', '%s/lib/libbeef.a' % libbeef, False))

        repls.append(('DFLAGS', ' '.join(dflags), False))

        # complete C/Fortran compiler and LD flags
        if self.toolchain.options.get('openmp', False) or self.cfg['hybrid']:
            repls.append(('LDFLAGS', self.toolchain.get_flag('openmp'), True))
            repls.append(('(?:C|F90|F)FLAGS', self.toolchain.get_flag('openmp'), True))

        # obtain library settings
        libs = []
        num_libs = ['BLAS', 'LAPACK', 'FFT']
        if self.cfg['with_scalapack']:
            num_libs.extend(['SCALAPACK'])
        for lib in num_libs:
            if self.toolchain.options.get('openmp', False):
                val = os.getenv('LIB%s_MT' % lib)
            else:
                val = os.getenv('LIB%s' % lib)
            if lib == 'SCALAPACK' and elpa:
                val = ' '.join([elpa_lib, val])
            repls.append(('%s_LIBS' % lib, val, False))
            libs.append(val)
        libs = ' '.join(libs)

        repls.append(('BLAS_LIBS_SWITCH', 'external', False))
        repls.append(('LAPACK_LIBS_SWITCH', 'external', False))
        repls.append(('LD_LIBS', ' '.join(extra_libs + [os.getenv('LIBS')]), False))

        # Do not use external FoX.
        # FoX starts to be used in 6.2 and they use a patched version that
        # is newer than FoX 4.1.2 which is the latest release.
        # Ake Sandgren, 20180712
        if get_software_root('FoX'):
            raise EasyBuildError("Found FoX external module, QuantumESPRESSO" +
                                 "must use the version they include with the source.")

        self.log.debug("List of replacements to perform: %s" % repls)

        if LooseVersion(self.version) >= LooseVersion("6"):
            make_ext = '.inc'
        else:
            make_ext = '.sys'

        # patch make.sys file
        fn = os.path.join(self.cfg['start_dir'], 'make' + make_ext)
        try:
            for line in fileinput.input(fn, inplace=1, backup='.orig.eb'):
                for (k, v, keep) in repls:
                    # need to use [ \t]* instead of \s*, because vars may be undefined as empty,
                    # and we don't want to include newlines
                    if keep:
                        line = re.sub(r"^(%s\s*=[ \t]*)(.*)$" % k, r"\1\2 %s" % v, line)
                    else:
                        line = re.sub(r"^(%s\s*=[ \t]*).*$" % k, r"\1%s" % v, line)

                # fix preprocessing directives for .f90 files in make.sys if required
                if LooseVersion(self.version) < LooseVersion("6.0"):
                    if comp_fam == toolchain.GCC:
                        line = re.sub(r"^\t\$\(MPIF90\) \$\(F90FLAGS\) -c \$<",
                                      "\t$(CPP) -C $(CPPFLAGS) $< -o $*.F90\n" +
                                      "\t$(MPIF90) $(F90FLAGS) -c $*.F90 -o $*.o",
                                      line)

                if LooseVersion(self.version) >= LooseVersion("6.6"):
                    # fix order of BEEF_LIBS in QE_LIBS
                    line = re.sub(r"^(QELIBS\s*=[ \t]*)(.*) \$\(BEEF_LIBS\) (.*)$",
                                  r"QELIBS = $(BEEF_LIBS) \2 \3", line)

                    # use FCCPP instead of CPP for Fortran headers
                    line = re.sub(r"\t\$\(CPP\) \$\(CPPFLAGS\) \$< -o \$\*\.fh",
                                  "\t$(FCCPP) $(CPPFLAGS) $< -o $*.fh", line)

                sys.stdout.write(line)
        except IOError as err:
            raise EasyBuildError("Failed to patch %s: %s", fn, err)

        self.log.debug("Contents of patched %s: %s" % (fn, open(fn, "r").read()))

        # patch default make.sys for wannier
        if LooseVersion(self.version) >= LooseVersion("5"):
            fn = os.path.join(self.cfg['start_dir'], 'install', 'make_wannier90' + make_ext)
        else:
            fn = os.path.join(self.cfg['start_dir'], 'plugins', 'install', 'make_wannier90.sys')
        try:
            for line in fileinput.input(fn, inplace=1, backup='.orig.eb'):
                line = re.sub(r"^(LIBS\s*=\s*).*", r"\1%s" % libs, line)

                sys.stdout.write(line)

        except IOError as err:
            raise EasyBuildError("Failed to patch %s: %s", fn, err)

        self.log.debug("Contents of patched %s: %s" % (fn, open(fn, "r").read()))

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
            if LooseVersion(self.version) < LooseVersion("5.3.0"):
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
