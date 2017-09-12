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
    """Custom easyblock for OpenKIM"""

    def extract_step(self):
        """
        Unpack the source files.

        The main file is unpacked as usual, all model files are
        unpacked into the right subdirectories.
        """
        main_src = self.src[0]
        self.log.info("Unpacking main source %s to %s", main_src['name'], self.builddir)
        main_unpack_dir = extract_file(main_src['path'], self.builddir, cmd=main_src['cmd'],
                                       extra_options=self.cfg['unpack_options'])
        if main_unpack_dir:
            main_src['finalpath'] = main_unpack_dir
        else:
            raise EasyBuildError("Failed to unpack %s", main_src['name'])

        # Now unpack the models and model drivers.
        for idx, src in enumerate(self.src[1:]):
            if src['name'].startswith('MD_'):
                targetdir = os.path.join(main_unpack_dir, 'src', 'model_drivers')
            elif src['name'].startswith('MO_'):
                targetdir = os.path.join(main_unpack_dir, 'src', 'models')
            else:
                raise EasyBuildError("Don't know where to unpack unrecognized source file %s", src['name'])

            self.log.info("Unpacking source %s to %s" % (src['name'], targetdir))
            srcdir = extract_file(src['path'], targetdir, cmd=src['cmd'], extra_options=self.cfg['unpack_options'])
            if srcdir:
                self.src[idx+1]['finalpath'] = srcdir
            else:
                raise EasyBuildError("Unpacking source %s failed", src['name'])

    def make_module_extra(self):
        """Also define $KIM_HOME in generated module."""
        txt = super(EB_OpenKIM, self).make_module_extra()
        txt += self.module_generator.set_environment('KIM_HOME', self.installdir)
        return txt
