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
General EasyBuild support for software with a binary installer

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

import shutil
import os
import stat

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_file, mkdir, remove_dir
from easybuild.tools.run import run_cmd


PREPEND_TO_PATH_DEFAULT = ['']


class Binary(EasyBlock):
    """
    Support for installing software that comes in binary form.
    Just copy the sources to the install dir, or use the specified install command.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Binary easyblock."""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'extract_sources': [False, "Whether or not to extract sources", CUSTOM],
            'install_cmd': [None, "Install command to be used.", CUSTOM],
            'install_cmds': [None, "List of install commands to be used.", CUSTOM],
            # staged installation can help with the hard (potentially faulty) check on available disk space
            'staged_install': [False, "Perform staged installation via subdirectory of build directory", CUSTOM],
            'prepend_to_path': [PREPEND_TO_PATH_DEFAULT, "Prepend the given directories (relative to install-dir) to "
                                                         "the environment variable PATH in the module file. Default "
                                                         "is the install-dir itself.", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize Binary-specific variables."""
        super(Binary, self).__init__(*args, **kwargs)

        self.actual_installdir = None
        if self.cfg.get('staged_install', False):
            self.actual_installdir = self.installdir
            self.installdir = os.path.join(self.builddir, 'staged')
            mkdir(self.installdir, parents=True)
            self.log.info("Performing staged installation via %s" % self.installdir)

    def extract_step(self):
        """Copy all source files to the build directory"""

        if self.cfg.get('extract_sources', False):
            super(Binary, self).extract_step()
        else:
            # required for correctly guessing start directory
            self.src[0]['finalpath'] = self.builddir

            # copy source to build dir
            for source in self.src:
                dst = os.path.join(self.builddir, source['name'])
                copy_file(source['path'], dst)
                adjust_permissions(dst, stat.S_IRWXU, add=True)

    def configure_step(self):
        """No configuration, this is binary software"""
        pass

    def build_step(self):
        """No compilation, this is binary software"""
        pass

    def install_step(self):
        """Copy all files in build directory to the install directory"""
        install_cmd = self.cfg.get('install_cmd', None)
        install_cmds = self.cfg.get('install_cmds', [])

        if install_cmd is None and install_cmds is None:
            try:
                # shutil.copytree doesn't allow the target directory to exist already
                remove_dir(self.installdir)
                shutil.copytree(self.cfg['start_dir'], self.installdir, symlinks=self.cfg['keepsymlinks'])
            except OSError as err:
                raise EasyBuildError("Failed to copy %s to %s: %s", self.cfg['start_dir'], self.installdir, err)
        else:
            if install_cmd:
                if not install_cmds:
                    install_cmds = [install_cmd]
                    install_cmd = None
                else:
                    raise EasyBuildError("Don't use both install_cmds and install_cmd, pick one!")

            if isinstance(install_cmds, (list, tuple)):
                for install_cmd in install_cmds:
                    cmd = ' '.join([self.cfg['preinstallopts'], install_cmd, self.cfg['installopts']])
                    self.log.info("Running install command for %s: '%s'..." % (self.name, cmd))
                    run_cmd(cmd, log_all=True, simple=True)
            else:
                raise EasyBuildError("Incorrect value type for install_cmds, should be list or tuple: ",
                                     install_cmds)

    def post_install_step(self):
        """Copy installation to actual installation directory in case of a staged installation."""
        if self.cfg.get('staged_install', False):
            staged_installdir = self.installdir
            self.installdir = self.actual_installdir
            try:
                # copytree expects target directory to not exist yet
                if os.path.exists(self.installdir):
                    remove_dir(self.installdir)
                shutil.copytree(staged_installdir, self.installdir)
            except OSError as err:
                raise EasyBuildError("Failed to move staged install from %s to %s: %s",
                                     staged_installdir, self.installdir, err)

        super(Binary, self).post_install_step()

    def sanity_check_rpath(self):
        """Skip the rpath sanity check, this is binary software"""
        self.log.info("RPATH sanity check is skipped when using %s easyblock (derived from Binary)",
                      self.__class__.__name__)

    def make_module_extra(self):
        """Add the specified directories to the PATH."""

        txt = super(Binary, self).make_module_extra()
        prepend_to_path = self.cfg.get('prepend_to_path', PREPEND_TO_PATH_DEFAULT)
        if prepend_to_path:
            txt += self.module_generator.prepend_paths("PATH", prepend_to_path)
        self.log.debug("make_module_extra added this: %s" % txt)
        return txt
