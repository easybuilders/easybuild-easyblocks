##
# Copyright 2009-2020 Ghent University
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
"""
import fileinput
import glob
import os
import random
import re
import shutil
import sys
import tempfile
import fnmatch

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import change_dir, read_file, write_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.py2vs3 import ascii_letters
from easybuild.tools.run import run_cmd, run_cmd_qa
from easybuild.tools.systemtools import get_platform_name
from easybuild.tools import toolchain


class EB_GAMESS_minus_US(EasyBlock):
    """Support for building/installing GAMESS-US."""

    @staticmethod
    def extra_options():
        """Define custom easyconfig parameters for GAMESS-US."""
        extra_vars = {
            'ddi_comm': ['mpi', "DDI communication layer to use", CUSTOM],
            'maxcpus': [None, "Maximum number of cores per node", MANDATORY],
            'maxnodes': [None, "Maximum number of nodes", MANDATORY],
            'runtest': [True, "Run GAMESS-US tests", CUSTOM],
            'omp': [False, "Enabling OpenMP", CUSTOM],
            'scratch_dir': ['$TMPDIR', "Scratch dir to be used in rungms script", CUSTOM],
        }
        return EasyBlock.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Easyblock constructor, enable building in installation directory."""
        super(EB_GAMESS_minus_US, self).__init__(*args, **kwargs)
        self.build_in_installdir = True
        self.testdir = None
        if self.cfg['runtest']:
            self.testdir = tempfile.mkdtemp()
            # make sure test dir doesn't contain [ or ], rungms csh script doesn't handle that well ("set: No match")
            if re.search(r'[\[\]]', self.testdir):
                raise EasyBuildError("Temporary dir for tests '%s' will cause problems with rungms csh script",
                                     self.testdir)

        self.scratch_dir = self.cfg['scratch_dir']

    def extract_step(self):
        """Extract sources."""
        # strip off 'gamess' part to avoid having everything in a 'gamess' subdirectory
        self.cfg['unpack_options'] = "--strip-components=1"
        super(EB_GAMESS_minus_US, self).extract_step()

    def configure_step(self):
        """Configure GAMESS-US build via provided interactive 'config' script."""
        """Opening install.info file as append"""
        f = open(self.builddir + "/install.info", "a")
        f.writelines(["setenv GMS_PATH " + self.builddir + "\n"
            "setenv GMS_BUILD_DIR " + self.installdir + "\n"])
        # machine type
        platform_name = get_platform_name()
        x86_64_linux_re = re.compile('^x86_64-.*$')
        if x86_64_linux_re.match(platform_name):
            machinetype = "linux64"
            f.writelines(["setenv GMS_TARGET " + machinetype + "\n" +
                "setenv GMS_HPC_SYSTEM_TARGET generic" + "\n"])
        else:
            raise EasyBuildError("Build target %s currently unsupported", platform_name)

        # compiler config
        comp_fam = self.toolchain.comp_family()
        fortran_comp, fortran_ver = None, None
        if comp_fam == toolchain.INTELCOMP:
            fortran_comp = 'ifort'
            (out, _) = run_cmd("ifort -v", simple=False)
            res = re.search(r"^ifort version ([0-9]+)\.[0-9.]+$", out)
            if res:
                fortran_ver = res.group(1)
            else:
                raise EasyBuildError("Failed to determine ifort major version number")
        elif comp_fam == toolchain.GCC:
            fortran_comp = 'gfortran'
            fortran_ver = '.'.join(get_software_version('GCC').split('.')[:2])
        else:
            raise EasyBuildError("Compiler family '%s' currently unsupported.", comp_fam)

        f.writelines(["setenv GMS_FORTRAN " + fortran_comp + "\n" + 
            "setenv GMS_GFORTRAN_VERNO " + fortran_ver + "\n"])

        # math library config
        known_mathlibs = ['imkl', 'OpenBLAS', 'ATLAS', 'ACML']
        mathlib, mathlib_root = None, None
        for mathlib in known_mathlibs:
            mathlib_root = get_software_root(mathlib)
            if mathlib_root is not None:
                break
        if mathlib_root is None:
            raise EasyBuildError("None of the known math libraries (%s) available, giving up.", known_mathlibs)
        if mathlib == 'imkl':
            mathlib = 'mkl'
            mathlib_vers_res = '.'.join(get_software_version('imkl').split('.')[:1])
            if int(mathlib_vers_res) == 2020:
                mathlib_root = os.path.join(mathlib_root, 'mkl/lib/intel64')
            elif int(mathlib_vers_res) == 2021:
                mathlib_root = os.path.join(mathlib_root, 'mkl/latest/lib/intel64')

            if int(mathlib_vers_res) >= 2020:
                # For some GAMESS-US versions oneapi is not in lked, so we use 12-so instead
                if self.version == "20200630-R1" or self.version == "20200930-R2":
                    mathlib_vers = "12-so"
                elif self.version == "20210620-R1":
                    mathlib_vers = "12-so"
                else:
                    mathlib_vers = "oneapi-so"
            else:
                mathlib_vers = "12"

        else:
            mathlib = mathlib.lower()

        f.writelines(["setenv GMS_MATHLIB " + mathlib + "\n" +
            "setenv GMS_MATHLIB_PATH " + mathlib_root + "\n" +
            "setenv GMS_MKL_VERNO " + mathlib_vers + "\n" +
            "setenv GMS_LAPACK_LINK_LINE" + "" + "\n"])

        # verify selected DDI communication layer
        known_ddi_comms = ['mpi', 'mixed', 'shmem', 'sockets']
        if not self.cfg['ddi_comm'] in known_ddi_comms:
            raise EasyBuildError("Unsupported DDI communication layer specified (known: %s): %s",
                                 known_ddi_comms, self.cfg['ddi_comm'])
        
        f.writelines(["setenv GMS_DDI_COMM " + self.cfg['ddi_comm'] + "\n" ])

        # MPI library config
        mpilib, mpilib_root, mpilib_path = None, None, None
        if self.cfg['ddi_comm'] == 'mpi':

            known_mpilibs = ['impi', 'OpenMPI', 'MVAPICH2', 'MPICH2']
            for mpilib in known_mpilibs:
                mpilib_root = get_software_root(mpilib)
                if mpilib_root is not None:
                    break
            if mpilib_root is None:
                raise EasyBuildError("None of the known MPI libraries (%s) available, giving up.", known_mpilibs)
            mpilib_path = mpilib_root
            if mpilib == 'impi':
                mpilib_path = os.path.join(mpilib_root, 'intel64')
            else:
                mpilib = mpilib.lower()
        else:
            mpilib, mpilib_root = '', ''

        f.writelines(["setenv GMS_MPI_LIB " + mpilib + "\n" + 
            "setenv GMS_MPI_PATH " + mpilib_root + "\n"])

        # These are extra programs which for now we simply set all to FALSE
        f. writelines(["setenv GMS_MSUCC false " + "\n"])
        f. writelines(["setenv GMS_LIBCCHEM false" + "\n"])
        f. writelines(["setenv GMS_PHI none " + "\n"])
        f. writelines(["setenv GMS_SHMTYPE sysv " + "\n"])

        if self.cfg['omp'] == 'True':
            f. writelines(["setenv GMS_OPENMP true" + "\n"])
        else:
            f. writelines(["setenv GMS_OPENMP false" + "\n"])
        
        f. writelines(["setenv GMS_LIBXC false " + "\n"])
        f. writelines(["setenv GMS_MDI false " + "\n"])
        f. writelines(["setenv GMS_VM2 false " + "\n"])
        f. writelines(["setenv TINKER false " + "\n"])
        f. writelines(["setenv VB2000 false " + "\n"])
        f. writelines(["setenv XMVB false " + "\n"])
        f. writelines(["setenv NEO false " + "\n"])
        f. writelines(["setenv NBO false " + "\n"])
        f. writelines(["setenv GMS_FPE_FLAGS " + "\n"]) 
        #f. writelines(["setenv GMS_FPE_FLAGS '-ffpe-trap=invalid,zero,overflow' " + "\n"]) # This seems to be useful for debugging 

        f.close()

        self.log.debug("Contents of install.info:\n%s" % read_file(os.path.join(self.builddir, 'install.info')))

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
                if self.cfg['scratch_dir']:
                    line = re.sub(r"^(\s*set\s*SCR)=.*", r"\1=%s" % self.cfg['scratch_dir'], line)
                    line = re.sub(r"^(\s*set\s*USERSCR)=.*", r"\1=%s" % self.cfg['scratch_dir'], line)
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
                    line = re.sub("\*UNX", "    ", line)
                    sys.stdout.write(line)
            except IOError as err:
                raise EasyBuildError("Failed to patch actvte.code", actvte, err)
            # compiling
            run_cmd("mv %s/tools/actvte.code" % self.builddir + " %s/tools/actvte.f" % self.builddir)
            run_cmd("%s -o " % fortran_comp + " %s/tools/actvte.x" % self.builddir + " %s/tools/actvte.f" % self.builddir)

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

        # Done up to here
        quit()

        if self.scratch_dir:
            # FIXME: resolve environment variables used in scratch_dir values

            # use unique subdirectory in specified scratch dir;
            # we should use a shell command to create this directory,
            # since scratch_dir may include names of environment variables
            salt = ''.join(random.choice(ascii_letters) for i in range(10))
            self.scratch_dir = os.path.join(self.scratch_dir, self.name + '-' + salt)

            # make sure that specified directory is accessible via 'ssh', since rungms relies on that;
            # touch a file, and then use "ssh localhost ls" to see if it's accessible;
            # we must use shell commands for this, since scratch_dir may contain names of environment variables
            test_file = os.path.join(self.scratch_dir, 'test.txt')
            run_cmd("mkdir -p %s" % self.scratch_dir)
            run_cmd("touch %s" % test_file)
            test_cmd = 'ssh localhost "ls %s"' % test_file
            (out, ec) = run_cmd(test_cmd, simple=False, log_ok=False, log_all=False)
            if ec:
                error_msg = "Scratch directory %s is not accessible via 'ssh'!\n" % self.scratch_dir
                error_msg += "Specify a different path using the 'scratch_dir' easyconfig parameter.\n"
                error_msg += "Output of test command '%s': %s" % (test_cmd, out)
                raise EasyBuildError(error_msg)
            else:
                self.log.info("Using %s as scratch directory", self.scratch_dir)

        # patch hardcoded settings in rungms to use values specified in easyconfig file
        rungms = os.path.join(self.builddir, 'rungms')
        extra_gmspath_lines = "set ERICFMT=$GMSPATH/auxdata/ericfmt.dat\nset MCPPATH=$GMSPATH/auxdata/MCP\n"
        try:
            for line in fileinput.input(rungms, inplace=1, backup='.orig'):
                line = re.sub(r"^(\s*set\s*TARGET)=.*", r"\1=%s" % self.cfg['ddi_comm'], line)
                line = re.sub(r"^(\s*set\s*GMSPATH)=.*", r"\1=%s\n%s" % (self.installdir, extra_gmspath_lines), line)
                line = re.sub(r"^(\s*set\s*GMS_OPENMP)=.*", r"\1=%s" % "true", line) # changed in gamess-20190930-R2 for OpenBLAS support
                line = re.sub(r"(null\) set VERNO)=.*", r"\1=%s" % self.version, line)
                line = re.sub(r"^(\s*set DDI_MPI_CHOICE)=.*", r"\1=%s" % mpilib, line)
                line = re.sub(r"^(\s*set DDI_MPI_ROOT)=.*%s.*" % mpilib.lower(), r"\1=%s" % mpilib_path, line)
                line = re.sub(r"^(\s*set GA_MPI_ROOT)=.*%s.*" % mpilib.lower(), r"\1=%s" % mpilib_path, line)
                # comment out all adjustments to $LD_LIBRARY_PATH that involves hardcoded paths
                line = re.sub(r"^(\s*)(setenv\s*LD_LIBRARY_PATH\s*/.*)", r"\1#\2", line)
                if self.scratch_dir:
                    line = re.sub(r"^(\s*set\s*SCR)=.*", r"\1=%s" % self.scratch_dir, line)
                    line = re.sub(r"^(\s*set\s*USERSCR)=.*", r"\1=%s" % self.scratch_dir, line)
                sys.stdout.write(line)
        except IOError as err:
            raise EasyBuildError("Failed to patch %s: %s", rungms, err)

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
        # don't use provided 'runall' script for tests, since that only runs the tests single-core
        if self.cfg['runtest']:

            if not build_option('mpi_tests'):
                self.log.info("Skipping testing of GAMESS-US since MPI testing is disabled")
                return

            cwd = change_dir(self.testdir)

            # copy input files for exam<id> standard tests
            for test_input in glob.glob(os.path.join(self.installdir, 'tests', 'standard', 'exam*.inp')):
                try:
                    shutil.copy2(test_input, os.getcwd())
                except OSError as err:
                    raise EasyBuildError("Failed to copy %s to %s: %s", test_input, os.getcwd(), err)

            rungms = os.path.join(self.installdir, 'rungms')
            test_env_vars = ['export OMP_NUM_THREADS=1; TMPDIR=%s' % self.testdir]
            if self.toolchain.mpi_family() == toolchain.INTELMPI:
                test_env_vars.extend([
                    'I_MPI_FALLBACK=enable',  # enable fallback in case first fabric fails (see $I_MPI_FABRICS_LIST)
                    'I_MPI_HYDRA_BOOTSTRAP=fork',  # tests are only run locally (2 processes), so no SSH required
                ])

            # run all exam<id> tests, dump output to exam<id>.log
            # we let Python count the number of *.inp files as that changes
            tests_path = os.path.join(self.installdir, 'tests', 'standard')
            n_tests = len(fnmatch.filter(os.listdir(tests_path), '*.inp'))
            for i in range(1, n_tests+1):
                test_cmd = ' '.join(test_env_vars + [rungms, 'exam%02d' % i, self.version, '1', '2'])
                (out, _) = run_cmd(test_cmd, log_all=True, simple=False)
                write_file('exam%02d.log' % i, out)

            # verify output of tests
            check_cmd = os.path.join(self.installdir, 'tests', 'standard', 'checktst')
            (out, _) = run_cmd(check_cmd, log_all=True, simple=False)
            success_regex = re.compile("^All %d test results are correct" % n_tests, re.M)
            if success_regex.search(out):
                self.log.info("All tests ran successfully!")
            else:
                raise EasyBuildError("Not all tests ran successfully...")

            change_dir(cwd)

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

    def cleanup_step(self):
        """Cleanup set."""
        # remove dedicated scratch directory (if any);
        # we must use a shell command for this, since the path may contain environment variables
        super(EB_GAMESS_minus_US, self).cleanup_step()

        # FIXME
