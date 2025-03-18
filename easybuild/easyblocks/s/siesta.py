##
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
##
"""
EasyBuild support for building and installing Siesta, implemented as an easyblock

@author: Miguel Dias Costa (National University of Singapore)
@author: Ake Sandgren (Umea University)
"""
import os
import stat

import easybuild.tools.toolchain as toolchain
from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import adjust_permissions, apply_regex_substitutions
from easybuild.tools.filetools import change_dir, copy_dir, copy_file, mkdir
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Siesta(ConfigureMake):
    """
    Support for building/installing Siesta.
    - avoid parallel build for older versions
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra options for Siesta"""
        extra = {
            'with_transiesta': [True, "Build transiesta", CUSTOM],
            'with_utils': [True, "Build all utils", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars=extra)

    def configure_step(self):
        """
        Custom configure and build procedure for Siesta.
        - There are two main builds to do, siesta and transiesta
        - In addition there are multiple support tools to build
        """

        start_dir = self.cfg['start_dir']
        obj_dir = os.path.join(start_dir, 'Obj')
        arch_make = os.path.join(obj_dir, 'arch.make')
        bindir = os.path.join(start_dir, 'bin')

        version = self.version.replace('-b', '.0.2.').replace('-MaX-', '.')
        loose_ver = LooseVersion(version)

        par = ''
        if loose_ver >= LooseVersion('4.1'):
            par = f"-j {self.cfg.parallel}"

        # enable OpenMP support if desired
        env_var_suff = ''
        if self.toolchain.options.get('openmp', None):
            env_var_suff = '_MT'

        scalapack = os.environ['LIBSCALAPACK' + env_var_suff]
        blacs = os.environ['LIBSCALAPACK' + env_var_suff]
        lapack = os.environ['LIBLAPACK' + env_var_suff]
        blas = os.environ['LIBBLAS' + env_var_suff]
        if get_software_root('imkl') or get_software_root('FFTW'):
            # the only module that uses FFTW is STM and it explicitly wants a non-MPI version
            fftw = os.environ['LIBFFT_MT']
        else:
            fftw = None

        regex_newlines = []
        regex_subs = [
            ('dc_lapack.a', ''),
            (r'^NETCDF_INTERFACE\s*=.*$', ''),
            ('libsiestaBLAS.a', ''),
            ('libsiestaLAPACK.a', ''),
            # Needed here to allow 4.1-b1 to be built with openmp
            (r"^(LDFLAGS\s*=).*$", r"\1 %s %s" % (os.environ['FCFLAGS'], os.environ['LDFLAGS'])),
        ]

        regex_subs_gfortran = [
            (r"^(FCFLAGS_free_f90\s*=.*)$", r"\1 -ffree-line-length-none"),
            (r"^(FPPFLAGS_free_F90\s*=.*)$", r"\1 -ffree-line-length-none"),
        ]

        gfortran_flags = ''
        gcc_version = get_software_version('GCCcore') or get_software_version('GCC')
        if LooseVersion(gcc_version) >= LooseVersion('10.0') and LooseVersion(self.version) <= LooseVersion('4.1.5'):
            # -fallow-argument-mismatch is required when compiling with GCC 10.x & more recent
            gfortran_flags = '-fallow-argument-mismatch'

        netcdff_loc = get_software_root('netCDF-Fortran')
        if netcdff_loc:
            # Needed for gfortran at least
            regex_newlines.append((r"^(ARFLAGS_EXTRA\s*=.*)$", r"\1\nNETCDF_INCFLAGS = -I%s/include" % netcdff_loc))

        if fftw:
            fft_inc, fft_lib = os.environ['FFT_INC_DIR'], os.environ['FFT_LIB_DIR']
            fppflags = r"\1\nFFTW_INCFLAGS = -I%s\nFFTW_LIBS = -L%s %s" % (fft_inc, fft_lib, fftw)
            regex_newlines.append((r'(FPPFLAGS\s*:?=.*)$', fppflags))

        # Make a temp installdir during the build of the various parts
        mkdir(bindir)

        # change to actual build dir
        change_dir(obj_dir)

        # Populate start_dir with makefiles
        run_shell_cmd(os.path.join(start_dir, 'Src', 'obj_setup.sh'))

        if loose_ver < LooseVersion('4.1.0.2.2'):
            # MPI?
            if self.toolchain.options.get('usempi', None):
                self.cfg.update('configopts', '--enable-mpi')

            # BLAS and LAPACK
            self.cfg.update('configopts', '--with-blas="%s"' % blas)
            self.cfg.update('configopts', '--with-lapack="%s"' % lapack)

            # ScaLAPACK (and BLACS)
            self.cfg.update('configopts', '--with-scalapack="%s"' % scalapack)
            self.cfg.update('configopts', '--with-blacs="%s"' % blacs)

            # NetCDF-Fortran
            if netcdff_loc:
                self.cfg.update('configopts', '--with-netcdf=-lnetcdff')

            # Configure is run in obj_dir, configure script is in ../Src
            super(EB_Siesta, self).configure_step(cmd_prefix='../Src/')

            if loose_ver > LooseVersion('4.0'):
                regex_subs_Makefile = [
                    (r'CFLAGS\)-c', r'CFLAGS) -c'),
                ]
                apply_regex_substitutions('Makefile', regex_subs_Makefile)

            if self.toolchain.comp_family() in [toolchain.GCC]:
                apply_regex_substitutions(arch_make, regex_subs_gfortran)

        else:  # there's no configure on newer versions

            if self.toolchain.comp_family() in [toolchain.INTELCOMP]:
                copy_file(os.path.join(obj_dir, 'intel.make'), arch_make)
            elif self.toolchain.comp_family() in [toolchain.GCC]:
                copy_file(os.path.join(obj_dir, 'gfortran.make'), arch_make)
            else:
                raise EasyBuildError("There is currently no support for compiler: %s", self.toolchain.comp_family())

            regex_subs.append((r"^(FPPFLAGS\s*:?=.*)$", r"\1 -DF2003"))

            if self.toolchain.options.get('usempi', None):
                regex_subs.extend([
                    (r"^(CC\s*=\s*).*$", r"\1%s" % os.environ['MPICC']),
                    (r"^(FC\s*=\s*).*$", r"\1%s" % os.environ['MPIF90']),
                    (r"^(FPPFLAGS\s*:?=.*)$", r"\1 -DMPI"),
                ])
                regex_newlines.append((r"^(FPPFLAGS\s*:?=.*)$", r"\1\nMPI_INTERFACE = libmpi_f90.a\nMPI_INCLUDE = ."))
                complibs = scalapack
            else:
                complibs = lapack

            regex_subs.extend([
                (r"^(LIBS\s*=).*$", r"\1 %s" % complibs),
                # Needed for a couple of the utils
                (r"^(FFLAGS\s*=\s*).*$", r"\1 -fPIC %s %s" % (os.environ['FCFLAGS'], gfortran_flags)),
            ])
            regex_newlines.append((r"^(COMP_LIBS\s*=.*)$", r"\1\nWXML = libwxml.a"))

            if self.toolchain.comp_family() in [toolchain.GCC]:
                regex_subs.extend(regex_subs_gfortran)

            if netcdff_loc:
                regex_subs.extend([
                    (r"^(LIBS\s*=.*)$", r"\1 $(NETCDF_LIBS)"),
                    (r"^(FPPFLAGS\s*:?=.*)$", r"\1 -DCDF -DNCDF -DNCDF_4 -DNCDF_PARALLEL $(NETCDF_INCLUDE)"),
                    (r"^(COMP_LIBS\s*=.*)$", r"\1 libncdf.a libfdict.a"),
                ])
                netcdf_lib_and_inc = "NETCDF_LIBS = -lnetcdff\nNETCDF_INCLUDE = -I%s/include" % netcdff_loc
                netcdf_lib_and_inc += "\nINCFLAGS = $(NETCDF_INCLUDE)"
                regex_newlines.append((r"^(COMP_LIBS\s*=.*)$", r"\1\n%s" % netcdf_lib_and_inc))

            xmlf90 = get_software_root('xmlf90')
            if xmlf90:
                regex_subs.append((r"^(XMLF90_ROOT\s*=).*$", r"\1%s" % xmlf90))

            libpsml = get_software_root('libPSML')
            if libpsml:
                regex_subs.append((r"^(PSML_ROOT\s*=).*$.*", r"\1%s" % libpsml))

            libgridxc = get_software_root('libGridXC')
            if libgridxc:
                regex_subs.append((r"^(GRIDXC_ROOT\s*=).*$", r"\1%s" % libgridxc))

            libxc = get_software_root('libxc')
            if libxc:
                regex_subs.append((r"^#(LIBXC_ROOT\s*=).*$", r"\1 %s" % libxc))

            elpa = get_software_root('ELPA')
            if elpa:
                elpa_ver = get_software_version('ELPA')
                regex_subs.extend([
                    (r"^(FPPFLAGS\s*:?=.*)$", r"\1 -DSIESTA__ELPA"),
                    (r"^(FPPFLAGS\s*:?=.*)$", r"\1 -I%s/include/elpa-%s/modules" % (elpa, elpa_ver)),
                    (r"^(LIBS\s*=.*)$", r"\1 -L%s/lib -lelpa" % elpa),
                ])

            elsi = get_software_root('ELSI')
            if elsi:
                if not os.path.isfile(os.path.join(elsi, 'lib', 'libelsi.%s' % get_shared_lib_ext())):
                    raise EasyBuildError("This easyblock requires ELSI shared libraries instead of static")

                regex_subs.extend([
                    (r"^(FPPFLAGS\s*:?=.*)$", r"\1 -DSIESTA__ELSI"),
                    (r"^(FPPFLAGS\s*:?=.*)$", r"\1 -I%s/include" % elsi),
                    (r"^(LIBS\s*=.*)$", r"\1 $(FFTW_LIBS) -L%s/lib -lelsi" % elsi),
                ])

            metis = get_software_root('METIS')
            if metis:
                regex_subs.extend([
                    (r"^(FPPFLAGS\s*:?=.*)$", r"\1 -DSIESTA__METIS"),
                    (r"^(LIBS\s*=.*)$", r"\1 -L%s/lib -lmetis" % metis),
                ])

        apply_regex_substitutions(arch_make, regex_subs)

        # individually apply substitutions that add lines
        for regex_nl in regex_newlines:
            apply_regex_substitutions(arch_make, [regex_nl])

        run_shell_cmd('make %s' % par)

        # Put binary in temporary install dir
        copy_file(os.path.join(obj_dir, 'siesta'), bindir)

        if self.cfg['with_utils']:
            # Make the utils
            change_dir(os.path.join(start_dir, 'Util'))

            if loose_ver >= LooseVersion('4'):
                # clean_all.sh might be missing executable bit...
                adjust_permissions('./clean_all.sh', stat.S_IXUSR, recursive=False, relative=True)
                run_shell_cmd('./clean_all.sh')

            if loose_ver >= LooseVersion('4.1'):
                regex_subs_TS = [
                    (r"^default:.*$", r""),
                    (r"^EXE\s*=.*$", r""),
                    (r"^(include\s*..ARCH_MAKE.*)$", r"EXE=tshs2tshs\ndefault: $(EXE)\n\1"),
                    (r"^(INCFLAGS.*)$", r"\1 -I%s" % obj_dir),
                ]

                makefile = os.path.join(start_dir, 'Util', 'TS', 'tshs2tshs', 'Makefile')
                apply_regex_substitutions(makefile, regex_subs_TS)

                if self.version != '4.1-MaX-1.0':
                    regex_subs_Gen_basis = [
                        (r"^(INCFLAGS.*)$", r"\1 -I%s" % obj_dir),
                    ]
                    makefile = os.path.join(start_dir, 'Util', 'Gen-basis', 'Makefile')
                    apply_regex_substitutions(makefile, regex_subs_Gen_basis)

            if loose_ver >= LooseVersion('4'):
                # SUFFIX rules in wrong place
                regex_subs_suffix = [
                    (r'^(\.SUFFIXES:.*)$', r''),
                    (r'^(include\s*\$\(ARCH_MAKE\).*)$', r'\1\n.SUFFIXES:\n.SUFFIXES: .c .f .F .o .a .f90 .F90'),
                ]
                makefile = os.path.join(start_dir, 'Util', 'Sockets', 'Makefile')
                apply_regex_substitutions(makefile, regex_subs_suffix)
                makefile = os.path.join(start_dir, 'Util', 'SiestaSubroutine', 'SimpleTest', 'Src', 'Makefile')
                apply_regex_substitutions(makefile, regex_subs_suffix)

            regex_subs_UtilLDFLAGS = [
                (r'(\$\(FC\)\s*-o\s)', r'$(FC) %s %s -o ' % (os.environ['FCFLAGS'], os.environ['LDFLAGS'])),
            ]
            makefile = os.path.join(start_dir, 'Util', 'Optimizer', 'Makefile')
            apply_regex_substitutions(makefile, regex_subs_UtilLDFLAGS)
            if loose_ver >= LooseVersion('4'):
                makefile = os.path.join(start_dir, 'Util', 'JobList', 'Src', 'Makefile')
                apply_regex_substitutions(makefile, regex_subs_UtilLDFLAGS)

            # remove clean at the end of default target
            # And yes, they are re-introducing this bug.
            is_ver40_to_401 = loose_ver >= LooseVersion('4.0') and loose_ver < LooseVersion('4.0.2')
            if (is_ver40_to_401 or loose_ver == LooseVersion('4.1.0.2.3')):
                makefile = os.path.join(start_dir, 'Util', 'SiestaSubroutine', 'SimpleTest', 'Src', 'Makefile')
                apply_regex_substitutions(makefile, [(r"simple_mpi_parallel clean", r"simple_mpi_parallel")])
                makefile = os.path.join(start_dir, 'Util', 'SiestaSubroutine', 'ProtoNEB', 'Src', 'Makefile')
                apply_regex_substitutions(makefile, [(r"protoNEB clean", r"protoNEB")])

            # build_all.sh might be missing executable bit...
            adjust_permissions('./build_all.sh', stat.S_IXUSR, recursive=False, relative=True)
            run_shell_cmd('./build_all.sh')

            # Now move all the built utils to the temp installdir
            expected_utils = [
                'CMLComp/ccViz',
                'Contrib/APostnikov/eig2bxsf', 'Contrib/APostnikov/fmpdos',
                'Contrib/APostnikov/md2axsf', 'Contrib/APostnikov/rho2xsf',
                'Contrib/APostnikov/vib2xsf', 'Contrib/APostnikov/xv2xsf',
                'COOP/fat', 'COOP/mprop',
                'Denchar/Src/denchar',
                'DensityMatrix/cdf2dm', 'DensityMatrix/dm2cdf',
                'Eig2DOS/Eig2DOS',
                'Gen-basis/gen-basis', 'Gen-basis/ioncat',
                'Gen-basis/ionplot.sh',
                'Grid/cdf2grid', 'Grid/cdf2xsf', 'Grid/cdf_laplacian',
                'Grid/g2c_ng', 'Grid/grid2cdf', 'Grid/grid2cube',
                'Grid/grid2val', 'Grid/grid_rotate',
                'Helpers/get_chem_labels',
                'HSX/hs2hsx', 'HSX/hsx2hs',
                'JobList/Src/countJobs', 'JobList/Src/getResults',
                'JobList/Src/horizontal', 'JobList/Src/runJobs',
                'Macroave/Src/macroave',
                'ON/lwf2cdf',
                'Optimizer/simplex', 'Optimizer/swarm',
                'pdosxml/pdosxml',
                'Projections/orbmol_proj',
                'SiestaSubroutine/FmixMD/Src/driver',
                'SiestaSubroutine/FmixMD/Src/para',
                'SiestaSubroutine/FmixMD/Src/simple',
                'STM/ol-stm/Src/stm', 'STM/simple-stm/plstm',
                'Vibra/Src/fcbuild', 'Vibra/Src/vibra',
                'WFS/readwf', 'WFS/readwfx', 'WFS/wfs2wfsx',
                'WFS/wfsnc2wfsx', 'WFS/wfsx2wfs',
            ]

            # skip broken utils in 4.1-MaX-1.0 release, hopefully will be fixed later
            if self.version != '4.1-MaX-1.0':
                expected_utils.extend([
                    'VCA/fractional', 'VCA/mixps',
                ])

            if loose_ver >= LooseVersion('3.2'):
                expected_utils.extend([
                    'Bands/eigfat2plot',
                ])

            if loose_ver >= LooseVersion('4.0'):
                if self.version != '4.1-MaX-1.0':
                    expected_utils.extend([
                        'SiestaSubroutine/ProtoNEB/Src/protoNEB',
                        'SiestaSubroutine/SimpleTest/Src/simple_pipes_parallel',
                        'SiestaSubroutine/SimpleTest/Src/simple_pipes_serial',
                        'SiestaSubroutine/SimpleTest/Src/simple_sockets_parallel',
                        'SiestaSubroutine/SimpleTest/Src/simple_sockets_serial',
                    ])
                expected_utils.extend([
                    'Sockets/f2fmaster', 'Sockets/f2fslave',
                ])
                if self.toolchain.options.get('usempi', None):
                    if self.version != '4.1-MaX-1.0':
                        expected_utils.extend([
                            'SiestaSubroutine/SimpleTest/Src/simple_mpi_parallel',
                            'SiestaSubroutine/SimpleTest/Src/simple_mpi_serial',
                        ])

            if loose_ver < LooseVersion('4.1'):
                expected_utils.append('WFS/info_wfsx')
                if loose_ver >= LooseVersion('4.0'):
                    expected_utils.extend([
                        'COOP/dm_creator',
                        'TBTrans_rep/tbtrans',
                    ])
                else:
                    expected_utils.extend([
                        'TBTrans/tbtrans',
                    ])

            if loose_ver < LooseVersion('4.0.2'):
                expected_utils.extend([
                    'Bands/new.gnubands',
                ])
            else:
                expected_utils.extend([
                    'Bands/gnubands',
                ])
                # Need to revisit this when 4.1 is officialy released.
                # This is based on b1-b3 releases
                if loose_ver < LooseVersion('4.1'):
                    expected_utils.extend([
                        'Contour/grid1d', 'Contour/grid2d',
                        'Optical/optical', 'Optical/optical_input',
                        'sies2arc/sies2arc',
                    ])

            if loose_ver >= LooseVersion('4.1'):
                expected_utils.extend([
                    'DensityMatrix/dmbs2dm', 'DensityMatrix/dmUnblock',
                    'Grimme/fdf2grimme',
                    'SpPivot/pvtsp',
                    'TS/TBtrans/tbtrans', 'TS/tselecs.sh',
                    'TS/ts2ts/ts2ts',
                ])
                if self.version != '4.1-MaX-1.0':
                    expected_utils.extend([
                        'TS/tshs2tshs/tshs2tshs',
                    ])

            for util in expected_utils:
                copy_file(os.path.join(start_dir, 'Util', util), bindir)

        if self.cfg['with_transiesta']:
            # Build transiesta
            change_dir(obj_dir)

            ts_clean_target = 'clean'
            if loose_ver >= LooseVersion('4.1.0.2.4'):
                ts_clean_target += '-transiesta'

            run_shell_cmd('make %s' % ts_clean_target)
            run_shell_cmd('make %s transiesta' % par)

            copy_file(os.path.join(obj_dir, 'transiesta'), bindir)

    def build_step(self):
        """No build step for Siesta."""
        pass

    def test_step(self):
        """Custom test step for Siesta."""
        change_dir(os.path.join(self.cfg['start_dir'], 'Obj', 'Tests'))
        super(EB_Siesta, self).test_step()

    def install_step(self):
        """Custom install procedure for Siesta: copy binaries."""
        bindir = os.path.join(self.installdir, 'bin')
        copy_dir(os.path.join(self.cfg['start_dir'], 'bin'), bindir)

    def sanity_check_step(self):
        """Custom sanity check for Siesta."""

        bins = ['bin/siesta']

        if self.cfg['with_transiesta']:
            bins.append('bin/transiesta')

        if self.cfg['with_utils']:
            bins.append('bin/denchar')

        custom_paths = {
            'files': bins,
            'dirs': [],
        }
        custom_commands = []
        if self.toolchain.options.get('usempi', None) and build_option('mpi_tests'):
            # make sure Siesta was indeed built with support for running in parallel
            # The "cd to builddir" is required to not contaminate the install dir with cruft from running siesta
            mpi_test_cmd = "cd %s && " % self.builddir
            mpi_test_cmd = mpi_test_cmd + "echo 'SystemName test' | mpirun -np 2 siesta 2>/dev/null | grep PARALLEL"
            custom_commands.append(mpi_test_cmd)

        super(EB_Siesta, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
