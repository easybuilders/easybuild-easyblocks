##
# Copyright 2018 Free University of Brussels
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
@author: Ward Poelmans (Free University of Brussels)
"""
import glob
import os
import stat

from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, apply_regex_substitutions, copy_file, write_file


class EB_BWISE(MakeCp):
    """
    Custom easyblock to install BWISE
    """
    @staticmethod
    def extra_options(extra_vars=None):
        """Change default values of options"""
        extra = MakeCp.extra_options()
        # files_to_copy is not mandatory here
        extra['files_to_copy'][2] = CUSTOM
        return extra

    def build_step(self, verbose=False, path=None):
        """Run multiple times for different sources"""

        makefiles_fixes = [
            (r'^CC=.*$', 'CC=$(CXX)'),
            (r'^CFLAGS=.*$', 'CFLAGS:=$(CFLAGS)'),
            (r'^LDFLAGS=.*$', 'LDFLAGS:=$(LDFLAGS) -fopenmp')
        ]

        os.chdir(self.builddir)
        # first BWISE itself
        bwisepath = glob.glob('BWISE-*')
        if bwisepath:
            os.chdir(os.path.join(bwisepath[0], 'src'))
        else:
            raise EasyBuildError("Could not find BWISE path")

        apply_regex_substitutions('makefile', makefiles_fixes)
        apply_regex_substitutions('../Bwise.py', [(r'^BWISE_MAIN = .*$', 'BWISE_MAIN = os.environ[\'EBROOTBWISE\']')])
        super(EB_BWISE, self).build_step()

        # Onwards to BGREAT
        os.chdir(self.builddir)
        bgreatpath = glob.glob('BGREAT2-*')
        if bgreatpath:
            os.chdir(bgreatpath[0])
        else:
            raise EasyBuildError("Could not find BGREAT path")
        apply_regex_substitutions('makefile', makefiles_fixes)
        super(EB_BWISE, self).build_step()
        copy_file('bgreat', self.cfg['start_dir'])

        # Finally, BTRIM
        os.chdir(self.builddir)
        btrimpath = glob.glob('BTRIM-*')
        if btrimpath:
            os.chdir(btrimpath[0])
        else:
            raise EasyBuildError("Could not find BTRIM path")
        apply_regex_substitutions('makefile', makefiles_fixes)
        super(EB_BWISE, self).build_step()
        copy_file('btrim', self.cfg['start_dir'])

        binaries = ['sequencesToNumbers', 'numbersFilter', 'path_counter', 'maximal_sr', 'simulator',
                    'path_to_kmer', 'K2000/*.py', 'K2000/*.sh']
        self.cfg['files_to_copy'] = [(['bgreat', 'btrim', 'Bwise.py'] + ['src/%s' % x for x in binaries], 'bin'),
                                     'data']

    def install_step(self):
        super(EB_BWISE, self).install_step()

        # BWISE expects it to be at this location...
        txt = """#!/bin/sh
        bcalm "$@"
        """
        write_file(os.path.join(self.installdir, "bin", "bcalm"), txt)

        adjust_permissions(os.path.join(self.installdir, "bin"), stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
