##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for FreeFem++, implemented as an easyblock

@author: Balazs Hajgato (Free University Brussels - VUB)
"""
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.run import run_cmd
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root


class EB_FreeFem(ConfigureMake):
    """Support for building and installing FreeFem++."""

    def configure_step(self):
        """FreeFem++ configure should run twice. First PETSc configured, then PETSc have to be build,
        then configure FreeFem++ with the builded PETSc."""

        # first Autoreconf has to be run
        if not get_software_root('Autotools'):
            raise EasyBuildError("Autoconfig is required to build FreeFem++. Please add it as build dependency")

        run_cmd("autoreconf -i", log_all=True, simple=False)

        # delete old installation, then set keeppreviousinstall to True (do not delete PETsc install)
        self.make_installdir()
        self.cfg['keeppreviousinstall'] = True

        # configure and make petsc-slepc
        cmd = "./configure --prefix=%s &&" % self.installdir
        cmd += "cd download/ff-petsc &&"
        cmd += "make petsc-slepc &&"
        cmd += "cd ../.."
        run_cmd(cmd, log_all=True, simple=False)

        super(EB_FreeFem, self).configure_step()
