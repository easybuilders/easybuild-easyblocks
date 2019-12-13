##
# Copyright 2009-2019 Ghent University
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
EasyBuild support for ELSI, implemented as an easyblock

@author: Miguel Dias Costa (National University of Singapore)
"""
import os
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.modules import get_software_root, get_software_version


class EB_ELSI(CMakeMake):
    """Support for building ELSI."""

    @staticmethod
    def extra_options():
        """Define custom easyconfig parameters for ELSI."""

        extra_vars = {
            'enable_pexsi': [False, "Enable PEXSI solver", CUSTOM],
        }

        return CMakeMake.extra_options(extra_vars)

    def configure_step(self):
        """Custom configure procedure for ELSI."""

        self.cfg['separate_build_dir'] = True

        if self.cfg['enable_pexsi']:
            self.cfg.update('configopts', "-DENABLE_PEXSI=1")

        if self.cfg['runtest']:
            self.cfg.update('configopts', "-DENABLE_TESTS=1")
            self.cfg.update('configopts', "-DENABLE_C_TESTS=1")
            self.cfg['runtest'] = 'test'

        libs = [lib[3:-2] for lib in os.environ['SCALAPACK_STATIC_LIBS'].split(',')]

        elpa = get_software_root('ELPA')
        if elpa:
            self.log.info("Using external ELPA.")
            elpa_ver = get_software_version('ELPA')
            self.cfg.update('configopts', "-DUSE_EXTERNAL_ELPA=1")
            self.cfg.update('configopts', "-DINC_PATHS='%s/include/elpa-%s/modules'" % (elpa, elpa_ver))
            self.cfg.update('configopts', "-DLIB_PATHS='%s/lib'" % elpa)
            libs = ['elpa'] + libs
        else:
            self.log.info("No external ELPA specified as dependency, building internal ELPA.")

        self.cfg.update('configopts', "-DLIBS='%s'" % ';'.join(libs))

        super(EB_ELSI, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for ELSI."""

        libs = ['elsi']
        modules = ['elsi']

        if self.cfg['enable_pexsi']:
            libs.append('pexsi')
            modules.append('elsi_pexsi')

        custom_paths = {
            'files': ['include/%s.mod' % mod for mod in modules] + ['lib/lib%s.a' % lib for lib in libs],
            'dirs': [],
        }

        super(EB_ELSI, self).sanity_check_step(custom_paths=custom_paths)
