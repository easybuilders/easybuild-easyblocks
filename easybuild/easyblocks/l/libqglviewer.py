##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for building and installing libQGLViewer, implemented as an easyblock

@author: Javier Antonio Ruiz Bosch (Central University "Marta Abreu" of Las Villas, Cuba)
"""

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.tools.modules import get_software_root
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools import LooseVersion


class EB_libQGLViewer(ConfigureMake):
    """Support for building/installing libQGLViewer."""

    def configure_step(self):
        """Custom configuration procedure for libQGLViewer: qmake PREFIX=/install/path ..."""

        cmd = "%(preconfigopts)s qmake PREFIX=%(installdir)s %(configopts)s" % {
            'preconfigopts': self.cfg['preconfigopts'],
            'installdir': self.installdir,
            'configopts': self.cfg['configopts'],
        }
        run_shell_cmd(cmd)

    def sanity_check_step(self):
        """Custom sanity check for libQGLViewer."""
        shlib_ext = get_shared_lib_ext()
        """
        From version 2.8.0 onwards qt version also gets added to the lib file names.
        """
        if LooseVersion(self.version) < LooseVersion("2.8.0"):
            suffix = ''
        else:
            for dep in ['Qt5', 'Qt6']:
                if get_software_root(dep):
                    suffix = '-' + dep.lower()
                    break
            else:
                raise EasyBuildError("Missing Qt5 or Qt6 dependency")
        custom_paths = {
            'files': [('lib/libQGLViewer'+suffix+'.prl', 'lib64/libQGLViewer'+suffix+'.prl'),
                      ('lib/libQGLViewer'+suffix+'.%s' % shlib_ext,
                       'lib64/libQGLViewer'+suffix+'.%s' % shlib_ext)],
            'dirs': ['include/QGLViewer'],
        }

        super(EB_libQGLViewer, self).sanity_check_step(custom_paths=custom_paths)
