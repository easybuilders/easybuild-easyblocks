##
# Copyright 2009-2020 Ghent University
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
EasyBuild support for installing (precompiled) software which is supplied as a tarball,
implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import copy_dir, remove_dir
from easybuild.tools.run import run_cmd


class Tarball(EasyBlock):
    """
    Precompiled software supplied as a tarball:
    - will unpack binary and copy it to the install dir
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Tarball."""
        extra_vars = EasyBlock.extra_options(extra=extra_vars)
        extra_vars.update({
            'final_dir': [None, "Override default installation path with provided path", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize easyblock."""
        super(Tarball, self).__init__(*args, **kwargs)

    def configure_step(self):
        """
        Dummy configure method
        """
        pass

    def build_step(self):
        """
        Dummy build method: nothing to build
        """
        pass

    def install_step(self, src=None):
        """Install by copying from specified source directory (or 'start_dir' if not specified)."""

        # Run preinstallopts before copy of source directory
        if self.cfg['preinstallopts']:
            preinstall_opts = self.cfg['preinstallopts'].split('&&')
            preinstall_cmd = '&&'.join([opt for opt in preinstall_opts if opt and not opt.isspace()])
            self.log.info("Preparing installation of %s using command '%s'..." % (self.name, preinstall_cmd))
            run_cmd(preinstall_cmd, log_all=True, simple=True)

        # Copy source directory
        source_path = src or self.cfg['start_dir']
        install_path = self.cfg['final_dir'] or self.installdir
        self.log.info("Copying tarball contents of %s to %s..." % (self.name, install_path))
        remove_dir(install_path)
        copy_dir(source_path, install_path, symlinks=self.cfg['keepsymlinks'])

    def sanity_check_rpath(self):
        """Skip the rpath sanity check, this is binary software"""
        self.log.info("RPATH sanity check is skipped when using %s easyblock (derived from Tarball)",
                      self.__class__.__name__)
