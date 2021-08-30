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
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import change_dir
from easybuild.tools.py2vs3 import string_type


class CMakePythonPackage(PythonPackage, CMakeMake):
    """Build a Python package and module with CMake.

    Some packages use cmake to first build and install C Python packages
    and then put the Python package in lib/pythonX.Y/site-packages.

    We install this in a seperate location and generate a module file
    which sets the PYTHONPATH.

    The steps of CMakePythonPackage are based on PythonPackage, except for
    the configure and build steps which use CMakeMake. The tests can be
    arbitrarily carried out with both. The installation is always done with
    CMake, but the option 'start_dir_python' allows to execute an extra install
    with PythonPackage.
    """
    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to Python packages thar are configured/built/installed via CMake"""
        extra_vars = PythonPackage.extra_options(extra_vars=extra_vars)
        extra_vars = CMakeMake.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'start_dir_python': [None, ('Path to Python package source code. It will be installed as a regular '
                                        'Python package after the installation process with make.'), CUSTOM],
            # redefine default options to be exclusive of PythonPackage
            'installopts': ['', 'Extra options for installation of Python package', CUSTOM],
            'runtest': [True, 'Test to run for the Python package.', CUSTOM],
            # add extra options as their counterparts for CMakeMake
            'installopts_make': ['', 'Extra options for installation with make', CUSTOM],
            'runtest_make': [None, ('Indicates if a test should be run after make; should specify argument '
                                    'after make (for e.g.,"test" for make test)'), CUSTOM],
        })
        # enable out-of-source build
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def configure_step(self, *args, **kwargs):
        """Add extra configuration using CMakeMake"""
        super(CMakePythonPackage, self).configure_step()

        return CMakeMake.configure_step(self, *args, **kwargs)

    def build_step(self, *args, **kwargs):
        """Build Python package with CMakeMake"""
        return CMakeMake.build_step(self, *args, **kwargs)

    def test_step(self):
        """Combined test with CMakeMake and PythonPackage tests"""
        runtest_python = self.cfg['runtest']

        # execute 'runtest_make' in test step of CMakeMake
        if self.cfg['runtest_make'] and isinstance(self.cfg['runtest_make'], string_type):
            self.cfg['runtest'] = self.cfg['runtest_make']
            CMakeMake.test_step(self)

        # execute 'runtest' in test step of PythonPackage
        self.cfg['runtest'] = runtest_python
        if self.cfg['runtest']:
            super(CMakePythonPackage, self).test_step()

    def install_step(self):
        """
        Always install with CMakeMake install step
        Python packages not part of CMakeMake installation can be installed separately with PythonPackage
        """
        # set installopts for installation with CMakeMake
        installopts_python = self.cfg['installopts']
        self.cfg['installopts'] = self.cfg['installopts_make']

        if self.cfg['start_dir_python'] is None:
            # single install with CMakeMake
            return CMakeMake.install_step(self)
        else:
            # install with CMakeMake plus PythonPackage
            CMakeMake.install_step(self)

            # update build environment with CMakeMake installation
            new_buildenv = [
                ('LD_LIBRARY_PATH', 'lib'),
                ('CPATH', 'include'),
            ]
            for (envar, envpath) in new_buildenv:
                oldvar = os.environ.get(envar, '')
                newvar = os.path.join(self.installdir, envpath)
                setvar(envar, os.pathsep.join([newvar, oldvar]))

            # set installopts for installation with PythonPackage
            self.cfg['installopts'] = installopts_python

            # move to Python package source directory
            if os.path.isabs(self.cfg['start_dir_python']):
                pysrc_dir = self.cfg['start_dir_python']
            else:
                pysrc_dir = os.path.join(self.builddir, 'easybuild_obj', self.cfg['start_dir_python'])

            change_dir(pysrc_dir)

            super(CMakePythonPackage, self).install_step()

    def post_install_step(self):
        """Reset working directory before post-installation commands"""
        change_dir(os.path.join(self.builddir, 'easybuild_obj'))
        super(CMakePythonPackage, self).post_install_step()
