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
        self.log.info("Unpacking main source %s to %s",
                      self.src[0]['name'], self.builddir)
        main_unpack_dir = extract_file(self.src[0]['path'], self.builddir, 
            cmd=self.src[0]['cmd'], extra_options=self.cfg['unpack_options'])
        if not main_unpack_dir:
            raise EasyBuildError("Failed to unpack %s", self.src[0]['name'])
        self.src[0]['finalpath'] = main_unpack_dir

        # Now unpack the models and model drivers.
        for idx, src in enumerate(self.src[1:]):
            if src['name'].startswith('MD_'):
                targetdir = os.path.join(main_unpack_dir, *driverdir)
            elif src['name'].startswith('MO_'):
                targetdir = os.path.join(main_unpack_dir, *modeldir)
            else:
                raise EasyBuildError("Don't know where to unpack unrecognized source file %s" % (src['name'],))

            self.log.info("Unpacking source %s to %s" % (src['name'], targetdir))
            srcdir = extract_file(src['path'], targetdir, cmd=src['cmd'],
                                  extra_options=self.cfg['unpack_options'])
            if srcdir:
                self.src[idx+1]['finalpath'] = srcdir
            else:
                raise EasyBuildError("Unpacking source %s failed", src['name'])
