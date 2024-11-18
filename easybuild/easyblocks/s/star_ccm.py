##
# Copyright 2018-2024 Ghent University
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
EasyBuild support for building and installing STAR-CCM+, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os
import tempfile
import stat

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.config import build_option
from easybuild.tools.filetools import change_dir, find_glob_pattern, adjust_permissions, copy_file
from easybuild.tools.run import run_cmd


class EB_STAR_minus_CCM_plus_(EasyBlock):
    """Support for building/installing STAR-CCM+."""

    def __init__(self, *args, **kwargs):
        """Initialise STAR-CCM+ easyblock."""
        super(EB_STAR_minus_CCM_plus_, self).__init__(*args, **kwargs)
        self.starccm_subdir = None
        self.starview_subdir = None

    # adding an extract_step to support Siemens distributions with extension .aol
    def extract_step(self):
        # Siemens distributions are tarballs or executables with .aol extension
        if self.src[0]['name'].endswith('.aol'):
            self.aol_install = True
        else:
            self.aol_install = False

        if self.aol_install:
            # required for correctly guessing start directory
            self.src[0]['finalpath'] = self.builddir

            # copy the .aol to build dir
            for source in self.src:
                dst = os.path.join(self.builddir, source['name'])
                copy_file(source['path'], dst)
                adjust_permissions(dst, stat.S_IRWXU, add=True)
        else:
            EasyBlock.extract_step(self)

    def configure_step(self):
        """No configuration procedure for STAR-CCM+."""
        pass

    def build_step(self):
        """No build procedure for STAR-CCM+."""
        pass

    def install_step(self):
        """Custom install procedure for STAR-CCM+."""

        if self.aol_install:
            install_script_pattern = "./STAR-CCM+*.aol"
        else:
            install_script_pattern = "./STAR-CCM+%s_*.sh" % self.version

        if self.dry_run:
            install_script = install_script_pattern
        else:
            install_script = find_glob_pattern(install_script_pattern)

        # depending of the target filesystem the check for available disk space may fail, so disable it;
        # note that this makes the installer exit with non-zero exit code...
        env.setvar('CHECK_DISK_SPACE', 'OFF')

        env.setvar('IATEMPDIR', tempfile.mkdtemp())

        # argument -DINSTALLFLEX is -DINSTALL_LICENSING for the .aol installer
        if self.aol_install:
            cmd = ' '.join([
                self.cfg['preinstallopts'],
                # The install_script installs also the Siemens Installer Program (SIP)
                # under $HOME, this is not need to run STAR-CCM+
                'HOME=%s' % self.builddir,
                install_script,
                "-i silent",
                # for some reason the installation directory's name cannot be the version
                # So using builddir and then moving to installdir
                "-DINSTALLDIR=%s" % self.builddir,
                "-DINSTALL_LICENSING=false",
                "-DADDSYSTEMPATH=false",
                self.cfg['installopts'],
                "&& mv %s/%s %s" % (self.builddir, self.version, self.installdir),
            ])
        else:
            cmd = ' '.join([
                self.cfg['preinstallopts'],
                install_script,
                "-i silent",
                "-DINSTALLDIR=%s" % self.installdir,
                "-DINSTALLFLEX=false",
                "-DADDSYSTEMPATH=false",
                self.cfg['installopts'],
            ])

        # ignore exit code of command, since there's always a non-zero exit if $CHECK_DISK_SPACE is set to OFF;
        # rely on sanity check to catch problems with the installation
        run_cmd(cmd, log_all=False, log_ok=False, simple=False)

    def find_starccm_subdirs(self):
        """Determine subdirectory of install directory in which STAR-CCM+ was installed."""
        starccm_subdir_pattern = os.path.join(self.version + '*', 'STAR-CCM+%s*' % self.version)

        if self.dry_run:
            self.starccm_subdir = starccm_subdir_pattern
        else:
            # take into account that install directory may not exist or be totally empty,
            # for example when --module-only --force is used
            try:
                cwd = change_dir(self.installdir)
                self.starccm_subdir = find_glob_pattern(starccm_subdir_pattern)
                self.log.info("Found STAR-CCM+ subdirectory: %s", self.starccm_subdir)
                change_dir(cwd)
            except Exception:
                if build_option('module_only') and build_option('force'):
                    self.starccm_subdir = starccm_subdir_pattern
                else:
                    raise

        self.starview_subdir = os.path.join(os.path.dirname(self.starccm_subdir), 'STAR-View+%s' % self.version)

    def sanity_check_step(self):
        """Custom sanity check for STAR-CCM+."""
        if self.starccm_subdir is None or self.starview_subdir is None:
            self.find_starccm_subdirs()

        custom_paths = {
            'files': [os.path.join(self.installdir, self.starccm_subdir, 'star', 'bin', 'starccm+'),
                      os.path.join(self.installdir, self.starview_subdir, 'bin', 'starview+')],
            'dirs': [],
        }
        custom_commands = ["starccm+ --help 2>&1 | grep 'Usage: '"]
        super(EB_STAR_minus_CCM_plus_, self).sanity_check_step(
            custom_paths=custom_paths,
            custom_commands=custom_commands
        )
    def make_module_extra(self):
        """Extra statements specific to STAR-CCM+ to include in generated module file."""
        if self.starccm_subdir is None or self.starview_subdir is None:
            self.find_starccm_subdirs()

        txt = super(EB_STAR_minus_CCM_plus_, self).make_module_extra()

        bin_dirs = [
            os.path.join(self.starccm_subdir, 'star', 'bin'),
            os.path.join(self.starview_subdir, 'bin'),
        ]
        txt += self.module_generator.prepend_paths('PATH', bin_dirs)

        return txt
