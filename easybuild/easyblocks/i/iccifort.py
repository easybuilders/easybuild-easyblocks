##
# Copyright 2019-2024 Bart Oldeman, McGill University, Compute Canada
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
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
EasyBuild support for installing the Intel compiler suite, implemented as an easyblock

@author: Bart Oldeman (McGill University, Compute Canada)
"""

import os
from easybuild.easyblocks.icc import EB_icc
from easybuild.easyblocks.ifort import EB_ifort


class EB_iccifort(EB_ifort, EB_icc):
    """
    Class that can be used to install iccifort
    """

    def sanity_check_step(self):
        """Custom sanity check paths for iccifort."""
        EB_icc.sanity_check_step(self)
        EB_ifort.sanity_check_step(self)

    def make_module_extra(self):
        txt = super(EB_iccifort, self).make_module_extra()

        # also define $EBROOT* and $EBVERSION* for icc/ifort
        txt += self.module_generator.set_environment('EBROOTICC', self.installdir)
        txt += self.module_generator.set_environment('EBROOTIFORT', self.installdir)
        txt += self.module_generator.set_environment('EBVERSIONICC', self.version)
        txt += self.module_generator.set_environment('EBVERSIONIFORT', self.version)

        return txt

    def make_module_req_guess(self):
        # Use EB_icc because its make_module_req_guess deliberately omits 'include' for CPATH:
        # including it causes problems, e.g. with complex.h and std::complex
        # cfr. https://software.intel.com/en-us/forums/intel-c-compiler/topic/338378
        # whereas EB_ifort adds 'include' but that's only needed if icc and ifort are separate
        guesses = EB_icc.make_module_req_guess(self)

        # remove entries from LIBRARY_PATH that icc and co already know about at compile time
        # only do this for iccifort merged installations so that icc can still find ifort
        # libraries and vice versa for split installations
        if self.comp_libs_subdir is not None:
            compiler_library_paths = [os.path.join(self.comp_libs_subdir, p)
                                      for p in ('lib', 'compiler/lib/intel64', 'lib/ia32', 'lib/intel64')]
            guesses['LIBRARY_PATH'] = [p for p in guesses['LIBRARY_PATH'] if p not in compiler_library_paths]
        return guesses
