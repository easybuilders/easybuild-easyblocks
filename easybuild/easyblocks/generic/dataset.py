##
# Copyright 2009-2023 Ghent University
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
EasyBuild support for installing datasets

@author: Samuel Moors (Vrije Universiteit Brussel)
"""
from easybuild.framework.easyblock import EasyBlock
from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig.default import CUSTOM
from easybuild.tools.filetools import remove_file


class Dataset(Binary):
    """Support for installing datasets"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Data easyblock."""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'extract_sources': [True, "Whether or not to extract sources", CUSTOM],
            'data_install_path': [None, "Custom installation path for datasets", CUSTOM],
            'cleanup_sources': [True, "Whether or not to delete the sources after installation", CUSTOM]
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize Dataset-specific variables."""
        self.is_data = True
        super(Dataset, self).__init__(*args, **kwargs)

        if self.cfg['data_install_path']:
            self.installdir = self.cfg['data_install_path']

        # extract sources directly into installation directory
        self.build_in_installdir = True

    def install_step(self):
        """No install step, datasets are extracted directly into installdir"""
        pass

    def cleanup_step(self):
        """Cleanup sources after installation"""
        if self.cfg['cleanup_sources']:
            for src in self.src:
                self.log.info("Removing source %s" % src['name'])
                remove_file(src['path'])
        super(Dataset, self).cleanup_step()
