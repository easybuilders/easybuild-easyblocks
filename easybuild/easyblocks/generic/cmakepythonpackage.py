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
EasyBuild support for Python packages that are configured with CMake, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.py2vs3 import string_type


class CMakePythonPackage(CMakeMake, PythonPackage):
    """Build a Python package and module with cmake.

    Some packages use cmake to first build and install C Python packages
    and then put the Python package in lib/pythonX.Y/site-packages.

    We install this in a seperate location and generate a module file
    which sets the PYTHONPATH.

    We use the default CMake implementation, and use make_module_extra from PythonPackage.
    """
    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to Python packages thar are configured/built/installed via CMake"""
        extra_vars = PythonPackage.extra_options(extra_vars=extra_vars)
        extra_vars = CMakeMake.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            # redefine 'runtest' as the default CMakeMake runtest
            'runtest': [None, ('Indicates if a test should be run after make; should specify argument '
                       'after make (for e.g.,"test" for make test)'), CUSTOM],
            # define 'runtest_python' as the runtest of PythonPackage
            'runtest_python': [True, 'Test to run for Python package.', CUSTOM]
        })
        # enable out-of-source build
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize with PythonPackage."""
        PythonPackage.__init__(self, *args, **kwargs)

    def configure_step(self, *args, **kwargs):
        """Main configuration using cmake"""

        PythonPackage.configure_step(self, *args, **kwargs)

        return CMakeMake.configure_step(self, *args, **kwargs)

    def build_step(self, *args, **kwargs):
        """Build Python package with cmake"""
        return CMakeMake.build_step(self, *args, **kwargs)

    def test_step(self):
        """Combined test with CMakeMake and PythonPackage tests"""

        # any test set in runtest is passed to CMakeMake
        if self.cfg['runtest'] and isinstance(self.cfg['runtest'], string_type):
            CMakeMake.test_step(self)

        # any test set in runtest_python is passed to PythonPackage
        if self.cfg['runtest_python']:
            self.cfg['runtest'] = self.cfg['runtest_python']
            return PythonPackage.test_step(self)

    def install_step(self):
        """Install with cmake install"""
        return CMakeMake.install_step(self)

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for Python packages"""
        return PythonPackage.sanity_check_step(self, *args, **kwargs)

    def make_module_extra(self):
        """Add extra Python package module parameters"""
        return PythonPackage.make_module_extra(self)
