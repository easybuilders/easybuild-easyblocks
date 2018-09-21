##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for software that uses the GNU installation procedure,
i.e. configure/make/make install, implemented as an easyblock.

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Toon Willems (Ghent University)
@author: Alan O'Cais (Juelich Supercomputing Centre)
"""

import os
import stat

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import print_warning
from easybuild.tools.config import source_paths
from easybuild.tools.version import EASYBLOCKS_VERSION
from easybuild.tools.filetools import adjust_permissions, download_file, read_file, remove_file, verify_checksum
from easybuild.tools.run import run_cmd

CONFIG_DOT_GUESS_URL_STUB = "https://git.savannah.gnu.org/gitweb/?p=config.git;a=blob_plain;f=config.guess;hb="
CONFIG_DOT_GUESS_COMMIT_ID = "59e2ce0e6b46bb47ef81b68b600ed087e14fdaad"
CONFIG_DOT_GUESS_SHA256 = "c02eb9cc55c86cfd1e9a794e548d25db5c9539e7b2154beb649bc6e2cbffc74c"


class ConfigureMake(EasyBlock):
    """
    Support for building and installing applications with configure/make/make install
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to ConfigureMake."""
        extra_vars = EasyBlock.extra_options(extra=extra_vars)
        extra_vars.update({
            'configure_cmd_prefix': ['', "Prefix to be glued before ./configure", CUSTOM],
            'prefix_opt': [None, "Prefix command line option for configure script ('--prefix=' if None)", CUSTOM],
            'tar_config_opts': [False, "Override tar settings as determined by configure.", CUSTOM],
            'build_type': [None, "Type of system package is being configured for, e.g., x86_64-pc-linux-gnu "
                                 "(determined by config.guess shipped with EasyBuild if None)", CUSTOM],
        })
        return extra_vars

    def obtain_config_dot_guess(self, download_source_path=None, search_source_paths=None):
        """
        Locate or download an up-to-date config.guess for use with ConfigureMake

        :param download_source_path: Path to download config.guess to
        :param search_source_paths: Paths to search for config.guess
        :return: Path to config.guess or None
        """
        eb_source_paths = source_paths()
        if download_source_path is None:
            download_source_path = eb_source_paths[0]
        if search_source_paths is None:
            search_source_paths = eb_source_paths

        download_name = 'config.guess'
        download_relpath = os.path.join('generic', 'eb_v' + EASYBLOCKS_VERSION.vstring, 'ConfigureMake', download_name)
        download_url = CONFIG_DOT_GUESS_URL_STUB + CONFIG_DOT_GUESS_COMMIT_ID

        config_dot_guess_path = None

        # Check file exists
        for path in eb_source_paths:
            tmp_config_dot_guess_path = os.path.join(path, download_relpath)
            if os.path.isfile(tmp_config_dot_guess_path):
                config_dot_guess_path = tmp_config_dot_guess_path
                self.log.info("Found recent %s at %s, using it if required.", download_name, config_dot_guess_path)
                break
        # If not try to grab it
        if config_dot_guess_path is None:
            tmp_config_dot_guess_path = os.path.join(download_source_path, download_relpath)
            downloaded_path = download_file(download_name, download_url, tmp_config_dot_guess_path)
            if downloaded_path is not None:
                # Check the SHA256
                if verify_checksum(downloaded_path, CONFIG_DOT_GUESS_SHA256):
                    config_dot_guess_path = downloaded_path
                    # Add execute permissions
                    adjust_permissions(downloaded_path, stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH, add=True)
                    self.log.info("Downloaded recent %s to %s, using it if required.", download_name,
                                  config_dot_guess_path)
                else:
                    self.log.info("Checksum failed for downloaded file %s, not using!", downloaded_path)
                    remove_file(downloaded_path)
            else:
                self.log.info("Failed to download recent %s to %s for use with ConfigureMake easyblock (if needed).",
                              download_name, tmp_config_dot_guess_path)

        return config_dot_guess_path

    def fetch_step(self, *args, **kwargs):
        """Custom fetch step for ConfigureMake so we use an updated config.guess."""
        super(ConfigureMake, self).fetch_step(*args, **kwargs)

        # Use an updated config.guess from a global location (if possible)
        self.config_dot_guess = self.obtain_config_dot_guess()

    def configure_step(self, cmd_prefix=''):
        """
        Configure step
        - typically ./configure --prefix=/install/path style
        """

        if self.cfg.get('configure_cmd_prefix'):
            if cmd_prefix:
                tup = (cmd_prefix, self.cfg['configure_cmd_prefix'])
                self.log.debug("Specified cmd_prefix '%s' is overruled by configure_cmd_prefix '%s'" % tup)
            cmd_prefix = self.cfg['configure_cmd_prefix']

        if self.cfg.get('tar_config_opts'):
            # setting am_cv_prog_tar_ustar avoids that configure tries to figure out
            # which command should be used for tarring/untarring
            # am__tar and am__untar should be set to something decent (tar should work)
            tar_vars = {
                'am__tar': 'tar chf - "$$tardir"',
                'am__untar': 'tar xf -',
                'am_cv_prog_tar_ustar': 'easybuild_avoid_ustar_testing'
            }
            for (key, val) in tar_vars.items():
                self.cfg.update('preconfigopts', "%s='%s'" % (key, val))

        prefix_opt = self.cfg.get('prefix_opt')
        if prefix_opt is None:
            prefix_opt = '--prefix='

        configure_command = cmd_prefix + './configure'

        # Avoid using config.guess from an Autoconf generated package as it is frequently out of date
        # use the version shipped with EB instead and provide the result to the configure command
        build_type_option = ''
        # possible that the configure_command is generated using preconfigopts...we're at the mercy of the gods then
        if 'Generated by GNU Autoconf' in read_file(configure_command):
            build_type = self.cfg.get('build_type')

            if build_type is None:
                config_guess_path = self.config_dot_guess
                if config_guess_path is None:
                    print_warning("No config.guess available, not setting '--build' option for configure step\n"
                                  "EasyBuild attempts to download a recent config.guess but seems to have failed!")
                else:
                    build_type, _ = run_cmd(config_guess_path, log_all=True)
                    build_type = build_type.strip()
                    self.log.info("%s returned a build type %s", config_guess_path, build_type)

            if build_type is not None:
                build_type_option = '--build=' + build_type

        cmd = ' '.join([
            self.cfg['preconfigopts'],
            configure_command,
            prefix_opt + self.installdir,
            build_type_option,
            self.cfg['configopts'],
        ])

        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out

    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        - typical: make -j X
        """

        paracmd = ''
        if self.cfg['parallel']:
            paracmd = "-j %s" % self.cfg['parallel']

        cmd = "%s make %s %s" % (self.cfg['prebuildopts'], paracmd, self.cfg['buildopts'])

        (out, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        return out

    def test_step(self):
        """
        Test the compilation
        - default: None
        """

        if self.cfg['runtest']:
            cmd = "make %s" % (self.cfg['runtest'])
            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            return out

    def install_step(self):
        """
        Create the installation in correct location
        - typical: make install
        """

        cmd = "%s make install %s" % (self.cfg['preinstallopts'], self.cfg['installopts'])

        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out
