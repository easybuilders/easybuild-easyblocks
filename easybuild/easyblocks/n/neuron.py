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
EasyBuild support for building and installing NEURON, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Maxime Boissonneault (Universite Laval, Compute Canada)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os
import re
import tempfile

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_NEURON(CMakeMake):
    """Support for building/installing NEURON."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for NEURON."""
        extra_vars = {
            'paranrn': [True, "Enable support for distributed simulations.", CUSTOM],
        }
        return CMakeMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for NEURON."""
        super(EB_NEURON, self).__init__(*args, **kwargs)

        self.python_root = None
        self.pylibdir = 'UNKNOWN'

    def prepare_step(self, *args, **kwargs):
        """Custom prepare step with python detection"""
        super(EB_NEURON, self).prepare_step(*args, **kwargs)

        self.python_root = get_software_root('Python')

    def configure_step(self):
        """Custom configuration procedure for NEURON."""
        # enable support for distributed simulations if desired
        if self.cfg['paranrn']:
            self.cfg.update('configopts', '-DNRN_ENABLE_MPI=ON')
        else:
            self.cfg.update('configopts', '-DNRN_ENABLE_MPI=OFF')

        # specify path to InterViews if it is available as a dependency
        interviews_root = get_software_root('InterViews')
        if interviews_root:
            self.cfg.update('configopts', f"-DIV_DIR={interviews_root} -DNRN_ENABLE_INTERVIEWS=ON")
        else:
            self.cfg.update('configopts', "-DNRN_ENABLE_INTERVIEWS=OFF")

        # optionally enable support for Python as alternative interpreter
        if self.python_root:
            python_cfgopts = " ".join([
                "-DNRN_ENABLE_PYTHON=ON",
                f"-DPYTHON_EXECUTABLE={self.python_root}/bin/python",
                "-DNRN_ENABLE_MODULE_INSTALL=ON",
                f"-DNRN_MODULE_INSTALL_OPTIONS='--prefix={self.installdir}'",
            ])
            self.cfg.update('configopts', python_cfgopts)
        else:
            self.cfg.update('configopts', "-DNRN_ENABLE_PYTHON=OFF")

        # determine Python lib dir
        self.pylibdir = det_pylibdir()

        # complete configuration with configure_method of parent
        CMakeMake.configure_step(self)

    def test_step(self):
        """Custom tests for NEURON."""
        if build_option('mpi_tests'):
            nproc = self.cfg.parallel
            try:
                hoc_file = os.path.join(self.cfg['start_dir'], 'src', 'parallel', 'test0.hoc')
                cmd = self.toolchain.mpi_cmd_for(f"bin/nrniv -mpi {hoc_file}", nproc)
                res = run_shell_cmd(cmd)
            except OSError as err:
                raise EasyBuildError("Failed to run parallel hello world: %s", err)

            valid = True
            for i in range(0, nproc):
                validate_regexp = re.compile(f"I am {i:d} of {nproc:d}")
                if not validate_regexp.search(res.output):
                    valid = False
                    break
            if res.exit_code or not valid:
                raise EasyBuildError("Validation of parallel hello world run failed.")
            self.log.info("Parallel hello world OK!")
        else:
            self.log.info("Skipping MPI testing of NEURON since MPI testing is disabled")

    def sanity_check_step(self):
        """Custom sanity check for NEURON."""
        shlib_ext = get_shared_lib_ext()

        binaries = ["mkthreadsafe", "modlunit", "neurondemo", "nocmodl", "nrngui", "nrniv", "nrnivmodl",
                    "nrnmech_makefile", "nrnpyenv.sh", "set_nrnpyenv.sh", "sortspike"]
        libs = ["nrniv", "rxdmath"]
        sanity_check_dirs = ['include', 'share/nrn']

        if self.python_root:
            sanity_check_dirs += [os.path.join("lib", "python")]
            if LooseVersion(self.version) < LooseVersion('8'):
                sanity_check_dirs += [os.path.join("lib", "python%(pyshortver)s", "site-packages")]

        # this is relevant for installations of Python packages for multiple Python versions (via multi_deps)
        # (we can not pass this via custom_paths, since then the %(pyshortver)s template value will not be resolved)
        # ensure that we only add to paths specified in the EasyConfig
        sanity_check_files = [os.path.join('bin', x) for x in binaries]
        sanity_check_files += [f'lib/lib{soname}.{shlib_ext}' for soname in libs]

        custom_paths = {
            'files': sanity_check_files,
            'dirs': sanity_check_dirs,
        }

        # run NEURON demo
        demo_dir = tempfile.mkdtemp()
        demo_inp_file = os.path.join(demo_dir, 'neurondemo.inp')
        demo_inp_cmds = '\n'.join([
            "demo(3) // load the pyramidal cell model.",
            "init()  // initialise the model",
            "t       // should be zero",
            "soma.v  // will print -65",
            "run()   // run the simulation",
            "t       // should be 5, indicating that 5ms were simulated",
            "soma.v  // will print a value other than -65, indicating that the simulation was executed",
            "quit()",
        ])
        write_file(demo_inp_file, demo_inp_cmds)

        demo_sanity_cmd = f"neurondemo < {demo_inp_file} 2>&1"
        demo_regexp_version = f'NEURON -- VERSION {self.version}'
        demo_regexp_soma = '68.134337'

        custom_commands = [
            f"{demo_sanity_cmd} | grep -c '{demo_regexp_version}'",
            f"{demo_sanity_cmd} | grep -c '{demo_regexp_soma}'",
        ]

        if self.python_root:
            custom_commands.append("python -s -c 'import neuron; neuron.test()'")

        super(EB_NEURON, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_step(self, *args, **kwargs):
        """
        Custom paths of NEURON module load environment
        """
        if self.python_root:
            # location of neuron Python package
            if LooseVersion(self.version) < LooseVersion('8'):
                self.module_load_environment.PYTHONPATH = [os.path.join("lib", "python*", "site-packages")]
            else:
                self.module_load_environment.PYTHONPATH = [os.path.join('lib', 'python')]

        return super(EB_NEURON, self).make_module_step(*args, **kwargs)

    def make_module_extra(self):
        """Define extra module entries required."""

        txt = super(EB_NEURON, self).make_module_extra()

        # we need to make sure the correct compiler is set in the environment,
        # since NEURON features compilation at runtime
        for var in ['CC', 'CXX', 'MPICC', 'MPICXX', 'MPICH_CC', 'MPICH_CXX']:
            val = os.getenv(var)
            if val:
                txt += self.module_generator.set_environment(var, val)
                self.log.debug(f"{var} set to {val}, adding it to module")
            else:
                self.log.debug(f"{var} not set: {os.environ.get(var, None)}")

        return txt
