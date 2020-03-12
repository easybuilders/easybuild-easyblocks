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
EasyBuild support for building and installing sepp, implemented as an easyblock
@author: Pavel Grochal (INUITS)
"""
import os
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.filetools import copy_dir, remove_dir, write_file
from easybuild.tools.modules import get_software_version
from easybuild.tools.run import run_cmd


class EB_SEPP(PythonPackage):
    """Support for installing the SEPP Python package as part of a Python installation."""

    def configure_step(self, *args, **kwargs):
        """Build sepp using setup.py."""
        super(EB_SEPP, self).configure_step(*args, **kwargs)

        # Configure sepp
        run_cmd("python setup.py config -c")

    def install_step(self, *args, **kwargs):
        super(EB_SEPP, self).install_step(*args, **kwargs)

        # Python version
        pyver = ".".join(get_software_version('Python').split(".")[:-1])
        python_site_packages_dir = os.path.join(self.installdir, "lib", "python%s" % pyver, "site-packages")

        # Old (wrong) SEPP paths
        sepp_wrong_config_dir = os.path.join(self.builddir, self.name.lower()+"-"+self.version, '.sepp')

        # New (correct) SEPP paths
        sepp_correct_home_path_file = os.path.join(python_site_packages_dir, "home.path")
        sepp_correct_config_dir = os.path.join(python_site_packages_dir, '.sepp')
        sepp_correct_config_file = os.path.join(sepp_correct_config_dir, 'main.config')

        # Create correct home.path file
        self.log.debug("Creating home.path file for SEPP at %s", sepp_correct_home_path_file)
        write_file(sepp_correct_home_path_file, sepp_correct_config_dir)

        # Copy .sepp folder with configurations and bundled stuff from builddir to installdir
        copy_dir(sepp_wrong_config_dir, sepp_correct_config_dir)

        # Replace wrong paths in SEPP configfile with correct ones
        run_cmd("sed -i 's#%s#%s#g' %s" % (sepp_wrong_config_dir, sepp_correct_config_dir, sepp_correct_config_file))
