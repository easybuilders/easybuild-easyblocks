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
EasyBuild support for pybind11, implemented as an easyblock

@author: Alexander Grund (TU Dresden)
"""
import os
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.easyblocks.generic.cmakepythonpackage import CMakePythonPackage
import easybuild.tools.environment as env
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.modules import get_software_root


class EB_pybind11(CMakePythonPackage):
    """Build PyBind11 for consumption with python packages and CMake

    PyBind11 can be consumed by CMake projects using `find_package` and by
    Python packages using `import pybind11`
    Hence we need to install PyBind11 twice: Once with CMake and once with pip
    """

    def configure_step(self):
        """Avoid that a system Python is picked up when a Python module is loaded"""

        # make sure right 'python' command is used for installing pybind11
        python_root = get_software_root('Python')
        python_exe_opt = '-DPYTHON_EXECUTABLE='
        if python_root and python_exe_opt not in self.cfg['configopts']:
            configopt = python_exe_opt + os.path.join(python_root, 'bin', 'python')
            self.log.info("Adding %s to configopts since it is not specified yet", configopt)
            self.cfg.update('configopts', configopt)

        super().configure_step()

    def test_step(self):
        """Run pybind11 tests"""
        # run tests unless explicitly disabled
        if self.cfg['runtest'] is not False:
            self.cfg['runtest'] = 'check'
        super().test_step()

    def install_step(self):
        """Install with cmake install and pip install"""
        build_dir = change_dir(self.cfg['start_dir'])
        PythonPackage.install_step(self)

        change_dir(build_dir)
        CMakeMake.install_step(self)

    def sanity_check_step(self):
        """
        Custom sanity check for Python packages
        """
        # don't add user site directory to sys.path (equivalent to python -s)
        env.setvar('PYTHONNOUSERSITE', '1', verbose=False)

        fake_mod_data = self.sanity_check_load_module(extension=self.is_extension)

        # Get python includes
        cmd = "%s -c 'import pybind11; print(pybind11.get_include())'" % self.python_cmd
        res = run_shell_cmd(cmd, fail_on_error=False)
        if res.exit_code:
            raise EasyBuildError("Failed to get pybind11 includes!")
        python_include = res.output.strip()

        # Check for CMake config and includes
        custom_paths = {
            'files': [os.path.join('share', 'cmake', 'pybind11', 'pybind11Config.cmake')],
            'dirs': [
                os.path.join('include', 'pybind11'),
                os.path.join(python_include, 'pybind11'),
            ],
        }

        res = PythonPackage.sanity_check_step(self, custom_paths=custom_paths)

        if fake_mod_data:
            self.clean_up_fake_module(fake_mod_data)

        return res
