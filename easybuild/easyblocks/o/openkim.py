##
# Copyright 2009-2017 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
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
EasyBuild support for the Open Knowledgbase of Interatomic Models

See OpenKIM.org

@author: Jakob Schiotz (Tech. Univ. Denmark)
"""

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.filetools import extract_file
from easybuild.tools.build_log import EasyBuildError
import os

class EB_OpenKIM(ConfigureMake):
    def extract_step(self):
        """
        Unpack the source files.

        The main file is unpacked as usual, all model files are
        unpacked into the right subdirectories.
        """
        driverdir = ('src', 'model_drivers')
        modeldir = ('src', 'models')
        main_unpack_dir = None
        for src in self.src:
            if src['name'].startswith('MD_'):
                assert main_unpack_dir is not None
                targetdir = os.path.join(main_unpack_dir, *driverdir)
            elif src['name'].startswith('MO_'):
                assert main_unpack_dir is not None
                targetdir = os.path.join(main_unpack_dir, *modeldir)
            else:
                targetdir = self.builddir
            self.log.info("Unpacking source %s to %s" % (src['name'],
                                                         targetdir))
            srcdir = extract_file(src['path'], targetdir, cmd=src['cmd'],
                                  extra_options=self.cfg['unpack_options'])
            if srcdir:
                self.src[self.src.index(src)]['finalpath'] = srcdir
                if main_unpack_dir is None:
                    main_unpack_dir = srcdir
                    self.log.info("Detected main unpacking path: %s" 
                                  % (main_unpack_dir,))
            else:
                raise EasyBuildError("Unpacking source %s failed", src['name'])
