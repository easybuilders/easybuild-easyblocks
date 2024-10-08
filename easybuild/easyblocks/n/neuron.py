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
EasyBuild support for building and installing NEURON, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Maxime Boissonneault (Universite Laval, Compute Canada)
"""
import os
import re

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext

from easybuild.tools import LooseVersion


class EB_NEURON(CMakeMake):
    """Support for building/installing NEURON."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for NEURON."""
        super(EB_NEURON, self).__init__(*args, **kwargs)

        self.hostcpu = 'UNKNOWN'
        self.with_python = False
        self.pylibdir = 'UNKNOWN'

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for NEURON."""

        extra_vars = {
            'paranrn': [True, "Enable support for distributed simulations.", CUSTOM],
        }
        return CMakeMake.extra_options(extra_vars)

    def configure_step(self):
        """Custom configuration procedure for NEURON."""
        if LooseVersion(self.version) < LooseVersion('7.8.1'):

            # make sure we're using the correct configure command
            # (required because custom easyconfig parameters from CMakeMake are picked up)
            self.cfg['configure_cmd'] = "./configure"

            # enable support for distributed simulations if desired
            if self.cfg['paranrn']:
                self.cfg.update('configopts', '--with-paranrn')

            # specify path to InterViews if it is available as a dependency
            interviews_root = get_software_root('InterViews')
            if interviews_root:
                self.cfg.update('configopts', "--with-iv=%s" % interviews_root)
            else:
                self.cfg.update('configopts', "--without-iv")

            # optionally enable support for Python as alternative interpreter
            python_root = get_software_root('Python')
            if python_root:
                self.with_python = True
                self.cfg.update('configopts', "--with-nrnpython=%s/bin/python" % python_root)

            # determine host CPU type
            cmd = "./config.guess"
            (out, ec) = run_cmd(cmd, simple=False)

            self.hostcpu = out.split('\n')[0].split('-')[0]
            self.log.debug("Determined host CPU type as %s" % self.hostcpu)

            # determine Python lib dir
            self.pylibdir = det_pylibdir()

            # complete configuration with configure_method of parent
            ConfigureMake.configure_step(self)
        else:
            # enable support for distributed simulations if desired
            if self.cfg['paranrn']:
                self.cfg.update('configopts', '-DNRN_ENABLE_MPI=ON')
            else:
                self.cfg.update('configopts', '-DNRN_ENABLE_MPI=OFF')

            # specify path to InterViews if it is available as a dependency
            interviews_root = get_software_root('InterViews')
            if interviews_root:
                self.cfg.update('configopts', "-DIV_DIR=%s -DNRN_ENABLE_INTERVIEWS=ON" % interviews_root)
            else:
                self.cfg.update('configopts', "-DNRN_ENABLE_INTERVIEWS=OFF")

            # no longer used it seems
            self.hostcpu = ''

            # optionally enable support for Python as alternative interpreter
            python_root = get_software_root('Python')
            if python_root:
                self.with_python = True
                self.cfg.update('configopts', "-DNRN_ENABLE_PYTHON=ON -DPYTHON_EXECUTABLE=%s/bin/python" % python_root)
                self.cfg.update('configopts', "-DNRN_ENABLE_MODULE_INSTALL=ON "
                                "-DNRN_MODULE_INSTALL_OPTIONS='--prefix=%s'" % self.installdir)
            else:
                self.cfg.update('configopts', "-DNRN_ENABLE_PYTHON=OFF")

            # determine Python lib dir
            self.pylibdir = det_pylibdir()

            # complete configuration with configure_method of parent
            CMakeMake.configure_step(self)

    def install_step(self):
        """Custom install procedure for NEURON."""

        super(EB_NEURON, self).install_step()

        # with the CMakeMake, the python module is installed automatically
        if LooseVersion(self.version) < LooseVersion('7.8.1'):
            if self.with_python:
                pypath = os.path.join('src', 'nrnpython')
                try:
                    pwd = os.getcwd()
                    os.chdir(pypath)
                except OSError as err:
                    raise EasyBuildError("Failed to change to %s: %s", pypath, err)

                cmd = "python setup.py install --prefix=%s" % self.installdir
                run_cmd(cmd, simple=True, log_all=True, log_ok=True)

                try:
                    os.chdir(pwd)
                except OSError as err:
                    raise EasyBuildError("Failed to change back to %s: %s", pwd, err)

    def sanity_check_step(self):
        """Custom sanity check for NEURON."""
        shlib_ext = get_shared_lib_ext()
        binpath = os.path.join(self.hostcpu, 'bin')
        libpath = os.path.join(self.hostcpu, 'lib', 'lib%s.' + shlib_ext)
        # hoc_ed is not included in the sources of 7.4. However, it is included in the binary distribution.
        # Nevertheless, the binary has a date old enough (June 2014, instead of November 2015 like all the
        # others) to be considered a mistake in the distribution
        binaries = ["neurondemo", "nrngui", "nrniv", "nrnivmodl", "nocmodl", "modlunit", "nrnmech_makefile",
                    "mkthreadsafe"]
        libs = ["nrniv"]
        sanity_check_dirs = ['share/nrn']

        if LooseVersion(self.version) < LooseVersion('7.4'):
            binaries += ["hoc_ed"]

        if LooseVersion(self.version) < LooseVersion('7.8.1'):
            binaries += ["bbswork.sh", "hel2mos1.sh", "ivoc", "memacs", "mos2nrn", "mos2nrn2.sh", "oc"]
            binaries += ["nrn%s" % x for x in ["iv_makefile", "oc", "oc_makefile", "ocmodl"]]
            libs += ["ivoc", "ivos", "memacs", "meschach", "neuron_gnu", "nrnmpi", "nrnoc", "nrnpython",
                     "oc", "ocxt", "scopmath", "sparse13", "sundials"]
            sanity_check_dirs += ['include/nrn']
        # list of included binaries changed with cmake. See
        # https://github.com/neuronsimulator/nrn/issues/899
        else:
            binaries += ["nrnpyenv.sh", "set_nrnpyenv.sh", "sortspike"]
            libs += ["rxdmath"]
            sanity_check_dirs += ['include']
            if self.with_python:
                sanity_check_dirs += [os.path.join("lib", "python"),
                                      os.path.join("lib", "python%(pyshortver)s", "site-packages")]

        # this is relevant for installations of Python packages for multiple Python versions (via multi_deps)
        # (we can not pass this via custom_paths, since then the %(pyshortver)s template value will not be resolved)
        # ensure that we only add to paths specified in the EasyConfig
        sanity_check_files = [os.path.join(binpath, x) for x in binaries] + [libpath % x for x in libs]
        self.cfg['sanity_check_paths'] = {
                'files': sanity_check_files,
                'dirs': sanity_check_dirs,
        }

        super(EB_NEURON, self).sanity_check_step()

        try:
            fake_mod_data = self.load_fake_module()
        except EasyBuildError as err:
            self.log.debug("Loading fake module failed: %s" % err)

        # test NEURON demo
        inp = '\n'.join([
            "demo(3) // load the pyramidal cell model.",
            "init()  // initialise the model",
            "t       // should be zero",
            "soma.v  // will print -65",
            "run()   // run the simulation",
            "t       // should be 5, indicating that 5ms were simulated",
            "soma.v  // will print a value other than -65, indicating that the simulation was executed",
            "quit()",
        ])
        (out, ec) = run_cmd("neurondemo", simple=False, log_all=True, log_output=True, inp=inp)

        validate_regexp = re.compile(r"^\s+-65\s*\n\s+5\s*\n\s+-68.134337", re.M)
        if ec or not validate_regexp.search(out):
            raise EasyBuildError("Validation of NEURON demo run failed.")
        else:
            self.log.info("Validation of NEURON demo OK!")

        if build_option('mpi_tests'):
            nproc = self.cfg['parallel']
            try:
                cwd = os.getcwd()
                os.chdir(os.path.join(self.cfg['start_dir'], 'src', 'parallel'))

                cmd = self.toolchain.mpi_cmd_for("nrniv -mpi test0.hoc", nproc)
                (out, ec) = run_cmd(cmd, simple=False, log_all=True, log_output=True)

                os.chdir(cwd)
            except OSError as err:
                raise EasyBuildError("Failed to run parallel hello world: %s", err)

            valid = True
            for i in range(0, nproc):
                validate_regexp = re.compile("I am %d of %d" % (i, nproc))
                if not validate_regexp.search(out):
                    valid = False
                    break
            if ec or not valid:
                raise EasyBuildError("Validation of parallel hello world run failed.")
            else:
                self.log.info("Parallel hello world OK!")
        else:
            self.log.info("Skipping MPI testing of NEURON since MPI testing is disabled")

        if self.with_python:
            cmd = "python -s -c 'import neuron; neuron.test()'"
            (out, ec) = run_cmd(cmd, simple=False, log_all=True, log_output=True)

        # cleanup
        self.clean_up_fake_module(fake_mod_data)

    def make_module_req_guess(self):
        """Custom guesses for environment variables (PATH, ...) for NEURON."""

        guesses = super(EB_NEURON, self).make_module_req_guess()

        guesses.update({
            'PATH': [os.path.join(self.hostcpu, 'bin')],
        })

        return guesses

    def make_module_extra(self):
        """Define extra module entries required."""

        txt = super(EB_NEURON, self).make_module_extra()

        # we need to make sure the correct compiler is set in the environment,
        # since NEURON features compilation at runtime
        for var in ['CC', 'CXX', 'MPICC', 'MPICXX', 'MPICH_CC', 'MPICH_CXX']:
            val = os.getenv(var)
            if val:
                txt += self.module_generator.set_environment(var, val)
                self.log.debug("%s set to %s, adding it to module" % (var, val))
            else:
                self.log.debug("%s not set: %s" % (var, os.environ.get(var, None)))

        if self.with_python:
            if self.cfg['multi_deps'] and 'Python' in self.cfg['multi_deps']:
                txt += self.module_generator.prepend_paths('EBPYTHONPREFIXES', '')
            else:
                txt += self.module_generator.prepend_paths('PYTHONPATH', [self.pylibdir])
            # also adds lib/python to PYTHONPATH
            txt += self.module_generator.prepend_paths('PYTHONPATH', ['lib/python'])
        return txt
