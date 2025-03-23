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
import os

from easybuild.framework.easyblock import EasyBlock
from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig.default import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import compute_checksum, create_index, is_readable, mkdir, move_file, remove_file
from easybuild.tools.filetools import symlink
from easybuild.tools.utilities import trace_msg


class Dataset(Binary):
    """Support for installing datasets"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Data easyblock."""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'extract_sources': [True, "Whether or not to extract data sources", CUSTOM],
            'data_install_path': [None, "Custom installation path for datasets", CUSTOM],
            'cleanup_data_sources': [False, "Whether or not to delete the data sources after installation", CUSTOM]
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize Dataset-specific variables."""
        super(Dataset, self).__init__(*args, **kwargs)

        if self.cfg['sources']:
            raise EasyBuildError(
                "Easyconfig parameter 'sources' is not supported for this EasyBlock. Use 'data_sources' instead.")

        if self.cfg['data_install_path']:
            self.installdir = self.cfg['data_install_path']

        # extract/copy sources directly into installation directory
        self.build_in_installdir = True

    def install_step(self):
        """No install step, datasets are extracted directly into installdir"""
        pass

    def post_install_step(self):
        """Add files to object_storage, remove duplicates, add symlinks"""
        trace_msg('adding files to object_storage...')

        # creating object storage at root of software name to reuse identical files in different versions
        object_storage = os.path.join(os.pardir, 'object_storage')
        mkdir(object_storage)
        datafiles = create_index(os.curdir)

        for datafile in datafiles:
            checksum = compute_checksum(datafile, checksum_type='sha256')
            print(datafile, checksum)
            objstor_file = os.path.join(object_storage, checksum)
            if is_readable(objstor_file):
                remove_file(datafile)
            else:
                move_file(datafile, objstor_file)
            # use relative paths for symlinks to easily relocate data installations later on if needed
            symlink(objstor_file, datafile, use_abspath_source=False)
            self.log.debug("Created symlink %s to %s" % (datafile, objstor_file))

    def cleanup_step(self):
        """Cleanup sources after installation"""
        if self.cfg['cleanup_data_sources']:
            for src in self.src:
                self.log.info("Removing data source %s" % src['name'])
                remove_file(src['path'])
        super(Dataset, self).cleanup_step()
