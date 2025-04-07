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
EasyBuild support for OpenSSL, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Davide Vanzo (ACCRE - Vanderbilt University)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os
import re

from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.filetools import remove_dir, symlink
from easybuild.tools.run import RunShellCmdError, run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext

GENERIC_SSL_CERTS_DIR = "/etc/ssl/certs"


class EB_OpenSSL(ConfigureMake):
    """Support for building OpenSSL"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to OpenSSL"""
        extra_vars = ConfigureMake.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'ssl_certificates': [None, "Absolute path to 'certs' directory with the system SSL certificates", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for OpenSSL"""
        super(EB_OpenSSL, self).__init__(*args, **kwargs)

        # path to SSL certificates
        ssl_certs_dir = self.cfg.get('ssl_certificates')

        if ssl_certs_dir is not None:
            # check option ssl_certificates
            ssl_certs_dir = os.path.normpath(ssl_certs_dir)
            if not os.path.isabs(ssl_certs_dir):
                raise EasyBuildError("ssl_certificates is not an absolute path: %s", ssl_certs_dir)
            if os.path.basename(ssl_certs_dir) != 'certs':
                raise EasyBuildError("ssl_certificates does not point to a 'certs' directory: %s", ssl_certs_dir)
            if not os.path.isdir(ssl_certs_dir):
                raise EasyBuildError("ssl_certificates 'certs' directory does not exist: %s", ssl_certs_dir)
        else:
            # set ssl_certs_dir from system OPENSSLDIR
            openssldir = ''
            openssldir_regex = re.compile(r'^OPENSSLDIR: "(.*)"$')
            openssldir_cmd = "openssl version -d"

            try:
                res = run_shell_cmd(openssldir_cmd, hidden=True)
                openssldir = openssldir_regex.search(res.output).group(1)
            except RunShellCmdError:
                self.log.info("OPENSSLDIR not found in system (openssl command failed), "
                              "continuing with generic OPENSSLDIR path...")
            except AttributeError:
                self.log.debug("OPENSSLDIR not found in system (openssl reported '%s'), "
                               "continuing with generic OPENSSLDIR path...", res.output)
            else:
                self.log.info("OPENSSLDIR determined from system openssl: %s", openssldir)

            if os.path.isdir(openssldir):
                ssl_certs_dir = os.path.join(openssldir, 'certs')
            elif os.path.isdir(GENERIC_SSL_CERTS_DIR):
                # fallback to generic OPENSSLDIR
                ssl_certs_dir = GENERIC_SSL_CERTS_DIR
                self.log.info("Falling back to generic SSL certificates directory: %s", ssl_certs_dir)
            else:
                self.log.info("Generic SSL certificates directory not found: %s", GENERIC_SSL_CERTS_DIR)

        self.ssl_certs_dir = ssl_certs_dir
        self.log.debug("SSL certificates directory: %s", self.ssl_certs_dir)

    def configure_step(self, cmd_prefix=''):
        """
        Configure step
        """

        cmd = "%s %s./config --prefix=%s threads shared %s" % (self.cfg['preconfigopts'], cmd_prefix,
                                                               self.installdir, self.cfg['configopts'])

        res = run_shell_cmd(cmd)

        return res.output

    def install_step(self):
        """Installation of OpenSSL and SSL certificates"""
        super(EB_OpenSSL, self).install_step()

        # SSL certificates
        # OPENSSLDIR is already populated by the installation of OpenSSL
        # try to symlink system certificates in the empty 'certs' directory
        ssl_dir = os.path.join(self.installdir, 'ssl')
        openssl_certs_dir = os.path.join(ssl_dir, 'certs')

        if self.ssl_certs_dir:
            remove_dir(openssl_certs_dir)
            symlink(self.ssl_certs_dir, openssl_certs_dir)

            # also symlink cert.pem file, if it exists
            # (required on CentOS 7, see https://github.com/easybuilders/easybuild-easyconfigs/issues/14058)
            cert_pem_path = os.path.join(os.path.dirname(self.ssl_certs_dir), 'cert.pem')
            if os.path.isfile(cert_pem_path):
                symlink(cert_pem_path, os.path.join(ssl_dir, os.path.basename(cert_pem_path)))
        else:
            print_warning("OpenSSL successfully installed without system SSL certificates. "
                          "Some packages might experience limited functionality.")

    def sanity_check_step(self):
        """Custom sanity check"""

        # basic paths
        custom_paths = {
            'files': ['bin/openssl'],
            'dirs': ['include', 'ssl'],
        }

        # add libraries
        lib_dir = 'lib'
        lib_sonames = ['libcrypto', 'libssl']
        shlib_ext = get_shared_lib_ext()
        lib_files = [os.path.join(lib_dir, '%s.%s') % (x, y) for x in lib_sonames for y in ['a', shlib_ext]]

        custom_paths['files'].extend(lib_files)

        # add engines
        engines_dir = 'engines'
        if LooseVersion(self.version) >= LooseVersion("1.1"):
            engines_dir = 'engines-1.1'

        custom_paths['dirs'].append(os.path.join(lib_dir, engines_dir))

        # add SSL certificates
        if self.ssl_certs_dir:
            custom_paths['dirs'].append('ssl/certs')

        super(EB_OpenSSL, self).sanity_check_step(custom_paths=custom_paths)
