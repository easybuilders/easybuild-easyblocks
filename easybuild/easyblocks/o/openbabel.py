##
# Copyright 2013 Ghent University
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
EasyBuild support for OpenBabel, implemented as an easyblock

@author: Ward Poelmans (Ghent University)
@author: Oliver Stueker (Compute Canada/ACENET)
"""
import os
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.systemtools import get_shared_lib_ext
from distutils.version import LooseVersion

class EB_OpenBabel(CMakeMake):
    """Support for installing the OpenBabel package."""

    @staticmethod
    def extra_options():
        extra_vars = {
            'with_python_bindings': [True, "Try to build Open Babel's Python bindings. (-DPYTHON_BINDINGS=ON)", CUSTOM],
        }
        return CMakeMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize OpenBabel-specific variables."""
        super(EB_OpenBabel, self).__init__(*args, **kwargs)
        self.with_python = False

    def configure_step(self):

        # Use separate build directory
        self.cfg['separate_build_dir'] = True

        self.cfg['configopts'] += "-DENABLE_TESTS=ON "
        # Needs wxWidgets
        self.cfg['configopts'] += "-DBUILD_GUI=OFF "

        root_python = get_software_root('Python')
        if root_python and self.cfg['with_python_bindings']:
            self.log.info("Enabling Python bindings")
            self.with_python = True
            shortpyver = '.'.join(get_software_version('Python').split('.')[:2])
            self.cfg['configopts'] += "-DPYTHON_BINDINGS=ON "
            shlib_ext = get_shared_lib_ext()
            self.cfg['configopts'] += "-DPYTHON_LIBRARY=%s/lib/libpython%s.%s " % (root_python, shortpyver, shlib_ext)
            self.cfg['configopts'] += "-DPYTHON_INCLUDE_DIR=%s/include/python%s " % (root_python, shortpyver)
        else:
            self.log.info("Not enabling Python bindings")

        root_eigen = get_software_root("Eigen")
        if root_eigen:
            self.log.info("Using Eigen")
            self.cfg['configopts'] += "-DEIGEN3_INCLUDE_DIR='%s/include' " % root_eigen
        else:
            self.log.info("Not using Eigen")

        super(EB_OpenBabel, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for OpenBabel."""
        custom_paths = {
            'files': ['bin/babel', 'lib/libopenbabel.%s' % get_shared_lib_ext()],
            'dirs': ['share/openbabel'],
        }
        super(EB_OpenBabel, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom variables for OpenBabel module."""
        txt = super(EB_OpenBabel, self).make_module_extra()
        if self.with_python:
            if LooseVersion(self.version) >= LooseVersion('2.4'):
                # since OpenBabel 2.4.0 the Python bindings under 
                # ${PREFIX}/lib/python2.7/site-packages  rather than ${PREFIX}/lib
                ob_pythonpath = det_pylibdir()
            else:
                ob_pythonpath = 'lib'
            txt += self.module_generator.prepend_paths('PYTHONPATH', [ob_pythonpath])
        babel_libdir = os.path.join(self.installdir, 'lib', 'openbabel', self.version)
        txt += self.module_generator.set_environment('BABEL_LIBDIR', babel_libdir)
        babel_datadir = os.path.join(self.installdir, 'share', 'openbabel', self.version)
        txt += self.module_generator.set_environment('BABEL_DATADIR', babel_datadir)
        return txt
