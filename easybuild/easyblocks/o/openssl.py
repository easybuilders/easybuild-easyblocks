##
# Copyright 2009-2022 Ghent University
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
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import remove_dir, symlink
from easybuild.tools.run import run_cmd

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

        # check option ssl_certificates
        ssl_certs_dir = self.cfg.get('ssl_certificates')

        if ssl_certs_dir:
            ssl_certs_dir = os.path.normpath(ssl_certs_dir)
            if not os.path.isabs(ssl_certs_dir):
                raise EasyBuildError("ssl_certificates is not an absolute path: %s", ssl_certs_dir)
            if os.path.basename(ssl_certs_dir) != 'certs':
                raise EasyBuildError("ssl_certificates does not point to a 'certs' directory: %s", ssl_certs_dir)
            if not os.path.isdir(ssl_certs_dir):
                raise EasyBuildError("ssl_certificates 'certs' directory does not exist: %s", ssl_certs_dir)

        self.ssl_certs_dir = ssl_certs_dir

    def configure_step(self, cmd_prefix=''):
        """
        Configure step
        """

        cmd = "%s %s./config --prefix=%s threads shared %s" % (self.cfg['preconfigopts'], cmd_prefix,
                                                               self.installdir, self.cfg['configopts'])

        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out

    def install_step(self):
        """Installation of OpenSSL and SSL certificates"""
        super(EB_OpenSSL, self).install_step()

        # SSL certificates
        # OPENSSLDIR is already populated by the installation of OpenSSL
        # try to symlink system certificates in the empty 'certs' directory
        openssl_certs_dir = os.path.join(self.installdir, 'ssl', 'certs')

        if self.ssl_certs_dir:
            # symlink the provided certificates by the user
            remove_dir(openssl_certs_dir)
            symlink(self.ssl_certs_dir, openssl_certs_dir)

    def sanity_check_step(self):
        """Custom sanity check"""

        libdir = None
        for libdir_cand in ['lib', 'lib64']:
            if os.path.exists(os.path.join(self.installdir, libdir_cand)):
                libdir = libdir_cand

        if libdir is None:
            raise EasyBuildError("Failed to determine library directory.")

        custom_paths = {
            'files': [os.path.join(libdir, x) for x in ['libcrypto.a', 'libcrypto.so', 'libssl.a', 'libssl.so']] +
            ['bin/openssl'],
            'dirs': [],
        }

        if LooseVersion(self.version) < LooseVersion("1.1"):
            custom_paths['files'].extend([os.path.join(libdir, 'libcrypto.so.1.0.0'),
                                          os.path.join(libdir, 'libssl.so.1.0.0')])
            custom_paths['dirs'].append(os.path.join(libdir, 'engines'))
        else:
            custom_paths['files'].extend([os.path.join(libdir, 'libcrypto.so.1.1'),
                                          os.path.join(libdir, 'libssl.so.1.1')])
            custom_paths['dirs'].append(os.path.join(libdir, 'engines-1.1'))

        super(EB_OpenSSL, self).sanity_check_step(custom_paths=custom_paths)
