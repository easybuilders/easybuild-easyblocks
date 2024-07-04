##
# Copyright 2009-2024 Ghent University
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
@author: Pavel Grochal (INUITS)
"""

import os

from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_dir, extract_file, remove_dir
from easybuild.tools.run import run_cmd


class Tarball(ExtensionEasyBlock):
    """
    Precompiled software supplied as a tarball: will unpack binary and copy it to the install dir
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Tarball."""
        extra_vars = ExtensionEasyBlock.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'install_type': [None, "Defaults to extract tarball into clean directory. Options: 'merge' merges tarball "
                             "to existing directory, 'subdir' extracts tarball into its own sub-directory", CUSTOM],
            'preinstall_cmd': [None, "Command to execute before installation", CUSTOM],
        })
        return extra_vars

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

    def run(self, *args, **kwargs):
        """Install as extension: unpack sources and copy (via install step)."""
        if self.cfg['install_type'] is None:
            self.log.info("Auto-enabled install_type=merge because Tarball is being used to install an extension")
            self.cfg['install_type'] = 'merge'
        # unpack sources and call install_step to copy unpacked sources to install directory
        srcdir = extract_file(self.src, self.builddir, change_into_dir=False)
        kwargs['src'] = srcdir
        self.install_step(*args, **kwargs)

    def install_step(self, src=None):
        """Install by copying from specified source directory (or 'start_dir' if not specified)."""

        # Run preinstallopts and/or preinstall_cmd before copy of source directory
        preinstall_cmd = None
        if self.cfg['preinstallopts']:
            preinstall_opts = self.cfg['preinstallopts'].split('&&')
            preinstall_cmd = '&&'.join([opt for opt in preinstall_opts if opt and not opt.isspace()])
        if self.cfg['preinstall_cmd']:
            preinstall_cmd = '&& '.join([cmd for cmd in [preinstall_cmd, self.cfg['preinstall_cmd']] if cmd])
        if preinstall_cmd:
            self.log.info("Preparing installation of %s using command '%s'..." % (self.name, preinstall_cmd))
            run_cmd(preinstall_cmd, log_all=True, simple=True)

        # Copy source directory
        source_path = src or self.cfg['start_dir']

        if self.cfg['install_type'] == 'subdir':
            # Wipe and install in a sub-directory with the name of the package
            install_path = os.path.join(self.installdir, self.name.lower())
            dirs_exist_ok = False
            install_logmsg = "Copying tarball contents of %s to sub-directory %s..."
        elif self.cfg['install_type'] == 'merge':
            # Enable merging with root of existing installdir
            install_path = self.installdir
            dirs_exist_ok = True
            install_logmsg = "Merging tarball contents of %s into %s..."
        elif self.cfg['install_type'] is None:
            # Wipe and copy root of installation directory (default)
            install_path = self.installdir
            dirs_exist_ok = False
            install_logmsg = "Copying tarball contents of %s into %s after wiping it..."
        else:
            raise EasyBuildError("Unknown option '%s' for index_type.", self.cfg['install_type'])

        self.log.info(install_logmsg, self.name, install_path)

        if not dirs_exist_ok:
            remove_dir(install_path)

        copy_dir(source_path, install_path, symlinks=self.cfg['keepsymlinks'], dirs_exist_ok=dirs_exist_ok)

    def sanity_check_rpath(self):
        """Skip the rpath sanity check, this is binary software"""
        self.log.info("RPATH sanity check is skipped when using %s easyblock (derived from Tarball)",
                      self.__class__.__name__)
