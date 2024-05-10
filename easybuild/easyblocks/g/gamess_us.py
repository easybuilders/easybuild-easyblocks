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
EasyBuild support for building and installing GAMESS-US, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Toon Willems (Ghent University)
@author: Pablo Escobar (sciCORE, SIB, University of Basel)
@author: Benjamin Roberts (The University of Auckland)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import fileinput
import glob
import os
import re
import sys
import tempfile

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import change_dir, copy_file, mkdir, read_file, write_file, remove_dir
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import POWER, X86_64
from easybuild.tools.systemtools import get_cpu_architecture
from easybuild.tools import LooseVersion, toolchain

GAMESS_INSTALL_INFO = 'install.info'
GAMESS_SERIAL_TESTS = [
    'exam05',  # only the gradients for CITYP=CIS run in parallel
    'exam32',  # only CCTYP=CCSD or CCTYP=CCSD(T) can run in parallel
    'exam42',  # ROHF'S CCTYP must be CCSD or CR-CCL, with serial execution
    'exam45',  # only CCTYP=CCSD or CCTYP=CCSD(T) can run in parallel
    'exam46',  # ROHF'S CCTYP must be CCSD or CR-CCL, with serial execution
    'exam47',  # ROHF'S CCTYP must be CCSD or CR-CCL, with serial execution
]


class EB_GAMESS_minus_US(EasyBlock):
    """Support for building/installing GAMESS-US."""

    @staticmethod
    def extra_options():
        """Define custom easyconfig parameters for GAMESS-US."""
        extra_vars = {
            'ddi_comm': ['mpi', "DDI communication layer to use", CUSTOM],
            'maxcpus': [None, "Maximum number of cores per node", MANDATORY],
            'maxnodes': [None, "Maximum number of nodes", MANDATORY],
            'hyperthreading': [True, "Enable support for hyperthreading (2 threads per core)", CUSTOM],
            'runtest': [True, "Run GAMESS-US tests", CUSTOM],
            'scratch_dir': ['$TMPDIR', "dir for temporary binary files", CUSTOM],
            'user_scratch_dir': ['$TMPDIR', "dir for supplementary output files", CUSTOM],
        }
        return EasyBlock.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Easyblock constructor, enable building in installation directory."""
        super(EB_GAMESS_minus_US, self).__init__(*args, **kwargs)
        self.build_in_installdir = True

        # resolve path to scratch dir and make it
        scratch_dir_resolved = os.path.expandvars(self.cfg['scratch_dir'])
        if "$" in scratch_dir_resolved:
            error_msg = "Provided scratch directory '%s' does not resolve into a path."
            raise EasyBuildError(error_msg, self.cfg['scratch_dir'])

        mkdir(scratch_dir_resolved, parents=True)

        self.testdir = None
        if self.cfg['runtest']:
            # run tests in scratch dir
            self.testdir = tempfile.mkdtemp(dir=scratch_dir_resolved)

            # make sure test dir doesn't contain [ or ], rungms csh script doesn't handle that well ("set: No match")
            if re.search(r'[\[\]]', self.testdir):
                error_msg = "Temporary dir for tests '%s' will cause problems with rungms csh script"
                raise EasyBuildError(error_msg, self.testdir)

        # OpenMP cannot be enabled across the board, activate it only through
        # GMS_OPENMP so that it gets enabled by the build where needed
        self.omp_enabled = False
        if self.toolchain.options.get('openmp', None):
            self.omp_enabled = True
            self.toolchain.options['openmp'] = False

    def extract_step(self):
        """Extract sources."""
        # strip off 'gamess' part to avoid having everything in a 'gamess' subdirectory
        self.cfg['unpack_options'] = "--strip-components=1"
        super(EB_GAMESS_minus_US, self).extract_step()

    def configure_step(self):
        """Configure GAMESS-US via install.info file"""
        installinfo_opts = {}

        # installation paths
        installinfo_opts["GMS_PATH"] = self.installdir
        installinfo_opts["GMS_BUILD_DIR"] = self.builddir

        # machine type
        cpu_arch = get_cpu_architecture()
        if cpu_arch == X86_64:
            machinetype = "linux64"
        elif cpu_arch == POWER:
            machinetype = "ibm64"
        else:
            raise EasyBuildError("Build target %s currently unsupported", cpu_arch)

        installinfo_opts["GMS_TARGET"] = machinetype
        installinfo_opts["GMS_HPC_SYSTEM_TARGET"] = "generic"

        # Compiler config
        comp_fam = self.toolchain.comp_family()
        fortran_comp, fortran_version = None, None
        if comp_fam == toolchain.INTELCOMP:
            fortran_comp = 'ifort'
            (out, _) = run_cmd("ifort -v", simple=False)
            res = re.search(r"^ifort version ([0-9]+)\.[0-9.]+$", out)
            try:
                version_num = res.group(1)
            except (AttributeError, IndexError):
                raise EasyBuildError("Failed to determine ifort major version number")
            fortran_version = {"GMS_IFORT_VERNO": version_num}
        elif comp_fam == toolchain.GCC:
            fortran_comp = 'gfortran'
            version_num = '.'.join(get_software_version('GCC').split('.')[:2])
            fortran_version = {"GMS_GFORTRAN_VERNO": version_num}
        else:
            raise EasyBuildError("Compiler family '%s' currently unsupported.", comp_fam)

        installinfo_opts["GMS_FORTRAN"] = fortran_comp
        installinfo_opts.update(fortran_version)

        # OpenMP config
        installinfo_opts["GMS_OPENMP"] = self.omp_enabled

        # Math library config
        known_mathlibs = ['imkl', 'OpenBLAS', 'ATLAS', 'ACML']
        loaded_mathlib = [mathlib for mathlib in known_mathlibs if get_software_root(mathlib)]

        # math library: default settings
        try:
            mathlib = loaded_mathlib[0].lower()
            mathlib_root = get_software_root(loaded_mathlib[0])
            mathlib_subfolder = ''
            mathlib_flags = ''
        except IndexError:
            raise EasyBuildError("None of the known math libraries (%s) available, giving up.", known_mathlibs)

        # math library: special cases
        if mathlib == 'imkl':
            mathlib = 'mkl'
            mathlib_subfolder = 'mkl/lib/intel64'
            mkl_version = '12'
            imkl_ver = get_software_version('imkl')
            if LooseVersion(imkl_ver) >= LooseVersion("2021"):
                # OneAPI version
                mathlib_subfolder = 'mkl/latest/lib/intel64'
                mkl_version = 'oneapi'
            installinfo_opts["GMS_MKL_VERNO"] = mkl_version

            if LooseVersion(self.version) >= LooseVersion('20230601'):
                installinfo_opts["GMS_THREADED_BLAS"] = self.omp_enabled

        elif mathlib == 'openblas':
            mathlib_flags = "-lopenblas -lgfortran"
            if LooseVersion(self.version) >= LooseVersion('20210101'):
                mathlib_subfolder = 'lib'

        if mathlib_root is not None:
            mathlib_path = os.path.join(mathlib_root, mathlib_subfolder)
            self.log.debug("Software root of math libraries set to: %s", mathlib_path)
        else:
            raise EasyBuildError("Software root of math libraries (%s) not found", mathlib)

        installinfo_opts["GMS_MATHLIB"] = mathlib
        installinfo_opts["GMS_MATHLIB_PATH"] = mathlib_path
        installinfo_opts["GMS_LAPACK_LINK_LINE"] = '"%s"' % mathlib_flags

        # verify selected DDI communication layer
        known_ddi_comms = ['mpi', 'mixed', 'shmem', 'sockets']
        if not self.cfg['ddi_comm'] in known_ddi_comms:
            raise EasyBuildError(
                "Unsupported DDI communication layer specified (known: %s): %s", known_ddi_comms, self.cfg['ddi_comm']
            )

        installinfo_opts["GMS_DDI_COMM"] = self.cfg['ddi_comm']

        # MPI library config
        mpilib, mpilib_path = '', ''
        if self.cfg['ddi_comm'] == 'mpi':
            known_mpilibs = ['impi', 'OpenMPI', 'MVAPICH2', 'MPICH2']
            loaded_mpilib = [mpilib for mpilib in known_mpilibs if get_software_root(mpilib)]

            # mpi library: default settings
            try:
                mpilib = loaded_mpilib[0].lower()
                mpilib_root = get_software_root(loaded_mpilib[0])
                mpilib_subfolder = ''
            except IndexError:
                raise EasyBuildError("None of the known MPI libraries (%s) available, giving up.", known_mpilibs)

            if mpilib == 'impi':
                impi_ver = get_software_version('impi')
                if LooseVersion(impi_ver) >= LooseVersion("2021"):
                    mpilib_subfolder = "mpi/latest"
                else:
                    mpilib_subfolder = "intel64"

                if LooseVersion(impi_ver) >= LooseVersion("2019"):
                    # fix rungms settings for newer versions of Intel MPI
                    print("PATCH IMPI")
                    rungms = os.path.join(self.builddir, 'rungms')
                    try:
                        for line in fileinput.input(rungms, inplace=1, backup='.orig'):
                            line = re.sub(r"^(\s*setenv\s*I_MPI_STATS).*", r"# \1", line)
                            line = re.sub(r"^(\s*setenv\s*I_MPI_WAIT_MODE)\s*enable.*", r"\1 1", line)
                            sys.stdout.write(line)
                    except IOError as err:
                        raise EasyBuildError("Failed to patch Intel MPI settings in %s: %s", rungms, err)

            if mpilib_root is not None:
                mpilib_path = os.path.join(mpilib_root, mpilib_subfolder)
                self.log.debug("Software root of MPI libraries set to: %s", mpilib_path)
            else:
                raise EasyBuildError("Software root of MPI libraries (%s) not found", mpilib)

        installinfo_opts["GMS_MPI_LIB"] = mpilib
        installinfo_opts["GMS_MPI_PATH"] = mpilib_path

        # Accelerators (disabled)
        # TODO: add support for GPUs
        if LooseVersion(self.version) >= LooseVersion('20230601'):
            # offloading onto Intel GPUs
            installinfo_opts["GMS_OPENMP_OFFLOAD"] = False

        # These are extra programs which for now we simply set all to FALSE
        installinfo_opts["GMS_MSUCC"] = False
        installinfo_opts["GMS_PHI"] = "none"
        installinfo_opts["GMS_SHMTYPE"] = "sysv"
        installinfo_opts["GMS_LIBCCHEM"] = False  # libcchem
        if LooseVersion(self.version) >= LooseVersion('20230601'):
            # install options for libcchem2
            installinfo_opts["GMS_HPCCHEM"] = False
            installinfo_opts["GMS_HPCCHEM_USE_DATA_SERVERS"] = False
            # build Michigan State University code
            installinfo_opts["GMS_MSUAUTO"] = False

        # Optional plug-ins and interfaces
        # libXC
        if LooseVersion(self.version) >= LooseVersion('20200101'):
            installinfo_opts['GMS_LIBXC'] = False
            if get_software_root('libxc'):
                installinfo_opts['GMS_LIBXC'] = True
                # the linker needs to be patched to use external libXC
                lixc_libs = [os.path.join(os.environ['EBROOTLIBXC'], 'lib', lib) for lib in ['libxcf03.a', 'libxc.a']]
                libxc_linker_flags = ' '.join(lixc_libs)
                try:
                    lked = os.path.join(self.builddir, 'lked')
                    for line in fileinput.input(lked, inplace=1, backup='.orig'):
                        line = re.sub(r"^(\s*set\sLIBXC_FLAGS)=.*GMS_PATH.*", r'\1="%s"' % libxc_linker_flags, line)
                        sys.stdout.write(line)
                except IOError as err:
                    raise EasyBuildError("Failed to patch %s: %s", lked, err)
        # MDI
        # needs https://github.com/MolSSI-MDI/MDI_Library
        installinfo_opts['GMS_MDI'] = False
        # NBO
        installinfo_opts['NBO'] = False
        if get_software_root('NBO'):
            installinfo_opts['NBO'] = True
        # NEO
        installinfo_opts['NEO'] = False
        # RISM
        if LooseVersion(self.version) >= LooseVersion('20230601'):
            installinfo_opts['RISM'] = False
        # TINKER
        installinfo_opts['TINKER'] = False
        if get_software_root('TINKER'):
            installinfo_opts['TINKER'] = True
        # VB2000
        installinfo_opts['VB2000'] = False
        # VM2
        installinfo_opts['GMS_VM2'] = False
        # XMVB
        installinfo_opts['XMVB'] = False

        # add include paths from dependencies
        installinfo_opts["GMS_FPE_FLAGS"] = '"%s"' % os.environ['CPPFLAGS']
        # might be useful for debugging
        # installinfo_opts["GMS_FPE_FLAGS"] = '"%s"' % os.environ['CPPFLAGS'] + "-ffpe-trap=invalid,zero,overflow"

        # write install.info file with configuration settings
        installinfo_file = os.path.join(self.builddir, GAMESS_INSTALL_INFO)
        # replace boolean options with their string representation
        boolean_opts = {opt: str(val).lower() for opt, val in installinfo_opts.items() if val in [True, False]}
        installinfo_opts.update(boolean_opts)
        # format: setenv KEY VALUE
        installinfo_txt = '\n'.join(["setenv %s %s" % (k, installinfo_opts[k]) for k in installinfo_opts])
        write_file(installinfo_file, installinfo_txt)
        self.log.debug("Contents of %s:\n%s" % (installinfo_file, read_file(installinfo_file)))

        # patch hardcoded settings in rungms to use values specified in easyconfig file
        rungms = os.path.join(self.builddir, 'rungms')
        extra_gmspath_lines = "set ERICFMT=$GMSPATH/auxdata/ericfmt.dat\nset MCPPATH=$GMSPATH/auxdata/MCP\n"
        try:
            for line in fileinput.input(rungms, inplace=1, backup='.orig'):
                line = re.sub(r"^(\s*set\s*TARGET)=.*", r"\1=%s" % self.cfg['ddi_comm'], line)
                line = re.sub(r"^(\s*set\s*GMSPATH)=.*", r"\1=%s\n%s" % (self.installdir, extra_gmspath_lines), line)
                line = re.sub(r"(null\) set VERNO)=.*", r"\1=%s" % self.version, line)
                line = re.sub(r"^(\s*set DDI_MPI_CHOICE)=.*", r"\1=%s" % mpilib, line)
                line = re.sub(r"^(\s*set DDI_MPI_ROOT)=.*%s.*" % mpilib.lower(), r"\1=%s" % mpilib_path, line)
                line = re.sub(r"^(\s*set GA_MPI_ROOT)=.*%s.*" % mpilib.lower(), r"\1=%s" % mpilib_path, line)
                # comment out all adjustments to $LD_LIBRARY_PATH that involves hardcoded paths
                line = re.sub(r"^(\s*)(setenv\s*LD_LIBRARY_PATH\s*/.*)", r"\1#\2", line)
                # scratch directory paths
                line = re.sub(r"^(\s*set\s*SCR)=.*", r"if ( ! $?SCR ) \1=%s" % self.cfg['scratch_dir'], line)
                line = re.sub(
                    r"^(\s*set\s*USERSCR)=.*", r"if ( ! $?USERSCR ) \1=%s" % self.cfg['user_scratch_dir'], line
                )
                line = re.sub(r"^(df -k \$SCR)$", r"mkdir -p $SCR && mkdir -p $USERSCR && \1", line)
                if self.cfg['hyperthreading'] is False:
                    # disable hyperthreading (1 thread per core)
                    line = re.sub(r"\$PPN \+ \$PPN", r"$PPN", line)
                    line = re.sub(r"\$NCPUS \+ \$NCPUS", r"$NCPUS", line)
                sys.stdout.write(line)
        except IOError as err:
            raise EasyBuildError("Failed to patch %s: %s", rungms, err)

        # Replacing the MAXCPUS and MAXNODES in compddi to a value from the EasyConfig file
        compddi = os.path.join(self.builddir, 'ddi/compddi')
        try:
            for line in fileinput.input(compddi, inplace=1, backup='.orig'):
                line = re.sub(r"^(\s*set MAXCPUS)=.*", r"\1=%s" % self.cfg['maxcpus'], line, 1)
                line = re.sub(r"^(\s*set MAXNODES)=.*", r"\1=%s" % self.cfg['maxnodes'], line, 1)
                sys.stdout.write(line)
        except IOError as err:
            raise EasyBuildError("Failed to patch compddi", compddi, err)

        # for GAMESS-US 20200630-R1 we need to build the actvte.x program
        if self.version == "20200630-R1":
            actvte = os.path.join(self.builddir, 'tools/actvte.code')
            try:
                for line in fileinput.input(actvte, inplace=1, backup='.orig'):
                    line = re.sub("[*]UNX", "    ", line)
                    sys.stdout.write(line)
            except IOError as err:
                raise EasyBuildError("Failed to patch actvte.code", actvte, err)
            # compiling
            run_cmd("mv %s/tools/actvte.code" % self.builddir + " %s/tools/actvte.f" % self.builddir)
            run_cmd(
                "%s -o " % fortran_comp + " %s/tools/actvte.x" % self.builddir + " %s/tools/actvte.f" % self.builddir
            )

    def build_step(self):
        """Custom build procedure for GAMESS-US: using compddi, compall and lked scripts."""
        compddi = os.path.join(self.cfg['start_dir'], 'ddi', 'compddi')
        run_cmd(compddi, log_all=True, simple=True)

        # make sure the libddi.a library is present
        libddi = os.path.join(self.cfg['start_dir'], 'ddi', 'libddi.a')
        if not os.path.isfile(libddi):
            raise EasyBuildError("The libddi.a library (%s) was never built", libddi)
        else:
            self.log.info("The libddi.a library (%s) was successfully built." % libddi)

        ddikick = os.path.join(self.cfg['start_dir'], 'ddi', 'ddikick.x')
        if os.path.isfile(ddikick):
            self.log.info("The ddikick.x executable (%s) was successfully built." % ddikick)

            if self.cfg['ddi_comm'] == 'sockets':
                src = ddikick
                dst = os.path.join(self.cfg['start_dir'], 'ddikick.x')
                self.log.info("Moving ddikick.x executable from %s to %s." % (src, dst))
                os.rename(src, dst)

        compall_cmd = os.path.join(self.cfg['start_dir'], 'compall')
        compall = "%s %s %s" % (self.cfg['prebuildopts'], compall_cmd, self.cfg['buildopts'])
        run_cmd(compall, log_all=True, simple=True)

        cmd = "%s gamess %s" % (os.path.join(self.cfg['start_dir'], 'lked'), self.version)
        run_cmd(cmd, log_all=True, simple=True)

    def test_step(self):
        """Run GAMESS-US tests (if 'runtest' easyconfig parameter is set to True)."""
        if self.cfg['runtest']:
            # Avoid provided 'runall' script for tests, since that only runs the tests in serial
            # Tests must be run in parallel for MPI builds and can be run serial for other build types

            target_tests = [
                # (test name, path to test input)
                (os.path.splitext(os.path.basename(exam_file))[0], exam_file)
                for exam_file in glob.glob(os.path.join(self.installdir, 'tests', 'standard', 'exam*.inp'))
            ]
            test_procs = "1"
            test_env_vars = ['export OMP_NUM_THREADS=1']

            if self.cfg['ddi_comm'] == 'mpi':
                if not build_option('mpi_tests'):
                    self.log.info("Skipping tests of MPI build of GAMESS-US by user request ('mpi_tests' is disabled)")
                    return

                # MPI builds can only run tests that support parallel execution
                if int(self.cfg['parallel']) < 2:
                    self.log.info("Skipping testing of GAMESS-US as MPI tests need at least 2 CPU cores to run")
                    return

                test_procs = str(self.cfg['parallel'])
                target_tests = [exam for exam in target_tests if exam[0] not in GAMESS_SERIAL_TESTS]

                if self.toolchain.mpi_family() == toolchain.INTELMPI:
                    test_env_vars.extend([
                        # enable fallback in case first fabric fails (see $I_MPI_FABRICS_LIST)
                        'export I_MPI_FALLBACK=enable',
                        # tests are only run locally (single node), so no SSH required
                        'export I_MPI_HYDRA_BOOTSTRAP=fork',
                    ])

            # Prepare test directory to run tests
            try:
                cwd = os.getcwd()
                change_dir(self.testdir)
            except OSError as err:
                raise EasyBuildError("Failed to move to temporary directory for running tests: %s", err)

            for exam, exam_file in target_tests:
                try:
                    copy_file(exam_file, self.testdir)
                except OSError as err:
                    raise EasyBuildError("Failed to copy test '%s' to %s: %s", exam, self.testdir, err)

            test_env_vars.append('SCR=%s' % self.testdir)

            # run target exam<id> tests, dump output to exam<id>.log
            rungms = os.path.join(self.installdir, 'rungms')
            for exam, exam_file in target_tests:
                rungms_prefix = ' && '.join(test_env_vars)
                test_cmd = [rungms_prefix, rungms, exam_file, self.version, test_procs, test_procs]
                (out, _) = run_cmd(' '.join(test_cmd), log_all=True, simple=False)
                write_file('%s.log' % exam, out)

            check_cmd = os.path.join(self.installdir, 'tests', 'standard', 'checktst')
            (out, _) = run_cmd(check_cmd, log_all=True, simple=False)

            # verify output of tests
            failed_regex = re.compile(r"^.*!!FAILED\.$", re.M)
            failed_tests = set([exam[0:6] for exam in failed_regex.findall(out)])
            done_tests = set([exam[0] for exam in target_tests])
            if done_tests - failed_tests == done_tests:
                info_msg = "All target tests ran successfully!"
                if self.cfg['ddi_comm'] == 'mpi':
                    info_msg += " (serial tests ignored: %s)" % ", ".join(GAMESS_SERIAL_TESTS)
                self.log.info(info_msg)
            else:
                raise EasyBuildError("ERROR: Not all target tests ran successfully")

            # cleanup
            change_dir(cwd)
            try:
                remove_dir(self.testdir)
            except OSError as err:
                raise EasyBuildError("Failed to remove test directory %s: %s", self.testdir, err)

    def install_step(self):
        """Skip install step, since we're building in the install directory."""
        pass

    def sanity_check_step(self):
        """Custom sanity check for GAMESS-US."""
        custom_paths = {
            'files': ['gamess.%s.x' % self.version, 'rungms'],
            'dirs': [],
        }
        super(EB_GAMESS_minus_US, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Define GAMESS-US specific variables in generated module file, i.e. $GAMESSUSROOT."""
        txt = super(EB_GAMESS_minus_US, self).make_module_extra()
        txt += self.module_generator.set_environment('GAMESSUSROOT', self.installdir)
        txt += self.module_generator.prepend_paths("PATH", [''])
        return txt
