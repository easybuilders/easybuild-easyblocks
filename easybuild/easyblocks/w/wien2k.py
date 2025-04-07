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
EasyBuild support for building and installing WIEN2k, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Michael Sluydts (Ghent University)

"""
import fileinput
import os
import re
import shutil
import sys
import tempfile
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, extract_file, mkdir, read_file
from easybuild.tools.filetools import remove_dir, write_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd


class EB_WIEN2k(EasyBlock):
    """Support for building/installing WIEN2k."""

    def __init__(self, *args, **kwargs):
        """Enable building in install dir."""
        super(EB_WIEN2k, self).__init__(*args, **kwargs)
        self.build_in_installdir = True

    @staticmethod
    def extra_options():
        testdata_urls = ["http://www.wien2k.at/reg_user/benchmark/test_case.tar.gz",
                         "http://www.wien2k.at/reg_user/benchmark/mpi-benchmark.tar.gz"]

        extra_vars = {
            'runtest': [True, "Run WIEN2k tests", CUSTOM],
            'testdata': [testdata_urls, "test data URL for WIEN2k benchmark test", CUSTOM],
            'wien_mpirun': [None, "MPI wrapper command to use", CUSTOM],
            'remote': [None, "Remote command to use (e.g. pbsssh, ...)", CUSTOM],
            'use_remote': [True, "Whether to remotely login to initiate the k-point parallellization calls", CUSTOM],
            'mpi_remote': [False, "Whether to initiate MPI calls locally or remotely", CUSTOM],
            'wien_granularity': [True, "Granularity for parallel execution (see manual)", CUSTOM],
            'taskset': [None, "Specifies an optional command for binding a process to a specific core", CUSTOM],
            'nmatmax': [19000, "Specifies the maximum matrix size", CUSTOM],
            'nume': [6000, "Specifies the number of states to output.", CUSTOM],
        }
        return EasyBlock.extra_options(extra_vars)

    def extract_step(self):
        """Unpack WIEN2k sources using gunzip and provided expand_lapw script."""
        super(EB_WIEN2k, self).extract_step()

        run_shell_cmd("gunzip *gz")

        cmd = "./expand_lapw"
        qa = [
            (r"continue \(y/n\)", 'y'),
        ]
        no_qa = [
            "tar -xf.*",
            ".*copied and linked.*",
        ]

        run_shell_cmd(cmd, qa_patterns=qa, qa_wait_patterns=no_qa)

    def configure_step(self):
        """Configure WIEN2k build by patching siteconfig_lapw script and running it."""

        self.cfgscript = "siteconfig_lapw"

        # patch config file first

        # toolchain-dependent values
        comp_answer = None
        if self.toolchain.comp_family() == toolchain.INTELCOMP:  # @UndefinedVariable
            if get_software_root('icc'):
                intelver = get_software_version('icc')
            elif get_software_root('intel-compilers'):
                intelver = get_software_version('intel-compilers')
            if LooseVersion(intelver) >= LooseVersion("2011"):
                if LooseVersion(self.version) < LooseVersion("17"):
                    comp_answer = 'I'  # Linux (Intel ifort 12.0 compiler + mkl )
                else:
                    comp_answer = 'LI'  # Linux (Intel ifort compiler (12.0 or later)+mkl+intelmpi))
            else:
                comp_answer = "K1"  # Linux (Intel ifort 11.1 compiler + mkl )
        elif self.toolchain.comp_family() == toolchain.GCC:  # @UndefinedVariable
            if LooseVersion(self.version) < LooseVersion("17"):
                comp_answer = 'V'  # Linux (gfortran compiler + gotolib)
            else:
                comp_answer = 'LG'  # Linux (gfortran compiler + OpenBlas)
        else:
            raise EasyBuildError("Failed to determine toolchain-dependent answers.")

        # libraries
        liblapack = os.getenv('LIBLAPACK_MT').replace('static', 'dynamic')
        libscalapack = os.getenv('LIBSCALAPACK_MT').replace('static', 'dynamic')
        rlibs = "%s %s" % (liblapack, self.toolchain.get_flag('openmp'))
        rplibs = [libscalapack, liblapack]
        fftwver = get_software_version('FFTW')
        if fftwver:
            suff = ''
            if LooseVersion(fftwver) >= LooseVersion("3"):
                suff = '3'
            rplibs.insert(0, "-lfftw%(suff)s_mpi -lfftw%(suff)s" % {'suff': suff})
        else:
            rplibs.append(os.getenv('LIBFFT'))

        rplibs = ' '.join(rplibs)

        vars = {
            'FC': '%s' % os.getenv('F90'),
            'FOPT': '%s' % os.getenv('FFLAGS'),
            'MPF': '%s' % os.getenv('MPIF90'),
            'FPOPT': '%s' % os.getenv('FFLAGS'),
            'CC': os.getenv('CC'),
            'LDFLAGS': '$(FOPT) %s ' % os.getenv('LDFLAGS'),
            'R_LIBS': rlibs,  # libraries for 'real' (not 'complex') binary
            'RP_LIBS': rplibs,  # libraries for 'real' parallel binary
            'MPIRUN': '',
        }

        for line in fileinput.input(self.cfgscript, inplace=1, backup='.orig'):
            # set config parameters
            for (key, val) in vars.items():
                regexp = re.compile('^([a-z0-9]+):%s:(.*)' % key)
                res = regexp.search(line)
                if res:
                    # we need to exclude the lines with 'current', otherwise we break the script
                    if not res.group(1) == "current":
                        if 'OPT' in key:
                            # append instead of replace
                            line = regexp.sub('\\1:%s:%s %s' % (key, res.group(2), val), line)
                        else:
                            line = regexp.sub('\\1:%s:%s' % (key, val), line)
            # avoid exit code > 0 at end of configuration
            line = re.sub(r'(\s+)exit 1', '\\1exit 0', line)
            sys.stdout.write(line)

        # set correct compilers
        env.setvar('bin', os.getcwd())

        dc = {
            'COMPILERC': os.getenv('CC'),
            'COMPILER': os.getenv('F90'),
            'COMPILERP': os.getenv('MPIF90'),
        }

        if LooseVersion(self.version) < LooseVersion("17"):
            for (key, val) in dc.items():
                write_file(key, val)
        else:
            dc['cc'] = dc.pop('COMPILERC')
            dc['fortran'] = dc.pop('COMPILER')
            dc['parallel'] = dc.pop('COMPILERP')
            write_file('WIEN2k_COMPILER', '\n'.join(['%s:%s' % (k, v) for k, v in dc.items()]))

        # configure with patched configure script
        self.log.debug('%s part I (configure)' % self.cfgscript)

        if LooseVersion(self.version) >= LooseVersion('21'):
            perlroot = get_software_root('Perl')
            if perlroot is None:
                raise EasyBuildError("Perl is a required dependency of WIEN2k as of version 21")
            self.perlbin = os.path.join(perlroot, 'bin', 'perl')
        else:
            self.perlbin = ''

        cmd = './%s' % self.cfgscript
        qa = [
            (r"Press RETURN to continue", ''),
            (r"Your compiler:", ''),
            (r"Hit Enter to continue", ''),
            (r"Remote shell \(default is ssh\) =", ''),
            (r"Remote copy \(default is scp\) =", ''),
            (r"and you need to know details about your installed  mpi ..\) \(y/n\)", 'y'),
            (r"Q to quit Selection:", 'Q'),
            (r"A Compile all programs \(suggested\) Q Quit Selection:", 'Q'),
            (r"Please enter the full path of the perl program: ", self.perlbin),
            (r"continue or stop \(c/s\)", 'c'),
            (r"\(like taskset -c\). Enter N / your_specific_command:", 'N'),
        ]
        if LooseVersion(self.version) >= LooseVersion("13"):
            fftw_root = get_software_root('FFTW')
            if fftw_root:
                fftw_maj = get_software_version('FFTW').split('.')[0]
                fftw_spec = 'FFTW%s' % fftw_maj
            else:
                raise EasyBuildError("Required FFTW dependency is missing")
            qa.extend([
                (r"\) Selection:", comp_answer),
                (r"Shared Memory Architecture\? \(y/N\):", 'N'),
                (r"Set MPI_REMOTE to  0 / 1:", '0'),
                (r"You need to KNOW details about your installed  MPI and FFTW \) \(y/n\)", 'y'),
                (r"Do you want to use FFTW \(recommended, but for sequential code not required\)\? \(Y,n\):", 'y'),
                (r"Please specify whether you want to use FFTW3 \(default\) or FFTW2  \(FFTW3 / FFTW2\):", fftw_spec),
                (r"Please specify the ROOT-path of your FFTW installation \(like /opt/fftw3\):", fftw_root),
                (r"is this correct\? enter Y \(default\) or n:", 'Y'),
            ])

            libxcroot = get_software_root('libxc')

            if LooseVersion(self.version) < LooseVersion("17"):
                libxcstr1 = ' before'
                libxcstr3 = ''
            elif LooseVersion(self.version) > LooseVersion("19"):
                libxcstr1 = ' - usually not needed'
                libxcstr3 = 'root-'
            else:
                libxcstr1 = ''
                libxcstr3 = ''

            libxc_q1 = r"LIBXC \(that you have installed%s\)\? \(y,N\):" % libxcstr1
            libxc_q2 = r"Do you want to automatically search for LIBXC installations\? \(Y,n\):"
            libxc_q3 = r"Please enter the %sdirectory of your LIBXC-installation\!:" % libxcstr3
            libxc_q4 = r"Please enter the lib-directory of your LIBXC-installation \(usually lib or lib64\)\!:"
            libxc_q5 = r"LIBXC \(usually not needed, ONLY for experts who want to play with different DFT options. "
            libxc_q5 += r"It must have been installed before\)\? \(y,N\):"
            libxc_q6 = r"Would you like to use LIBXC \(needed ONLY for self-consistent gKS mGGA calculations, "
            libxc_q6 += r"for the stress tensor and experts who want to play with different DFT options. "
            libxc_q6 += r"It must have been installed before\)\? \(y,N\):"

            if libxcroot:
                qa.extend([
                    (libxc_q1, 'y'),
                    (libxc_q2, 'n'),
                    (libxc_q3, libxcroot),
                    (libxc_q4, 'lib'),
                    (libxc_q5, 'y'),
                    (libxc_q6, 'y'),
                ])
            else:
                qa.extend([
                    (libxc_q1, 'N'),
                    (libxc_q5, 'N'),
                    (libxc_q6, 'N'),
                ])

            if LooseVersion(self.version) >= LooseVersion("17"):
                scalapack_libs = os.getenv('LIBSCALAPACK').split()
                scalapack = next((lib[2:] for lib in scalapack_libs if 'scalapack' in lib), 'scalapack')
                blacs = next((lib[2:] for lib in scalapack_libs if 'blacs' in lib), 'openblas')
                qa.extend([
                    (r"You need to KNOW details about your installed MPI, ELPA, and FFTW \) \(y/N\)", 'y'),
                    (r"Do you want to use a present ScaLAPACK installation\? \(Y,n\):", 'y'),
                    (r"Do you want to use the MKL version of ScaLAPACK\? \(Y,n\):", 'n'),  # we set it ourselves below
                    (r"Do you use Intel MPI\? \(Y,n\):", 'y'),
                    (r"Is this correct\? \(Y,n\):", 'y'),
                    (r"Please specify the target architecture of your ScaLAPACK libraries \(e.g. intel64\)\!:", ''),
                    (r"ScaLAPACK root:", os.getenv('MKLROOT') or os.getenv('EBROOTSCALAPACK')),
                    (r"ScaLAPACK library:", scalapack),
                    (r"BLACS root:", os.getenv('MKLROOT') or os.getenv('EBROOTOPENBLAS')),
                    (r"BLACS library:", blacs),
                    (r"Please enter your choice of additional libraries\!:", ''),
                    (r"Do you want to use a present FFTW installation\? \(Y,n\):", 'y'),
                    (r"Please specify the path of your FFTW installation \(like /opt/fftw3/\) "
                        r"or accept present choice \(enter\):", fftw_root),
                    (r"Please specify the target achitecture of your FFTW library \(e.g. lib64\) "
                        r"or accept present choice \(enter\):", ''),
                    (r"Do you want to automatically search for FFTW installations\? \(Y,n\):", 'n'),
                    (r"Please specify the ROOT-path of your FFTW installation \(like /opt/fftw3/\) "
                        r"or accept present choice \(enter\):", fftw_root),
                    (r"Is this correct\? enter Y \(default\) or n:", 'Y'),
                    (r"Please specify the name of your FFTW library or accept present choice \(enter\):", ''),
                    (r"or accept the recommendations \(Enter - default\)\!:", ''),
                    # the temporary directory is hardcoded into execution scripts and must exist at runtime
                    (r"Please enter the full path to your temporary directory:", '/tmp'),
                ])

                elparoot = get_software_root('ELPA')
                if elparoot:

                    apply_regex_substitutions(self.cfgscript, [(r"cat elpahelp2$", "cat -n elpahelp2")])

                    elpa_dict = {
                        'root': elparoot,
                        'version': get_software_version('ELPA'),
                        'variant': 'elpa_openmp' if self.toolchain.get_flag('openmp') else 'elpa',
                    }

                    elpa_dir = "%(root)s/include/%(variant)s-%(version)s" % elpa_dict

                    qa.extend([
                        (r"Do you want to use ELPA\? \(y,N\):", 'y'),
                        (r"Do you want to automatically search for ELPA installations\? \(Y,n\):", 'n'),
                        (r"Please specify the ROOT-path of your ELPA installation \(like /usr/local/elpa/\) "
                            r"or accept present path \(Enter\):", elparoot),
                        (r"Please specify the lib-directory of your ELPA installation \(e.g. lib or lib64\)\!:", 'lib'),
                        (r"Please specify the lib-directory of your ELPA installation \(e.g. lib or lib64\):", 'lib'),
                        (r"Please specify the name of your installed ELPA library \(e.g. elpa or elpa_openmp\)\!:",
                         elpa_dict['variant']),
                        (r"Please specify the name of your installed ELPA library \(e.g. elpa or elpa_openmp\):",
                         elpa_dict['variant']),
                        (r".*(?P<number>[0-9]+)\t%s\n(.*\n)*" % elpa_dir, '%(number)s'),
                    ])
                else:
                    qa.append((r"Do you want to use ELPA\? \(y,N\):", 'n'))
        else:
            qa.extend([
                (r"compiler\) Selection:", comp_answer),
                (r"Shared Memory Architecture\? \(y/n\):", 'n'),
                (r"If you are using mpi2 set MPI_REMOTE to 0  Set MPI_REMOTE to 0 / 1:", '0'),
                (r"Do you have MPI and Scalapack installed and intend to run "
                    r"finegrained parallel\? \(This is usefull only for BIG cases "
                    r"\(50 atoms and more / unit cell\) and you need to know details "
                    r"about your installed  mpi and fftw \) \(y/n\)", 'y'),
            ])

        no_qa = [
            'You have the following mkl libraries in %s :' % os.getenv('MKLROOT'),
            "%s( |\t)*.*" % os.getenv('MPIF90'),
            "%s( |\t)*.*" % os.getenv('F90'),
            "%s( |\t)*.*" % os.getenv('CC'),
            ".*SRC_.*",
        ]

        mpif90 = os.getenv('MPIF90')
        qa.extend([
            (r"S\s+Save and Quit[\s\n]+To change an item select option.[\s\n]+Selection:", 'S'),
            (r"Recommended setting for parallel f90 compiler: .* Current selection: Your compiler:", mpif90),
            (r"process or you can change single items in \"Compiling Options\".[\s\n]+Selection:", 'S'),
            (r"A\s+Compile all programs \(suggested\)[\s\n]+Q\s*Quit[\s\n]+Selection:", 'Q'),
        ])

        # don't check output too frequently for questions, or we'll provide incorrect answers...
        run_shell_cmd(cmd, qa_patterns=qa, qa_wait_patterns=no_qa)

        # post-configure patches
        parallel_options = {}
        parallel_options_fp = os.path.join(self.cfg['start_dir'], 'parallel_options')

        if self.cfg['wien_mpirun']:
            parallel_options.update({'WIEN_MPIRUN': self.cfg['wien_mpirun']})

        if self.cfg['taskset'] is None:
            self.cfg['taskset'] = 'no'
        parallel_options.update({'TASKSET': self.cfg['taskset']})

        for opt in ['use_remote', 'mpi_remote', 'wien_granularity']:
            parallel_options.update({opt.upper(): int(self.cfg[opt])})

        write_file(parallel_options_fp, '\n'.join(['setenv %s "%s"' % tup for tup in parallel_options.items()]))

        if self.cfg['remote']:
            if self.cfg['remote'] == 'pbsssh':
                extratxt = '\n'.join([
                    '',
                    "set remote = pbsssh",
                    "setenv PBSSSHENV 'LD_LIBRARY_PATH PATH'",
                    '',
                ])
                write_file(parallel_options_fp, extratxt, append=True)
            else:
                raise EasyBuildError("Don't know how to handle remote %s", self.cfg['remote'])

        self.log.debug("Patched file %s: %s", parallel_options_fp, read_file(parallel_options_fp))

        # Set configurable parameters for size of problems.
        param_subs = [
            (r'\s+PARAMETER\s+\(\s*NMATMAX\s*=\s*\d+\)', r'      PARAMETER (NMATMAX=%s)' % self.cfg['nmatmax']),
            (r'\s+PARAMETER\s+\(\s*NUME\s*=\s*\d+\)', r'      PARAMETER (NUME=%s)' % self.cfg['nume']),
        ]
        self.log.debug("param_subs = %s" % param_subs)
        apply_regex_substitutions('SRC_lapw1/param.inc', param_subs)
        self.log.debug("Patched file %s: %s", 'SRC_lapw1/param.inc', read_file('SRC_lapw1/param.inc'))

    def build_step(self):
        """Build WIEN2k by running siteconfig_lapw script again."""

        self.log.debug('%s part II (build_step)' % self.cfgscript)

        qa = [
            (r"Press RETURN to continue", '\nQ'),  # also answer on first qanda pattern with 'Q' to quit
            (r"Please enter the full path of the perl program: ", self.perlbin),
        ]

        if LooseVersion(self.version) < LooseVersion("17"):
            qa.extend([
                (r"L Perl path \(if not in /usr/bin/perl\) Q Quit Selection:", 'R'),
                (r"A Compile all programs S Select program Q Quit Selection:", 'A'),
            ])
        else:
            qa.extend([
                (r"program Q Quit Selection:", 'A'),
                (r"Path Q Quit Selection:", 'R'),
            ])

        no_qa = [
            r"%s( |\t)*.*" % os.getenv('MPIF90'),
            r"%s( |\t)*.*" % os.getenv('F90'),
            r"%s( |\t)*.*" % os.getenv('CC'),
            r"mv( |\t)*.*",
            r".*SRC_.*",
            r".*: warning .*",
            r".*Stop.",
            r"Compile time errors \(if any\) were:",
        ]

        cmd = "./%s" % self.cfgscript
        self.log.debug("no_qa for %s: %s", cmd, no_qa)
        run_shell_cmd(cmd, qa_patterns=qa, qa_wait_patterns=no_qa)

    def test_step(self):
        """Run WIEN2k test benchmarks. """

        def run_wien2k_test(cmd_arg):
            """Run a WPS command, and check for success."""

            cmd = "x_lapw lapw1 %s" % cmd_arg
            res = run_shell_cmd(cmd, fail_on_error=False)

            re_success = re.compile(r"LAPW1\s+END")
            if not re_success.search(res.output):
                raise EasyBuildError("Test '%s' in %s failed (pattern '%s' not found)?",
                                     cmd, os.getcwd(), re_success.pattern)
            else:
                self.log.info("Test '%s' seems to have run successfully: %s" % (cmd, res.output))

        if self.cfg['runtest']:
            if not self.cfg['testdata']:
                raise EasyBuildError("List of URLs for testdata not provided.")

            # prepend $PATH with install directory, define $SCRATCH which is used by the tests
            env.setvar('PATH', "%s:%s" % (self.installdir, os.environ['PATH']))
            try:
                cwd = os.getcwd()

                # create temporary directory
                tmpdir = tempfile.mkdtemp()
                os.chdir(tmpdir)
                self.log.info("Running tests in %s" % tmpdir)

                scratch = os.path.join(tmpdir, 'scratch')
                mkdir(scratch)
                env.setvar('SCRATCH', scratch)

                # download data
                testdata_paths = {}
                for testdata in self.cfg['testdata']:
                    td_path = self.obtain_file(testdata)
                    if not td_path:
                        raise EasyBuildError("Downloading file from %s failed?", testdata)
                    testdata_paths.update({os.path.basename(testdata): td_path})

                self.log.debug('testdata_paths: %s' % testdata_paths)

                # unpack serial benchmark
                serial_test_name = "test_case"
                srcdir = extract_file(testdata_paths['%s.tar.gz' % serial_test_name], tmpdir, change_into_dir=False)
                change_dir(srcdir)

                # run serial benchmark
                os.chdir(os.path.join(tmpdir, serial_test_name))
                run_wien2k_test("-c")

                # unpack parallel benchmark (in serial benchmark dir)
                parallel_test_name = "mpi-benchmark"
                srcdir = extract_file(testdata_paths['%s.tar.gz' % parallel_test_name], tmpdir, change_into_dir=False)
                change_dir(srcdir)

                # run parallel benchmark
                os.chdir(os.path.join(tmpdir, serial_test_name))
                run_wien2k_test("-p")

                os.chdir(cwd)
                remove_dir(tmpdir)

            except OSError as err:
                raise EasyBuildError("Failed to run WIEN2k benchmark tests: %s", err)

            self.log.debug("Current dir: %s" % os.getcwd())

    def test_cases_step(self):
        """Run test cases, if specified."""

        for test in self.cfg['tests']:

            # check expected format
            if not len(test) == 4:
                raise EasyBuildError("WIEN2k test case not specified in expected format: "
                                     "(testcase_name, init_lapw_args, run_lapw_args, [scf_regexp_pattern])")
            test_name = test[0]
            init_args = test[1]
            run_args = test[2]
            scf_regexp_patterns = test[3]

            try:
                cwd = os.getcwd()
                # WIEN2k enforces that working dir has same name as test case
                tmpdir = os.path.join(tempfile.mkdtemp(), test_name)

                scratch = os.path.join(tmpdir, 'scratch')
                mkdir(scratch, parents=True)
                env.setvar('SCRATCH', scratch)

                os.chdir(tmpdir)
                self.log.info("Running test case %s in %s" % (test_name, tmpdir))
            except OSError as err:
                raise EasyBuildError("Failed to create temporary directory for test %s: %s", test_name, err)

            # try and find struct file for test
            test_fp = self.obtain_file("%s.struct" % test_name)

            try:
                shutil.copy2(test_fp, tmpdir)
            except OSError as err:
                raise EasyBuildError("Failed to copy %s: %s", test_fp, err)

            # run test
            run_shell_cmd("init_lapw %s" % init_args)
            run_shell_cmd("run_lapw %s" % run_args)

            # check output
            scf_fn = "%s.scf" % test_name
            self.log.debug("Checking output of test %s in %s" % (str(test), scf_fn))
            scftxt = read_file(scf_fn)
            for regexp_pat in scf_regexp_patterns:
                regexp = re.compile(regexp_pat, re.M)
                if not regexp.search(scftxt):
                    raise EasyBuildError("Failed to find pattern %s in %s", regexp.pattern, scf_fn)
                else:
                    self.log.debug("Found pattern %s in %s" % (regexp.pattern, scf_fn))

            # cleanup
            try:
                os.chdir(cwd)
                remove_dir(tmpdir)
            except OSError as err:
                raise EasyBuildError("Failed to clean up temporary test dir: %s", err)

    def install_step(self):
        """Fix broken symlinks after build/installation."""
        # fix broken symlink
        os.remove(os.path.join(self.installdir, "SRC_w2web", "htdocs", "usersguide"))
        os.symlink(os.path.join(self.installdir, "SRC_usersguide_html"),
                   os.path.join(self.installdir, "SRC_w2web", "htdocs", "usersguide"))

    def sanity_check_step(self):
        """Custom sanity check for WIEN2k."""

        lapwfiles = []
        for suffix in ['0', '0_mpi', '1', '1_mpi', '1c', '1c_mpi', '2', '2_mpi', '2c', '2c_mpi',
                       '3', '3c', '5', '5c', '7', '7c', 'dm', 'dmc', 'so']:
            p = os.path.join(self.installdir, "lapw%s" % suffix)
            lapwfiles.append(p)

        custom_paths = {
            'files': lapwfiles,
            'dirs': [],
        }

        super(EB_WIEN2k, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Set WIENROOT environment variable, and correctly prepend PATH."""

        txt = super(EB_WIEN2k, self).make_module_extra()

        txt += self.module_generator.set_environment("WIENROOT", self.installdir)
        txt += self.module_generator.prepend_paths("PATH", [""])

        return txt
