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
EasyBuild support for building and installing SEPP, implemented as an easyblock
@author: Pavel Grochal (INUITS)
"""
import os

from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.filetools import apply_regex_substitutions, copy_dir, write_file
from easybuild.tools.run import run_cmd


class EB_SEPP(PythonPackage):
    """Support for installing the SEPP Python package as part of a Python installation."""

    def configure_step(self, *args, **kwargs):
        """Configure SEPP using setup.py."""
        super(EB_SEPP, self).configure_step(*args, **kwargs)

        # Configure sepp
        run_cmd("python setup.py config -c")

    def install_step(self, *args, **kwargs):
        """
        Create required SEPP files:
        home.path - file specifying path to SEPP config dir (.sepp)
        main.config - SEPP configuration file
        """
        super(EB_SEPP, self).install_step(*args, **kwargs)

        python_site_packages_dir = os.path.join(self.installdir, self.pylibdir)

        # original path to SEPP config
        sepp_orig_config_dir = os.path.join(self.builddir, self.name.lower() + "-" + self.version, '.sepp')

        # correct SEPP paths
        sepp_final_home_path_file = os.path.join(python_site_packages_dir, 'home.path')
        sepp_final_config_dir = os.path.join(python_site_packages_dir, '.sepp')
        sepp_final_config_file = os.path.join(sepp_final_config_dir, 'main.config')

        # create correct home.path file which contains location of .sepp config dir
        self.log.info("Creating home.path file for SEPP at %s", sepp_final_home_path_file)
        write_file(sepp_final_home_path_file, sepp_final_config_dir)

        # Copy .sepp folder with configurations and bundled stuff from builddir to installdir
        copy_dir(sepp_orig_config_dir, sepp_final_config_dir)

        # Replace wrong paths in SEPP configfile with correct ones
        regex_subs = [
            (r'%s' % sepp_orig_config_dir, '%s' % sepp_final_config_dir),
        ]
        apply_regex_substitutions(sepp_final_config_file, regex_subs)

    def sanity_check_step(self):
        """Custom sanity check for SEPP."""
        scripts = [
            'run_abundance.py', 'run_sepp.py', 'run_tipp.py',
            'run_tipp_tool.py', 'run_upp.py', 'split_sequences.py'
        ]
        custom_paths = {
            'files': [os.path.join('bin', s) for s in scripts],
            'dirs': [os.path.join(self.pylibdir, 'sepp')],
        }
        custom_commands = ["%s --help" % s for s in scripts]

        super(EB_SEPP, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
