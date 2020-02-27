# -*- coding: utf-8 -*-
##
# Copyright 2009-2020 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
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
EasyBuild support for installing Gurobi, implemented as an easyblock

@author: Bob Dröge (University of Groningen)
modified by James Carpenter (University of Birmingham)
"""
import os

from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


class EB_Gurobi(Tarball):
    """Support for installing linux64 version of Gurobi."""

    def install_step(self):
        """Install Gurobi and license file."""

        # Check if the client license file is already defined in the appropriate easyconfig variable
        licfile = self.cfg['license_file']
        if licfile is None:
            # Fallback to standard Gurobi license file environment variable
            licfile = os.getenv('GRB_LICENSE_FILE')
            if licfile is None:
                raise EasyBuildError("No license file specified in either the "
                                     "easyconfig or as GRB_LICENSE_FILE env var")

        if not os.path.exists(licfile):
            raise EasyBuildError("The provided license_file value \"%s\" is not a valid path", licfile)

        super(EB_Gurobi, self).install_step()

        # Copy the license file to the install dir only if it was specified in the easyconfig
        if self.cfg['license_file']:
            copy_file(licfile, os.path.join(self.installdir, 'gurobi.lic'))

        if get_software_root('Python'):
            run_cmd("python setup.py install --prefix=%s" % self.installdir)

    def sanity_check_step(self):
        """Custom sanity check for Gurobi."""
        custom_paths = {
            'files': ['bin/%s' % f for f in ['grbprobe', 'grbtune', 'gurobi_cl', 'gurobi.sh']],
            'dirs': [],
        }

        custom_commands = []
        if get_software_root('Python'):
            custom_commands.append("python -c 'import gurobipy'")

        super(EB_Gurobi, self).sanity_check_step(custom_commands=custom_commands, custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom extra module file entries for Gurobi."""
        txt = super(EB_Gurobi, self).make_module_extra()
        txt += self.module_generator.set_environment('GUROBI_HOME', self.installdir)

        # Only define GRB_LICENSE_FILE env var if it doesn't already exist
        if not os.getenv("GRB_LICENSE_FILE"):
            txt += self.module_generator.set_environment('GRB_LICENSE_FILE',
                                                         os.path.join(self.installdir, 'gurobi.lic'))

        if get_software_root('Python'):
            txt += self.module_generator.prepend_paths('PYTHONPATH', det_pylibdir())

        return txt
