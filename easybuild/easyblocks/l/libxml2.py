##
# Copyright 2009-2015 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for building and installing libxml2 with python bindings,
implemented as an easyblock.

@author: Jens Timmerman (Ghent University)
@author: Alan O'Cais (Juelich Supercomputing Centre)
"""
import os

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root


class EB_libxml2(ConfigureMake, PythonPackage):
    """Support for building and installing libxml2 with python bindings"""
    def __init__(self, *args, **kwargs):
        """
        Constructor
        init as a pythonpackage, since that is also an application
        """
        PythonPackage.__init__(self, *args, **kwargs)

    def configure_step(self):
        """
        Configure and 
        Test if python module is loaded
        """
        if not get_software_root('Python'):
            raise EasyBuildError("Python module not loaded")
        # We will do the python bindings ourselves so force them off
        self.cfg.update('configopts', '--without-python')
        ConfigureMake.configure_step(self)

    def build_step(self):
        """
        Make libxml2 first, then make python bindings
        """
        ConfigureMake.build_step(self)

    def install_step(self):
        """
        Install libxml2 and install python bindings
        """
        ConfigureMake.install_step(self)

        try:
            # We can only do the python bindings after the initial installation
            # since setup.py expects to find the include dir in the installation path
            # and that only exists after installation
            os.chdir('python')
            PythonPackage.configure_step(self)
            # set cflags to point to include folder for the compilation step to succeed
            env.setvar('CFLAGS', "-I../include")
            PythonPackage.build_step(self)
            PythonPackage.install_step(self)
            os.chdir('..')
        except OSError, err:
            raise EasyBuildError("Failed to install libxml2 Python bindings: %s", err)

    def make_module_extra(self):
        """
        Add python bindings to the pythonpath
        """
        return PythonPackage.make_module_extra(self)

    def sanity_check_step(self):
        """Custom sanity check for libxml2"""

        custom_paths = {
                        'files':["lib/libxml2.a", "lib/libxml2.so"] +
                                [os.path.join(self.pylibdir, x)
                                 for x in ['libxml2mod.so', 'libxml2.py', 'drv_libxml2.py']],
                        'dirs':["bin", self.pylibdir, "include/libxml2/libxml"],
                       }

        ConfigureMake.sanity_check_step(self, custom_paths=custom_paths)
